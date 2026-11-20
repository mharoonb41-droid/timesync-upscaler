"""
processor.py - Multiprocessing-based parallel rendering pipeline and background worker thread.

Orchestrates:
  Stage 1 (Parallel): Distributes image/video segments to multiprocessing workers
                      for Lanczos upscaling and frame-accurate chunk encoding.
                      All chunks are held in OS private temp storage.
  Stage 2 (Fast Merge): Concat demuxer stream copy and audio muxing into exactly ONE final video.
                        All temporary chunks are immediately wiped.
"""

from __future__ import annotations
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal

from exporter import ExportConfig, FFmpegEngine
from parser import TimestampEntry


def _render_single_chunk_worker(payload: dict) -> dict:
    """
    Top-level worker function for multiprocessing ProcessPoolExecutor.
    Must be picklable across process boundaries on Windows/macOS/Linux.
    """
    idx = payload["index"]
    prompt_id = payload["prompt_id"]
    media_path = payload["media_path"]
    duration = payload["duration"]
    output_path = payload["output_path"]
    is_video = payload.get("is_video", False)

    config = ExportConfig(**payload["config"])

    start_time = time.time()
    try:
        success = FFmpegEngine.render_segment(
            media_path=media_path,
            output_ts_path=output_path,
            duration=duration,
            config=config,
            is_video=is_video
        )
        elapsed = time.time() - start_time
        if success and os.path.isfile(output_path):
            size_kb = os.path.getsize(output_path) / 1024
            return {
                "success": True,
                "index": idx,
                "prompt_id": prompt_id,
                "output_path": output_path,
                "duration": duration,
                "elapsed": elapsed,
                "size_kb": size_kb,
                "error": None
            }
        else:
            return {
                "success": False,
                "index": idx,
                "prompt_id": prompt_id,
                "output_path": output_path,
                "duration": duration,
                "elapsed": elapsed,
                "size_kb": 0,
                "error": f"FFmpeg returned non-zero code for segment {prompt_id}"
            }
    except Exception as e:
        return {
            "success": False,
            "index": idx,
            "prompt_id": prompt_id,
            "output_path": output_path,
            "duration": duration,
            "elapsed": time.time() - start_time,
            "size_kb": 0,
            "error": str(e)
        }


class RenderWorkerThread(QThread):
    """
    Background QThread that drives multiprocessing chunk generation and Stage 2 merge
    into a single final output video without freezing the PySide6 UI.
    """
    progress_updated = Signal(int, int, str, float, str)  # current, total, status, speed_fps, eta_str
    log_message = Signal(str, str)                        # message, level ("INFO", "SUCCESS", "WARNING", "ERROR")
    rendering_completed = Signal(bool, str)               # success, final_output_file_path or error
    stage_changed = Signal(str)                           # stage description

    def __init__(
        self,
        entries: List[TimestampEntry],
        config: ExportConfig,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.entries = [e for e in entries if e.matched_file and os.path.isfile(e.matched_file)]
        self.config = config
        self._is_cancelled = False
        self._temp_dir: Optional[str] = None

    def cancel(self):
        self._is_cancelled = True
        self.log_message.emit("Cancellation requested by user. Aborting workers...", "WARNING")

    def run(self):
        total_segments = len(self.entries)
        if total_segments == 0:
            self.rendering_completed.emit(False, "No valid matched media files to render.")
            return

        start_time = time.time()
        self.log_message.emit(
            f"Starting video generation: {total_segments} prompt scenes | Target: {self.config.width}x{self.config.height} @ {self.config.fps}fps",
            "INFO"
        )
        self.log_message.emit(
            f"Multiprocessing workers: {self.config.num_workers} parallel CPU processes | Encoder: {self.config.encoder}",
            "INFO"
        )

        # Use the OS temporary directory so no chunk files appear in user's working folders
        self._temp_dir = tempfile.mkdtemp(prefix="timesync_internal_chunks_")

        try:
            self.stage_changed.emit("Stage 1/2: Processing & Upscaling All Prompt Scenes")

            payloads: List[dict] = []
            ordered_ts_paths: List[str] = []
            video_extensions = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".gif"}

            total_planned_duration = 0.0
            for i, entry in enumerate(self.entries):
                out_ts = os.path.join(self._temp_dir, f"chunk_{i:04d}_{entry.prompt_id}.ts")
                ordered_ts_paths.append(out_ts)
                total_planned_duration += entry.duration

                is_vid = Path(entry.matched_file).suffix.lower() in video_extensions
                payload = {
                    "index": i,
                    "prompt_id": entry.prompt_id,
                    "media_path": entry.matched_file,
                    "duration": entry.duration,
                    "output_path": out_ts,
                    "is_video": is_vid,
                    "config": asdict(self.config)
                }
                payloads.append(payload)

            completed_count = 0
            total_rendered_duration = 0.0
            results_by_index: Dict[int, dict] = {}

            workers = max(1, min(self.config.num_workers, total_segments))
            with ProcessPoolExecutor(max_workers=workers) as executor:
                future_to_idx = {
                    executor.submit(_render_single_chunk_worker, payload): payload["index"]
                    for payload in payloads
                }

                for future in as_completed(future_to_idx):
                    if self._is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.rendering_completed.emit(False, "Rendering was cancelled by user.")
                        return

                    res = future.result()
                    idx = res["index"]
                    results_by_index[idx] = res
                    completed_count += 1
                    total_rendered_duration += res["duration"]

                    if res["success"]:
                        self.log_message.emit(
                            f"[{completed_count}/{total_segments}] Processed scene for Prompt #{res['prompt_id']} ({res['duration']:.2f}s in {res['elapsed']:.2f}s)",
                            "SUCCESS"
                        )
                    else:
                        self.log_message.emit(
                            f"[{completed_count}/{total_segments}] Scene for Prompt #{res['prompt_id']} failed: {res['error']}",
                            "ERROR"
                        )

                    elapsed_total = time.time() - start_time
                    avg_time_per_segment = elapsed_total / completed_count
                    remaining_segments = total_segments - completed_count
                    eta_seconds = remaining_segments * avg_time_per_segment
                    eta_str = time.strftime("%M:%S", time.gmtime(eta_seconds))

                    rendered_frames = total_rendered_duration * self.config.fps
                    speed_fps = (rendered_frames / elapsed_total) if elapsed_total > 0 else 0.0

                    self.progress_updated.emit(
                        completed_count,
                        total_segments,
                        f"Rendering Scenes ({completed_count}/{total_segments})",
                        speed_fps,
                        eta_str
                    )

            # Check if all chunks succeeded
            failed_segments = [res for res in results_by_index.values() if not res["success"]]
            if failed_segments:
                err_msg = f"{len(failed_segments)} scenes failed to process. Video assembly aborted."
                self.log_message.emit(err_msg, "ERROR")
                self.rendering_completed.emit(False, err_msg)
                return

            # Stage 2: Merge into exactly ONE final video file & attach audio
            self.stage_changed.emit("Stage 2/2: Combining All Scenes & Muxing Audio into 1 Final Video")
            self.log_message.emit("Stage 2: Assembling all scenes into 1 single final video...", "INFO")

            if self.config.audio_path and os.path.isfile(self.config.audio_path):
                self.log_message.emit(f"Synchronizing voiceover audio track: {Path(self.config.audio_path).name}", "INFO")

            final_out = self.config.output_path
            merge_success, merge_msg = FFmpegEngine.concatenate_segments(
                segment_paths=ordered_ts_paths,
                output_file=final_out,
                audio_file=self.config.audio_path,
                total_duration=total_planned_duration
            )

            total_render_time = time.time() - start_time

            if merge_success and os.path.isfile(final_out):
                final_size_mb = os.path.getsize(final_out) / (1024 * 1024)
                self.log_message.emit(
                    f"🎉 1 Complete Video Successfully Saved: {final_out} ({final_size_mb:.2f} MB, {total_render_time:.1f}s)",
                    "SUCCESS"
                )
                self.rendering_completed.emit(True, final_out)
            else:
                self.log_message.emit(f"Final video assembly failed: {merge_msg}", "ERROR")
                self.rendering_completed.emit(False, merge_msg)

        finally:
            self._cleanup_temp_dir()

    def _cleanup_temp_dir(self):
        if self._temp_dir and os.path.isdir(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass
            self._temp_dir = None
