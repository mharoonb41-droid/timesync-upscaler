"""
matcher.py - Smart matcher linking timestamp script prompt entries with media files.

Matches prompt IDs (e.g., '1', '01', '001', '123') with filenames such as:
  - 01.png, 1.jpg, 001.webp
  - prompt_01.png, Prompt-1.jpeg, scene_001.webp
  - 123_exterior.png, shot_123.mp4, animated_01.gif
Provides status flags: MATCHED, MISSING, WARNING, DUPLICATE.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from parser import TimestampEntry

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".gif"}
ALL_SUPPORTED_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS


@dataclass
class MediaFileInfo:
    path: str
    filename: str
    stem: str
    extension: str
    is_video: bool
    is_image: bool
    numbers: List[int]
    str_numbers: List[str]


def scan_media_files(directory_or_files: str | Path | List[str | Path]) -> List[MediaFileInfo]:
    """Scans a directory or processes a list of file paths to collect supported media files."""
    file_paths: List[Path] = []

    if isinstance(directory_or_files, (str, Path)):
        p = Path(directory_or_files)
        if p.is_dir():
            for item in sorted(p.iterdir()):
                if item.is_file() and item.suffix.lower() in ALL_SUPPORTED_EXTENSIONS:
                    file_paths.append(item)
        elif p.is_file() and p.suffix.lower() in ALL_SUPPORTED_EXTENSIONS:
            file_paths.append(p)
    elif isinstance(directory_or_files, list):
        for item in directory_or_files:
            p = Path(item)
            if p.is_dir():
                for sub in sorted(p.iterdir()):
                    if sub.is_file() and sub.suffix.lower() in ALL_SUPPORTED_EXTENSIONS:
                        file_paths.append(sub)
            elif p.is_file() and p.suffix.lower() in ALL_SUPPORTED_EXTENSIONS:
                file_paths.append(p)

    results: List[MediaFileInfo] = []
    for fp in file_paths:
        ext = fp.suffix.lower()
        stem = fp.stem
        # Extract all numeric sequences in stem
        # e.g., 'prompt_001_v2' -> ['001', '2']
        num_matches = re.findall(r'\d+', stem)
        int_numbers = [int(n) for n in num_matches]

        results.append(MediaFileInfo(
            path=str(fp.resolve()),
            filename=fp.name,
            stem=stem,
            extension=ext,
            is_video=ext in SUPPORTED_VIDEO_EXTENSIONS,
            is_image=ext in SUPPORTED_IMAGE_EXTENSIONS,
            numbers=int_numbers,
            str_numbers=num_matches
        ))

    return results


class SmartMatcher:
    """Matches timestamp entries to media files using multiple heuristic passes."""

    @classmethod
    def match(
        cls,
        entries: List[TimestampEntry],
        media_pool: List[MediaFileInfo],
        enable_sequential_fallback: bool = True
    ) -> List[TimestampEntry]:
        if not entries:
            return []

        matched_files_used: Set[str] = set()

        # Pass 1: Exact stem match or single exact number match
        for entry in entries:
            target_num = entry.prompt_num
            target_str = str(entry.prompt_id).strip()

            best_file: Optional[MediaFileInfo] = None

            # Priority 1A: Exact stem match (e.g. '001.png' matches prompt '001')
            for mf in media_pool:
                if mf.path in matched_files_used:
                    continue
                if mf.stem.lower() == target_str.lower():
                    best_file = mf
                    break

            # Priority 1B: Prefix/suffix standard naming: 'prompt_01', 'scene_1', '01_scene'
            if not best_file and target_num is not None:
                for mf in media_pool:
                    if mf.path in matched_files_used:
                        continue
                    # Check if the number appears isolated by delimiters
                    # E.g. ^01$, ^01_, _01_, _01$, -01-, -01$
                    pattern = rf'(?:^|[_\s#\-\.\[])0*{target_num}(?:[_\s#\-\.\]]|$)'
                    if re.search(pattern, mf.stem, re.IGNORECASE):
                        best_file = mf
                        break

            # Priority 1C: Any matching number token in filename
            if not best_file and target_num is not None:
                for mf in media_pool:
                    if mf.path in matched_files_used:
                        continue
                    if target_num in mf.numbers:
                        best_file = mf
                        break

            if best_file:
                entry.matched_file = best_file.path
                entry.status = "MATCHED"
                entry.notes = f"Matched '{best_file.filename}'"
                matched_files_used.add(best_file.path)

        # Pass 2: Sequential fallback for remaining unmatched entries (optional)
        if enable_sequential_fallback:
            unused_files = [mf for mf in media_pool if mf.path not in matched_files_used]
            unused_idx = 0
            for entry in entries:
                if entry.matched_file is None and unused_idx < len(unused_files):
                    fallback_file = unused_files[unused_idx]
                    entry.matched_file = fallback_file.path
                    entry.status = "MATCHED"
                    entry.notes = f"Sequential fallback: '{fallback_file.filename}'"
                    matched_files_used.add(fallback_file.path)
                    unused_idx += 1

        # Pass 3: Final check and mark missing
        for entry in entries:
            if not entry.matched_file:
                entry.status = "MISSING"
                entry.notes = f"No media file found for prompt {entry.prompt_id}"
            elif not os.path.isfile(entry.matched_file):
                entry.status = "MISSING"
                entry.notes = f"Matched file missing on disk: {entry.matched_file}"

        return entries
