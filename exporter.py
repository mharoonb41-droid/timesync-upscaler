"""
exporter.py - FFmpeg media processing, CPU & GPU hardware detection (AMD Ryzen / Intel / NVIDIA),
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
from typing import Any, Dict, List, Optional, Tuple


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


@dataclass
class CPUHardwareInfo:
    cpu_name: str
    vendor: str          # "AMD", "Intel", or "Generic"
    threads: int
    is_amd: bool
    is_intel: bool


@dataclass
class EncoderOption:
    key: str
    label: str
    category: str        # "AMD", "Intel", "NVIDIA", "CPU"
    is_hardware: bool
    is_verified: bool
    is_recommended: bool = False


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
    """Manages FFmpeg interactions, AMD/Intel/NVIDIA hardware detection, chunk rendering, and merge."""

    _cached_encoders: Optional[List[str]] = None
    _cached_encoder_options: Optional[List[EncoderOption]] = None
    _cached_cpu_info: Optional[CPUHardwareInfo] = None

    @classmethod
    def get_ffmpeg_path(cls) -> str:
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

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg

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
    def get_cpu_hardware_info(cls) -> CPUHardwareInfo:
        """Detects system processor name, vendor (AMD vs Intel), and thread count."""
        if cls._cached_cpu_info is not None:
            return cls._cached_cpu_info

        cpu_name = "Multi-Core Processor"
        vendor = "Generic"

        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                cpu_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
                v_id = winreg.QueryValueEx(key, "VendorIdentifier")[0].strip()
                if "AMD" in v_id.upper() or "AMD" in cpu_name.upper():
                    vendor = "AMD"
                elif "INTEL" in v_id.upper() or "INTEL" in cpu_name.upper():
                    vendor = "Intel"
            except Exception:
                pass

        if vendor == "Generic":
            ident = os.environ.get("PROCESSOR_IDENTIFIER", "") + " " + sys.platform
            if "AMD" in ident.upper():
                vendor = "AMD"
            elif "INTEL" in ident.upper():
                vendor = "Intel"

        threads = os.cpu_count() or 4
        info = CPUHardwareInfo(
            cpu_name=cpu_name,
            vendor=vendor,
            threads=threads,
            is_amd=(vendor == "AMD"),
            is_intel=(vendor == "Intel")
        )
        cls._cached_cpu_info = info
        return info

    @classmethod
    def get_encoder_options(cls) -> List[EncoderOption]:
        """
        Returns full list of available encoders organized by hardware vendor:
        AMD AMF (Radeon / Ryzen APU), Intel QuickSync (Core / Arc), NVIDIA NVENC, and CPU Multi-Core.
        """
        if cls._cached_encoder_options is not None:
            return cls._cached_encoder_options

        ffmpeg = cls.get_ffmpeg_path()
        cpu_info = cls.get_cpu_hardware_info()

        # Query all encoders compiled into FFmpeg
        compiled_encoders = set()
        try:
            cmd = [ffmpeg, "-hide_banner", "-encoders"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            output = res.stdout + res.stderr
            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0].startswith("V"):
                    compiled_encoders.add(parts[1])
        except Exception:
            pass

        # Candidates definition: (key, base_label, category, is_hardware)
        candidates = [
            # AMD Hardware Acceleration (AMD AMF for Ryzen APUs and Radeon GPUs)
            ("h264_amf", "AMD AMF (H.264 / AVC - AMD Radeon/Ryzen)", "AMD", True),
            ("hevc_amf", "AMD AMF (HEVC / H.265 - AMD Radeon/Ryzen)", "AMD", True),
            ("av1_amf", "AMD AMF (AV1 Next-Gen - AMD Radeon/Ryzen)", "AMD", True),

            # Intel Hardware Acceleration (Intel QuickSync for Core CPUs and Arc GPUs)
            ("h264_qsv", "Intel QuickSync (H.264 / AVC - Intel Core/Arc)", "Intel", True),
            ("hevc_qsv", "Intel QuickSync (HEVC / H.265 - Intel Core/Arc)", "Intel", True),
            ("av1_qsv", "Intel QuickSync (AV1 Next-Gen - Intel Core/Arc)", "Intel", True),

            # NVIDIA Hardware Acceleration (NVENC for GeForce / RTX GPUs)
            ("h264_nvenc", "NVIDIA NVENC (H.264 / AVC - GeForce/RTX)", "NVIDIA", True),
            ("hevc_nvenc", "NVIDIA NVENC (HEVC / H.265 - GeForce/RTX)", "NVIDIA", True),
            ("av1_nvenc", "NVIDIA NVENC (AV1 Next-Gen - GeForce/RTX)", "NVIDIA", True),

            # Universal Multi-Core CPU Software Encoding
            ("libx264", f"CPU Software (AMD Ryzen & Intel Optimized - libx264)", "CPU", False),
            ("libx265", f"CPU Software (High Efficiency Multi-Core - libx265)", "CPU", False),
        ]

        options: List[EncoderOption] = []
        has_recommended = False

        for key, label, category, is_hw in candidates:
            # Check if encoder is compiled in FFmpeg
            if key in compiled_encoders or not is_hw:
                is_active = cls._test_encoder(ffmpeg, key) if is_hw else True
                
                # Check recommendation based on detected processor/GPU
                is_rec = False
                if not has_recommended:
                    if is_active and is_hw:
                        if category == "AMD" and cpu_info.is_amd:
                            is_rec = True
                            has_recommended = True
                        elif category == "Intel" and cpu_info.is_intel:
                            is_rec = True
                            has_recommended = True
                        elif category == "NVIDIA":
                            is_rec = True
                            has_recommended = True

                options.append(EncoderOption(
                    key=key,
                    label=label,
                    category=category,
                    is_hardware=is_hw,
                    is_verified=is_active,
                    is_recommended=is_rec
                ))

        # Default fallback recommendation if no hardware encoder was pre-recommended
        if not has_recommended:
            for opt in options:
                if opt.key == "libx264":
                    opt.is_recommended = True
                    break

        cls._cached_encoder_options = options
        return options

    @classmethod
    def detect_available_encoders(cls) -> List[str]:
        """Returns list of encoder keys for backward compatibility."""
        if cls._cached_encoders is not None:
            return cls._cached_encoders
        options = cls.get_encoder_options()
        keys = [opt.key for opt in options]
        cls._cached_encoders = keys
        return keys

    @classmethod
    def _test_encoder(cls, ffmpeg_bin: str, encoder: str) -> bool:
        """Runs a 1-frame null test with the given encoder to verify active hardware driver support."""
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
        using Lanczos upscaling and selected hardware (AMD AMF / Intel QSV / NVIDIA NVENC) or multi-core CPU.
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
            # AMD Advanced Media Framework (AMF) hardware encoding for AMD Ryzen APUs and Radeon GPUs
            cmd += [
                "-c:v", enc,
                "-rc", "cqp",
                "-qp_i", str(config.crf),
                "-qp_p", str(config.crf),
                "-quality", "quality",
                "-usage", "transcoding",
                "-g", str(config.fps * 2),
            ]
        else:
            # CPU Software: Optimized for multi-threaded AMD Ryzen and Intel multi-core CPUs
            cmd += [
                "-c:v", enc,
                "-crf", str(config.crf),
                "-preset", config.preset or "medium",
                "-threads", "0",
                "-g", str(config.fps * 2),
            ]

        cmd += ["-f", "mpegts", output_ts_path]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                # Graceful fallback to multi-core CPU encoding if selected hardware is not active
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
                        "-threads", "0",
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
        Seamlessly muxes voiceover audio (with automatic padding/trimming to prevent video cut-off).
        """
        if not segment_paths:
            return False, "No segment files provided for concatenation."

        ffmpeg = cls.get_ffmpeg_path()
        temp_dir = Path(tempfile.gettempdir())
        concat_txt = temp_dir / f"timesync_concat_{os.getpid()}_{int(time.time() * 1000)}.txt"

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
