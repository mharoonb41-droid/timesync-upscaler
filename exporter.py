"""
exporter.py - FFmpeg media processing, hardware encoder detection,
upscaling filter synthesis (Lanczos/Ken Burns), and stream-copy concatenation.
"""

from __future__ import annotations
import os
import sys
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ExportConfig:
    width: int = 2560
    height: int = 1440
    fps: int = 30
    encoder: str = "libx264"
    crf: int = 18
    preset: str = "medium"
    scaling_mode: str = "fit"  # "fit", "fill", "stretch"
    enable_ken_burns: bool = False
    video_overflow_mode: str = "trim"  # "trim" or "loop"
    audio_path: Optional[str] = None
    audio_sync_mode: str = "pad_or_trim"  # "pad_or_trim", "loop", "mute"
    num_workers: int = 4
    output_path: str = "output_synchronized.mp4"


RESOLUTION_PRESETS = {
    "1080p FHD (1920x1080) [16:9]": (1920, 1080),
    "2K QHD (2560x1440) [16:9]": (2560, 1440),
    "4K UHD (3840x2160) [16:9]": (3840, 2160),
    "Vertical 1080p (1080x1920) [9:16]": (1080, 1920),
    "Vertical 4K (2160x3840) [9:16]": (2160, 3840),
    "Square 1080p (1080x1080) [1:1]": (1080, 1080),
    "Ultrawide 1440p (3440x1440) [21:9]": (3440, 1440),
}


class FFmpegEngine:
    """Manages FFmpeg interactions, encoder detection, chunk rendering, and merge."""

    _cached_encoders: Optional[List[str]] = None

    @classmethod
    def get_ffmpeg_path(cls) -> str:
        # 1. Check PyInstaller bundle directory or application directory
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "ffmpeg.exe"))
            candidates.append(os.path.join(sys._MEIPASS, "bin", "ffmpeg.exe"))
        
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "ffmpeg.exe"))
        candidates.append(os.path.join(exe_dir, "bin", "ffmpeg.exe"))

        file_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(file_dir, "ffmpeg.exe"))
        candidates.append(os.path.join(file_dir, "bin", "ffmpeg.exe"))

        for c in candidates:
            if os.path.isfile(c):
                return c

        # 2. Check system PATH
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg

        # 3. Check common Windows install paths
        common_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        ]
        for cp in common_paths:
            if os.path.isfile(cp):
                return cp
        raise RuntimeError("FFmpeg not found. Please install FFmpeg or place ffmpeg.exe in the application folder.")

    @classmethod
    def get_ffprobe_path(cls) -> str:
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "ffprobe.exe"))
            candidates.append(os.path.join(sys._MEIPASS, "bin", "ffprobe.exe"))

        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "ffprobe.exe"))
        candidates.append(os.path.join(exe_dir, "bin", "ffprobe.exe"))

        file_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(file_dir, "ffprobe.exe"))
        candidates.append(os.path.join(file_dir, "bin", "ffprobe.exe"))

        for c in candidates:
            if os.path.isfile(c):
                return c

        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            return ffprobe

        common_paths = [
            r"C:\ffmpeg\bin\ffprobe.exe",
            r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
            r"C:\tools\ffmpeg\bin\ffprobe.exe",
        ]
        for cp in common_paths:
            if os.path.isfile(cp):
                return cp
        return "ffprobe"

    @classmethod
    def detect_available_encoders(cls) -> List[str]:
        """Probes FFmpeg for available H.264 and HEVC hardware and software encoders."""
        if cls._cached_encoders is not None:
            return cls._cached_encoders

        ffmpeg = cls.get_ffmpeg_path()
        candidates = [
            ("NVIDIA NVENC (H.264)", "h264_nvenc"),
            ("NVIDIA NVENC (HEVC/H.265)", "hevc_nvenc"),
            ("Intel QuickSync (H.264)", "h264_qsv"),
            ("Intel QuickSync (HEVC)", "hevc_qsv"),
            ("AMD AMF (H.264)", "h264_amf"),
            ("AMD AMF (HEVC)", "hevc_amf"),
            ("Apple VideoToolbox (H.264)", "h264_videotoolbox"),
            ("CPU Software (libx264 - Default)", "libx264"),
            ("CPU Software (libx265)", "libx265"),
        ]

        verified_encoders: List[str] = []

        try:
            cmd = [ffmpeg, "-hide_banner", "-encoders"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            output = res.stdout + res.stderr

            for label, enc in candidates:
                if enc in output:
                    if cls._test_encoder(ffmpeg, enc):
                        verified_encoders.append(enc)
        except Exception:
            pass

        if "libx264" not in verified_encoders:
            verified_encoders.append("libx264")

        cls._cached_encoders = verified_encoders
        return verified_encoders

    @classmethod
    def _test_encoder(cls, ffmpeg_bin: str, encoder: str) -> bool:
        """Runs a 1-frame null test with the given encoder to verify hardware support."""
        if encoder in ("libx264", "libx265"):
            return True
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.04",
            "-c:v", encoder,
            "-f", "null", "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def get_media_duration(cls, media_path: str) -> Optional[float]:
        """Uses ffprobe to obtain media duration in seconds."""
        ffprobe = cls.get_ffprobe_path()
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration:stream=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            media_path
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
            lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            for line in lines:
                try:
                    val = float(line)
                    if val > 0:
                        return val
                except ValueError:
                    continue
        except Exception:
            pass
        return None

    @classmethod
    def build_video_filter(
        cls,
        width: int,
        height: int,
        fps: int,
        duration: float,
        scaling_mode: str,
        is_static_image: bool,
        enable_ken_burns: bool
    ) -> str:
        filters: List[str] = []
        total_frames = max(1, int(round(duration * fps)))

        if is_static_image and enable_ken_burns:
            kb_filter = (
                f"zoompan=z='min(zoom+0.0005,1.12)':d={total_frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
            )
            filters.append(kb_filter)
        else:
            if scaling_mode == "fit":
                filters.append(
                    f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd"
                )
                filters.append(
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
                )
            elif scaling_mode == "fill":
                filters.append(
                    f"scale=w={width}:h={height}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd"
                )
                filters.append(
                    f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2"
                )
            else:  # stretch
                filters.append(f"scale=w={width}:h={height}:flags=lanczos+accurate_rnd")

        filters.append(f"fps={fps}")
        filters.append("format=yuv420p")

        return ",".join(filters)

    @classmethod
    def render_segment(
        cls,
        media_path: str,
        output_ts_path: str,
        duration: float,
        config: ExportConfig,
        is_video: bool = False
    ) -> bool:
        """
        Renders an internal frame-accurate segment chunk into temporary MPEG-TS (.ts)
        using Lanczos upscaling and selected hardware/CPU encoder.
        """
        ffmpeg = cls.get_ffmpeg_path()
        filter_str = cls.build_video_filter(
            width=config.width,
            height=config.height,
            fps=config.fps,
            duration=duration,
            scaling_mode=config.scaling_mode,
            is_static_image=not is_video,
            enable_ken_burns=config.enable_ken_burns and not is_video
        )

        cmd: List[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]

        if not is_video:
            cmd += [
                "-loop", "1",
                "-framerate", str(config.fps),
                "-t", f"{duration:.3f}",
                "-i", media_path,
            ]
        else:
            input_dur = cls.get_media_duration(media_path)
            if input_dur is not None and input_dur < duration:
                cmd += [
                    "-stream_loop", "-1",
                    "-i", media_path,
                    "-t", f"{duration:.3f}",
                ]
            else:
                cmd += [
                    "-i", media_path,
                    "-t", f"{duration:.3f}",
                ]

        cmd += ["-vf", filter_str]

        enc = config.encoder
        if "nvenc" in enc:
            cmd += [
                "-c:v", enc,
                "-cq", str(config.crf),
                "-preset", "p4",
                "-tune", "hq",
                "-g", str(config.fps * 2),
            ]
        elif "qsv" in enc:
            cmd += [
                "-c:v", enc,
                "-global_quality", str(config.crf),
                "-preset", "medium",
                "-g", str(config.fps * 2),
            ]
        elif "amf" in enc:
            cmd += [
                "-c:v", enc,
                "-quality", "quality",
                "-rc", "cbr",
                "-g", str(config.fps * 2),
            ]
        else:
            cmd += [
                "-c:v", enc,
                "-crf", str(config.crf),
                "-preset", config.preset or "medium",
                "-g", str(config.fps * 2),
            ]

        cmd += ["-f", "mpegts", output_ts_path]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                if enc != "libx264":
                    cmd_fallback = [
                        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-loop", "1" if not is_video else "-i",
                        media_path,
                        "-t", f"{duration:.3f}",
                        "-vf", filter_str,
                        "-c:v", "libx264",
                        "-crf", str(config.crf),
                        "-preset", "veryfast",
                        "-f", "mpegts", output_ts_path
                    ]
                    res2 = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    return res2.returncode == 0
                return False
            return True
        except Exception:
            return False

    @classmethod
    def concatenate_segments(
        cls,
        segment_paths: List[str],
        output_file: str,
        audio_file: Optional[str] = None,
        total_duration: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Stage 2 (Single Final Output): Combines all internal segments into exactly ONE final video.
        Seamlessly muxes the voiceover audio (with automatic padding/trimming to prevent video cut-off).
        No temporary files are left in the user directory.
        """
        if not segment_paths:
            return False, "No segment files provided for concatenation."

        ffmpeg = cls.get_ffmpeg_path()

        # Place the concat index file inside the OS temp directory
        temp_dir = Path(tempfile.gettempdir())
        concat_txt = temp_dir / f"timesync_concat_{os.getpid()}_{int(time.time() * 1000)}.txt"

        # Ensure target directory exists
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(concat_txt, "w", encoding="utf-8") as f:
                for sp in segment_paths:
                    clean_path = Path(sp).resolve().as_posix()
                    f.write(f"file '{clean_path}'\n")

            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt.resolve())
            ]

            if audio_file and os.path.isfile(audio_file):
                audio_dur = cls.get_media_duration(audio_file)
                if total_duration and total_duration > 0:
                    if audio_dur is not None and audio_dur < total_duration:
                        # Audio is shorter than video: pad with silence so video plays full length
                        cmd += [
                            "-i", str(Path(audio_file).resolve()),
                            "-filter_complex", f"[1:a]apad=whole_dur={total_duration:.3f}[a]",
                            "-map", "0:v:0",
                            "-map", "[a]",
                            "-c:v", "copy",
                            "-c:a", "aac",
                            "-b:a", "192k",
                            "-t", f"{total_duration:.3f}",
                        ]
                    else:
                        # Audio is equal or longer: trim audio exactly to video length
                        cmd += [
                            "-i", str(Path(audio_file).resolve()),
                            "-map", "0:v:0",
                            "-map", "1:a:0?",
                            "-c:v", "copy",
                            "-c:a", "aac",
                            "-b:a", "192k",
                            "-t", f"{total_duration:.3f}",
                        ]
                else:
                    cmd += [
                        "-i", str(Path(audio_file).resolve()),
                        "-map", "0:v:0",
                        "-map", "1:a:0?",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-shortest",
                    ]
            else:
                cmd += [
                    "-c:v", "copy",
                    "-an"
                ]

            cmd += ["-movflags", "+faststart", output_file]

            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.isfile(output_file) and os.path.getsize(output_file) > 0:
                return True, f"Successfully exported single final video: {output_file}"
            else:
                return False, f"FFmpeg concat failed: {res.stderr}"
        except Exception as e:
            return False, f"Concatenation error: {str(e)}"
        finally:
            if concat_txt.exists():
                try:
                    concat_txt.unlink()
                except Exception:
                    pass
