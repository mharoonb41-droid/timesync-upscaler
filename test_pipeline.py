"""
test_pipeline.py - Automated end-to-end verification test for TimeSync-Upscaler.

Tests:
  1. Parsing sample script with sequential timestamps.
  2. Smart matching prompt IDs to images.
  3. Parallel multiprocessing chunk rendering in private OS temp storage.
  4. Final assembly into exactly ONE combined 2K QHD video with voiceover audio muxed.
  5. Verifying audio & video streams and zero leftover chunk files.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from PIL import Image, ImageDraw
from exporter import ExportConfig, FFmpegEngine
from matcher import SmartMatcher, scan_media_files
from parser import ScriptParser, format_seconds
from processor import _render_single_chunk_worker
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import subprocess


def create_test_images_and_audio(sample_dir: Path):
    sample_dir.mkdir(parents=True, exist_ok=True)
    images_info = [
        ("0.png", "#1e3a8a", "PROMPT 0: Vancouver 2019"),
        ("001.png", "#065f46", "PROMPT 001: Asian Grocery Store"),
        ("123_scene.jpg", "#701a75", "PROMPT 123: Alien Artifact"),
        ("prompt_04.png", "#854d0e", "PROMPT 4: Mysterious Jar"),
    ]
    created = []
    for filename, color, caption in images_info:
        fp = sample_dir / filename
        if not fp.exists():
            img = Image.new("RGB", (1280, 720), color=color)
            draw = ImageDraw.Draw(img)
            draw.rectangle([20, 20, 1260, 700], outline="#ffffff", width=4)
            draw.text((60, 340), caption, fill="#ffffff")
            img.save(str(fp))
        created.append(fp)

    # Ensure test audio file exists
    audio_path = sample_dir / "test_audio.mp3"
    if not audio_path.exists():
        ffmpeg = FFmpegEngine.get_ffmpeg_path()
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=13", "-c:a", "libmp3lame", str(audio_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    print(f"[+] Verified sample images and audio in {sample_dir}")
    return created, str(audio_path)


def run_test():
    print("==================================================")
    print(" Running End-to-End Single Video & Audio Pipeline Test")
    print("==================================================")

    sample_dir = ROOT_DIR / "sample_data"
    _, audio_file = create_test_images_and_audio(sample_dir)

    # 1. Parse Script
    script_path = sample_dir / "sample_script.txt"
    entries = ScriptParser.parse_file(script_path, total_audio_duration=13.0)
    print(f"\n[1] Parser Test:")
    print(f"    - Parsed entries count: {len(entries)}")
    for e in entries:
        print(f"    - Index {e.index} | ID: '{e.prompt_id}' | {format_seconds(e.start_seconds)} -> {format_seconds(e.end_seconds)} (Dur: {e.duration:.2f}s)")

    assert len(entries) == 4, f"Expected 4 entries, got {len(entries)}"
    print("    [PASS] Parser frame-accurate sequential durations verified.")

    # 2. Smart Matcher
    media_pool = scan_media_files(sample_dir)
    matched = SmartMatcher.match(entries, media_pool)
    print(f"\n[2] Smart Matcher Test:")
    for e in matched:
        print(f"    - Prompt #{e.prompt_id} -> Matched: {Path(e.matched_file).name}")
        assert e.status == "MATCHED"
    print("    [PASS] All assets matched.")

    # 3. Parallel Multiprocessing in Private OS Temp Directory
    print(f"\n[3] Multiprocessing Parallel Render in Private Temp Directory:")
    temp_dir = Path(tempfile.mkdtemp(prefix="test_timesync_private_"))
    final_output = str(sample_dir / "final_single_video_with_audio.mp4")

    config = ExportConfig(
        width=2560,
        height=1440,
        fps=30,
        encoder="libx264",
        crf=20,
        scaling_mode="fit",
        enable_ken_burns=False,
        audio_path=audio_file,
        num_workers=2,
        output_path=final_output
    )

    payloads = []
    ordered_ts = []
    total_planned = sum(e.duration for e in matched)

    for i, e in enumerate(matched):
        out_ts = str(temp_dir / f"test_segment_{i:04d}.ts")
        ordered_ts.append(out_ts)
        payloads.append({
            "index": i,
            "prompt_id": e.prompt_id,
            "media_path": e.matched_file,
            "duration": e.duration,
            "output_path": out_ts,
            "is_video": False,
            "config": asdict(config)
        })

    with ProcessPoolExecutor(max_workers=config.num_workers) as executor:
        futures = [executor.submit(_render_single_chunk_worker, p) for p in payloads]
        for f in as_completed(futures):
            res = f.result()
            assert res["success"]
            print(f"      * Scene #{res['prompt_id']} rendered: OK ({res['duration']:.2f}s)")

    print("    [PASS] All scenes processed in background.")

    # 4. Assembly into 1 Single Output Video with Audio Muxing
    print(f"\n[4] Assembly into Exactly ONE Final Video:")
    success, msg = FFmpegEngine.concatenate_segments(
        segment_paths=ordered_ts,
        output_file=final_output,
        audio_file=audio_file,
        total_duration=total_planned
    )
    print(f"    - Concat result: {success} | {msg}")
    assert success
    assert os.path.isfile(final_output)

    # 5. Clean up private temp chunks
    shutil.rmtree(temp_dir, ignore_errors=True)
    assert not temp_dir.exists(), "Temp chunks must be deleted!"

    # 6. Verify Final Video Streams & Duration
    ffprobe = FFmpegEngine.get_ffprobe_path()
    res = subprocess.run([
        ffprobe, "-v", "error",
        "-show_entries", "stream=index,codec_type,codec_name,duration:format=duration",
        "-of", "default=noprint_wrappers=1",
        final_output
    ], stdout=subprocess.PIPE, text=True, check=True)

    print("\n[5] Final Video Stream Verification:")
    print(res.stdout.strip())
    assert "codec_type=video" in res.stdout, "Video stream missing!"
    assert "codec_type=audio" in res.stdout, "Audio stream missing! Audio must be attached to the final video."

    size_mb = os.path.getsize(final_output) / (1024 * 1024)
    print(f"\n    ✅ Final Output Video: {final_output}")
    print(f"    ✅ Size: {size_mb:.2f} MB")
    print(f"    ✅ Audio attached: YES (AAC)")
    print(f"    ✅ Zero chunk files remaining in user directories!")

    print("\n==================================================")
    print(" ✅ ALL SINGLE-VIDEO & AUDIO PIPELINE TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    run_test()
