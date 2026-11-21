# TimeSync-Upscaler Studio

A high-performance, multiprocessing-based PC Desktop Application for automated **Image-to-Video Timestamp Synchronization** and **2K/4K Upscaled Video Export**.

Built with **PySide6** (Qt for Python), **FFmpeg Lanczos upscaling engine**, and Python's `multiprocessing` pipeline to bypass the Python GIL and utilize all available CPU cores and GPU encoders (`NVENC`, `QuickSync`, `AMF`, `libx264`).

---

## Key Features

- **Single Complete Video Output (Zero Chunk Clutter):**
  - All intermediate MPEG-TS processing segments are rendered in private OS temporary storage and automatically cleaned up.
  - Combines all scenes into **exactly ONE final `.mp4` video** with voiceover audio embedded.
- **AMD & Intel Processor & Hardware Acceleration:**
  - **Automatic Processor Detection:** Detects host CPU vendor (AMD vs. Intel), model name, architecture (x64/ARM64), and logical thread count directly on launch.
  - **AMD AMF (Advanced Media Framework):** First-class support for AMD Radeon GPUs and Ryzen APUs with `h264_amf`, `hevc_amf`, and `av1_amf` hardware encoding using dedicated low-latency CQP tuning.
  - **Intel QuickSync Video (QSV):** Hardware-accelerated `h264_qsv`, `hevc_qsv`, and `av1_qsv` encoding for Intel Core & Arc platforms.
  - **NVIDIA NVENC:** High-performance `h264_nvenc` and `hevc_nvenc` encoding.
  - **Multi-Core CPU Software (`libx264` / `libx265`):** Uses AVX2/AVX-512 multi-threading (`-threads 0`) optimized across all available cores for both AMD Ryzen and Intel processors with seamless automatic fallback.
- **Scroll-Safe UI & Fluid Responsiveness:**
  - Sidebar wrapped in a smooth `QScrollArea` to ensure components **never overlap** on any screen resolution or Windows display scaling factor (125%, 150%, 175%).
  - **Scroll-Safe Dropdowns (`NoScrollComboBox` / `NoScrollSlider` / `NoScrollSpinBox`):** Scrolling through the panel with the mouse wheel **never accidentally changes** your selected resolution, frame rate, encoder, or quality settings!
  - **"↺ Restore Default Settings" button:** Instantly resets all export settings to recommended production defaults based on detected CPU/GPU hardware.
- **Multiprocessing Pipeline (GIL-Bypassed):**
  - **Stage 1 (Parallel Scene Processing):** Distributes individual image and video segments across CPU worker processes (`ProcessPoolExecutor`) to scale, frame-accurately pad/trim, apply Ken Burns motion, and encode segments concurrently.
  - **Stage 2 (Fast Merge):** Concatenates all rendered segments instantly via FFmpeg's `concat` demuxer (stream copy without re-encoding) and muxes voiceover audio.
- **Voiceover Audio Synchronization & Smart Duration Matching:**
  - Attaches `.mp3`, `.wav`, `.m4a` audio tracks.
  - If audio is shorter than video: automatically padded with silence so the video never gets cut short.
  - If audio is longer than video: trimmed to exact video length with zero freeze frames.
- **Smart Timestamp & Prompt Parser:**
  - Robust regex parser supporting sequential timestamps (`[00:00]`, `[00:04]`, `[00:06]`), range timestamps (`[00:00 - 00:04]`), SRT subtitle files, and CSV scripts.
  - Recognizes prompt reference identifiers: `01`, `1`, `001`, `[01]`, `Prompt 1`, `#1`, `Scene 3`, `123,`.
- **Smart Heuristic Matcher:**
  - Automatically matches parsed prompt entries with image files (`.png`, `.jpg`, `.jpeg`, `.webp`) and animated clips/GIFs (`.gif`, `.mp4`, `.mov`).
  - Interactive validation table with inline search filtering and manual **Browse / Replace** buttons.
- **2K / 4K Lanczos Upscaling & Motion:**
  - Presets: 1080p FHD, **2K QHD (2560x1440)**, **4K UHD (3840x2160)**, Vertical 1080p (9:16), Vertical 4K, and Ultrawide.
  - Optional smooth **Ken Burns subtle zoom/pan** for static images.
- **Hardware Acceleration:**
  - Probes and utilizes NVIDIA NVENC (`h264_nvenc`, `hevc_nvenc`), Intel QuickSync (`h264_qsv`), AMD AMF (`h264_amf`), with automatic graceful fallback to CPU `libx264`.

---

## Project Structure

```
timesync-upscaler/
├── main.py                  # Desktop GUI bootstrap & headless CLI runner
├── parser.py                # Timestamp & prompt script parser (SRT/TXT/CSV)
├── matcher.py               # Media asset matcher and heuristic scanner
├── processor.py             # Multiprocessing pipeline & background QThread
├── exporter.py              # FFmpeg Lanczos upscaling, encoder probe, & fast concat
├── requirements.txt         # Python package dependencies
├── test_pipeline.py         # End-to-end automated pipeline test
├── README.md                # Documentation and setup instructions
├── ui/
│   ├── __init__.py
│   ├── main_window.py       # PySide6 main window with scrollable sidebar and scroll-safe widgets
│   ├── preview_table.py     # Interactive validation preview table with badges
│   ├── log_console.py       # Real-time color-coded console with auto-scroll
│   └── styles.py            # Modern dark-mode QSS stylesheet
└── sample_data/             # Test scripts, sample audio, and test images
    ├── sample_script.txt
    ├── sample_subtitles.srt
    ├── sample_prompts.csv
    └── test_audio.mp3
```

---

## Installation & Setup

### 1. Prerequisites
- **Python 3.10+** (Tested with Python 3.10 through 3.14)
- **FFmpeg 5.0+** (Ensure `ffmpeg` and `ffprobe` are installed and available on your system `PATH`)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## How to Run

### Launch Desktop GUI:
```bash
python main.py
```

### Quick Workflow:
1. In the header bar, click **"📁 Load Sample Demo"** to test with the bundled sample script and assets.
2. Or drag-and-drop your own **images folder**, **timestamp script** (`.txt`, `.srt`, `.csv`), and optional **audio track**.
3. Review matches in the validation table.
4. Click **"🎬 Export 1 Final Combined Video"**.
5. Once complete, click **"▶ Play Final Video"** to watch the video immediately.

### Run Headless CLI (Automated Batch Mode):
```bash
python main.py --cli \
  --script sample_data/sample_script.txt \
  --media sample_data/ \
  --audio sample_data/test_audio.mp3 \
  --output my_synchronized_video.mp4 \
  --res 2k \
  --fps 30 \
  --workers 4
```

### Run Verification Test Suite:
```bash
python test_pipeline.py
```
