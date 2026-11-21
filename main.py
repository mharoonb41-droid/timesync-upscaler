"""
main.py - Entry point for TimeSync-Upscaler Desktop Application and CLI.

Supports:
  1. Desktop GUI Mode: launches modern dark-themed PySide6 interface.
  2. Headless CLI Mode: allows running automated batch rendering from terminal or scripts.
"""

from __future__ import annotations
import argparse
import multiprocessing
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Fix for high DPI scaling on Windows
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"


def run_cli(args: argparse.Namespace):
    """Headless CLI execution mode: generates 1 combined final video output."""
    from exporter import ExportConfig, FFmpegEngine, RESOLUTION_PRESETS
    from matcher import SmartMatcher, scan_media_files
    from parser import ScriptParser
    from processor import _render_single_chunk_worker
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from dataclasses import asdict

    print("==================================================")
    print(" TimeSync-Upscaler Single-Video CLI Engine")
    print("==================================================")

    # 1. Verify FFmpeg & Hardware
    try:
        ffmpeg_bin = FFmpegEngine.get_ffmpeg_path()
        print(f"[*] FFmpeg binary: {ffmpeg_bin}")
    except RuntimeError as e:
        print(f"[!] Error: {e}")
        sys.exit(1)

    cpu_info = FFmpegEngine.get_cpu_hardware_info()
    print(f"[*] Host CPU: {cpu_info.name} ({cpu_info.arch}) | Logical Cores: {cpu_info.logical_cores} | Vendor: {cpu_info.vendor.upper()}")

    # 2. Parse script
    script_path = Path(args.script)
    if not script_path.is_file():
        print(f"[!] Script file not found: {script_path}")
        sys.exit(1)

    audio_dur = None
    if args.audio and os.path.isfile(args.audio):
        audio_dur = FFmpegEngine.get_media_duration(args.audio)
        print(f"[*] Voiceover audio track: {args.audio} (Duration: {audio_dur:.2f}s)")

    entries = ScriptParser.parse_file(script_path, total_audio_duration=audio_dur)
    print(f"[*] Parsed {len(entries)} timestamp entries from script.")

    # 3. Match media
    media_pool = scan_media_files(args.media)
    print(f"[*] Scanned {len(media_pool)} media assets from: {args.media}")
    matched_entries = SmartMatcher.match(entries, media_pool)

    valid_entries = [e for e in matched_entries if e.status == "MATCHED"]
    print(f"[*] Successfully matched: {len(valid_entries)} / {len(entries)} entries.")

    if not valid_entries:
        print("[!] No matched media entries found to render. Exiting.")
        sys.exit(1)

    # 4. Prepare Config
    width, height = 2560, 1440
    if args.res == "1080p":
        width, height = 1920, 1080
    elif args.res == "4k":
        width, height = 3840, 2160
    elif args.res == "vertical_1080p":
        width, height = 1080, 1920
    elif args.res == "vertical_4k":
        width, height = 2160, 3840

    config = ExportConfig(
        width=width,
        height=height,
        fps=args.fps,
        encoder=args.encoder,
        crf=args.crf,
        scaling_mode=args.scaling,
        enable_ken_burns=args.ken_burns,
        audio_path=args.audio,
        num_workers=args.workers,
        output_path=args.output
    )

    # 5. Multiprocessing Parallel Render in private OS temp folder
    temp_dir = Path(tempfile.mkdtemp(prefix="timesync_cli_temp_"))

    try:
        ordered_ts = []
        payloads = []
        video_exts = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".gif"}
        total_planned_dur = 0.0

        for i, entry in enumerate(valid_entries):
            out_ts = str(temp_dir / f"chunk_{i:04d}_{entry.prompt_id}.ts")
            ordered_ts.append(out_ts)
            total_planned_dur += entry.duration
            is_vid = Path(entry.matched_file).suffix.lower() in video_exts
            payloads.append({
                "index": i,
                "prompt_id": entry.prompt_id,
                "media_path": entry.matched_file,
                "duration": entry.duration,
                "output_path": out_ts,
                "is_video": is_vid,
                "config": asdict(config)
            })

        print(f"[*] Stage 1: Processing {len(payloads)} scenes with {config.num_workers} parallel workers...")
        with ProcessPoolExecutor(max_workers=config.num_workers) as executor:
            futures = [executor.submit(_render_single_chunk_worker, p) for p in payloads]
            for f in as_completed(futures):
                res = f.result()
                status = "OK" if res["success"] else f"FAIL ({res['error']})"
                print(f"    - Scene #{res['prompt_id']} [{res['duration']:.2f}s]: {status}")
                if not res["success"]:
                    print("[!] Render failure. Aborting.")
                    sys.exit(1)

        print("[*] Stage 2: Assembling scenes and muxing audio into 1 final video...")
        success, msg = FFmpegEngine.concatenate_segments(
            segment_paths=ordered_ts,
            output_file=args.output,
            audio_file=args.audio,
            total_duration=total_planned_dur
        )

        if success and os.path.isfile(args.output):
            out_size_mb = os.path.getsize(args.output) / (1024 * 1024)
            print(f"[+] ✅ 1 Final Video Exported Successfully: {args.output} ({out_size_mb:.2f} MB)")
        else:
            print(f"[!] Concat failed: {msg}")
            sys.exit(1)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_gui():
    """Launches the PySide6 modern dark desktop application."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from exporter import FFmpegEngine
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("TimeSync-Upscaler Studio")
    app.setOrganizationName("TimeSync")

    try:
        FFmpegEngine.get_ffmpeg_path()
    except RuntimeError as err:
        QMessageBox.critical(
            None,
            "FFmpeg Required",
            "FFmpeg was not detected in your system PATH.\n\n"
            "Please install FFmpeg and add it to your PATH to use TimeSync-Upscaler.\n"
            "Download from: https://ffmpeg.org/download.html"
        )
        sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def main():
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="TimeSync-Upscaler: Automated Multiprocess Video Studio")
    parser.add_argument("--cli", action="store_true", help="Run in headless CLI mode instead of GUI")
    parser.add_argument("--script", type=str, help="Path to timestamp script (.txt/.srt/.csv)")
    parser.add_argument("--media", type=str, help="Directory containing images/video assets")
    parser.add_argument("--audio", type=str, default=None, help="Optional voiceover audio file (.mp3/.wav)")
    parser.add_argument("--output", type=str, default="final_synchronized_video.mp4", help="Final single output video path")
    parser.add_argument("--res", choices=["1080p", "2k", "4k", "vertical_1080p", "vertical_4k"], default="2k", help="Resolution preset")
    parser.add_argument("--fps", type=int, default=30, help="Video frame rate (24, 30, 60)")
    parser.add_argument(
        "--encoder",
        type=str,
        default="libx264",
        help="Video encoder: libx264, libx265, h264_amf, hevc_amf (AMD), h264_qsv, hevc_qsv (Intel), h264_nvenc, hevc_nvenc (NVIDIA)"
    )
    parser.add_argument("--crf", type=int, default=18, help="CRF / Constant Quality value (16-28)")
    parser.add_argument("--scaling", choices=["fit", "fill", "stretch"], default="fit", help="Aspect scaling mode")
    parser.add_argument("--ken-burns", action="store_true", help="Enable subtle Ken Burns motion effect on images")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1), help="Worker process count")

    args, unknown = parser.parse_known_args()

    if args.cli or (args.script and args.media):
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
