"""
parser.py - Flexible and robust timestamp script parser for TimeSync-Upscaler.

Supports:
  1. SRT subtitle files (.srt)
  2. Range timestamps: [00:00 - 00:04], 00:01:20 --> 00:01:25, 00:04-00:09
  3. Sequential timestamps:
       [00:00] In July two thousand nineteen...
       001,[00:04] walked into an Asian grocery store
       123,[00:06] looking for something that did not belong on Earth.
  4. CSV / TSV formats: prompt_id,timestamp,text
  5. Multi-format prompt numbering: '001', 'Prompt 1', '#12', '[02]', 'Scene 3'
"""

from __future__ import annotations
import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class TimestampEntry:
    index: int
    prompt_id: str
    prompt_num: Optional[int]
    start_seconds: float
    end_seconds: float
    duration: float
    text: str = ""
    matched_file: Optional[str] = None
    status: str = "PENDING"  # MATCHED, MISSING, PENDING, WARNING
    notes: str = ""

    def to_dict(self):
        return {
            "index": self.index,
            "prompt_id": self.prompt_id,
            "prompt_num": self.prompt_num,
            "start_time": format_seconds(self.start_seconds),
            "end_time": format_seconds(self.end_seconds),
            "duration": f"{self.duration:.2f}s",
            "matched_file": self.matched_file or "None",
            "status": self.status,
            "text": self.text,
            "notes": self.notes,
        }


def format_seconds(sec: float) -> str:
    """Format seconds into HH:MM:SS.mmm or MM:SS.mmm."""
    if sec < 0:
        sec = 0.0
    hours = int(sec // 3600)
    minutes = int((sec % 3600) // 60)
    seconds = sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
    return f"{minutes:02d}:{seconds:06.3f}"


def parse_timestamp_str(t_str: str) -> Optional[float]:
    """
    Parses various timestamp strings into floating-point seconds:
      - 01:23:45.678 or 01:23:45,678 (HH:MM:SS.mmm)
      - 04:15.500 or 04:15 (MM:SS[.mmm])
      - 12.5s or 12.5 (SS[.mmm])
    """
    if not t_str:
        return None
    t_str = t_str.strip().replace(",", ".").rstrip("sS")
    parts = t_str.split(":")
    try:
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60 + s
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        return None
    return None


def extract_prompt_number(raw_str: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Extracts prompt reference numbers from tokens like:
      '001', '1', 'Prompt 1', 'Prompt_02', '#3', '[04]', 'Scene 5', '001,'
    """
    # 1. Matches "prompt 1", "prompt_01", "scene 1", "image 1", "#12"
    m = re.search(r'(?i)\b(?:prompt|scene|img|image|asset|pic|shot)[_\s#-]*(\d+)\b', raw_str)
    if m:
        num_str = m.group(1)
        return num_str, int(num_str)

    # 2. Matches "#123" or "#1"
    m = re.search(r'#(\d+)\b', raw_str)
    if m:
        num_str = m.group(1)
        return num_str, int(num_str)

    # 3. Matches bracketed or comma-separated leading digits: e.g. "001," or "[01]"
    m = re.search(r'^(?:\[|\()?(\d+)(?:\]|\)|\b|,)', raw_str.strip())
    if m:
        num_str = m.group(1)
        return num_str, int(num_str)

    # 4. Any standalone digit token
    tokens = re.findall(r'\b\d+\b', raw_str)
    if tokens:
        first = tokens[0]
        # Ignore numbers that look like years (e.g. 2019, 2024) if they appear in text context
        if len(first) <= 4 and int(first) < 2000:
            return first, int(first)

    return None, None


class ScriptParser:
    """Flexible parser for timestamp scripts in various text, SRT, and CSV formats."""

    @classmethod
    def parse_file(cls, file_path: str | Path, default_last_duration: float = 4.0, total_audio_duration: Optional[float] = None) -> List[TimestampEntry]:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        return cls.parse_text(text, default_last_duration=default_last_duration, total_audio_duration=total_audio_duration)

    @classmethod
    def parse_text(cls, raw_text: str, default_last_duration: float = 4.0, total_audio_duration: Optional[float] = None) -> List[TimestampEntry]:
        text = raw_text.strip()
        if not text:
            return []

        # Check for SRT format
        if "-->" in text:
            entries = cls._parse_srt(text)
            if entries:
                return cls._finalize_entries(entries, default_last_duration, total_audio_duration)

        # Check for CSV format
        if "," in text and "\n" in text:
            csv_entries = cls._try_parse_csv(text)
            if csv_entries:
                return cls._finalize_entries(csv_entries, default_last_duration, total_audio_duration)

        # General Line-by-Line Regex Parser
        entries = cls._parse_lines(text)
        return cls._finalize_entries(entries, default_last_duration, total_audio_duration)

    @classmethod
    def _parse_srt(cls, srt_text: str) -> List[TimestampEntry]:
        """Parses SubRip (.srt) subtitles."""
        entries: List[TimestampEntry] = []
        blocks = re.split(r'\n\s*\n', srt_text.strip())
        index = 1

        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            time_line = ""
            text_lines = []
            for line in lines:
                if "-->" in line:
                    time_line = line
                elif not time_line and line.isdigit():
                    continue  # SRT subtitle counter
                else:
                    text_lines.append(line)

            if not time_line:
                continue

            parts = time_line.split("-->")
            if len(parts) != 2:
                continue

            start_sec = parse_timestamp_str(parts[0].strip())
            end_sec = parse_timestamp_str(parts[1].strip())
            if start_sec is None or end_sec is None:
                continue

            combined_text = " ".join(text_lines)
            prompt_id_str, prompt_num = extract_prompt_number(combined_text)
            if prompt_id_str is None:
                prompt_id_str = f"{index:03d}"
                prompt_num = index

            entries.append(TimestampEntry(
                index=index,
                prompt_id=prompt_id_str,
                prompt_num=prompt_num,
                start_seconds=start_sec,
                end_seconds=end_sec,
                duration=max(0.01, end_sec - start_sec),
                text=combined_text
            ))
            index += 1

        return entries

    @classmethod
    def _try_parse_csv(cls, text: str) -> Optional[List[TimestampEntry]]:
        """Tries parsing structured CSV lines."""
        try:
            reader = csv.reader(io.StringIO(text))
            rows = [r for r in reader if r and any(cell.strip() for cell in r)]
            if len(rows) < 2:
                return None

            header = [c.strip().lower() for c in rows[0]]
            has_time_col = any("time" in c or "start" in c for c in header)
            if not has_time_col:
                return None

            start_idx = -1
            end_idx = -1
            id_idx = -1
            text_idx = -1

            for i, col in enumerate(header):
                if "start" in col or (col == "time" and start_idx == -1):
                    start_idx = i
                elif "end" in col:
                    end_idx = i
                elif "prompt" in col or "id" in col or "image" in col or "num" in col:
                    id_idx = i
                elif "text" in col or "desc" in col or "script" in col:
                    text_idx = i

            if start_idx == -1:
                return None

            entries: List[TimestampEntry] = []
            idx = 1
            for row in rows[1:]:
                if len(row) <= start_idx:
                    continue
                start_sec = parse_timestamp_str(row[start_idx])
                if start_sec is None:
                    continue

                end_sec = parse_timestamp_str(row[end_idx]) if (end_idx != -1 and len(row) > end_idx) else None
                prompt_raw = row[id_idx] if (id_idx != -1 and len(row) > id_idx) else ""
                row_text = row[text_idx] if (text_idx != -1 and len(row) > text_idx) else ""

                p_str, p_num = extract_prompt_number(prompt_raw)
                if p_str is None and row_text:
                    p_str, p_num = extract_prompt_number(row_text)
                if p_str is None:
                    p_str = f"{idx:03d}"
                    p_num = idx

                entries.append(TimestampEntry(
                    index=idx,
                    prompt_id=p_str,
                    prompt_num=p_num,
                    start_seconds=start_sec,
                    end_seconds=end_sec if end_sec is not None else 0.0,
                    duration=(end_sec - start_sec) if end_sec is not None else 0.0,
                    text=row_text
                ))
                idx += 1

            return entries if entries else None
        except Exception:
            return None

    @classmethod
    def _parse_lines(cls, text: str) -> List[TimestampEntry]:
        """
        Parses freeform script lines with range or sequential timestamps.
        Matches lines like:
          - 001,[00:04] walked into an Asian grocery store
          - [00:00 - 00:04] In July two thousand nineteen
          - Prompt 1: 00:00 - 00:05 | An astronaut on Mars
          - #2 [00:05-00:10] scene description
          - [00:00] First scene description
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        raw_items: List[dict] = []
        index = 1

        # Regex for range timestamps: [00:00 - 00:04], 00:00:00 --> 00:00:04, 00:00-00:05
        range_regex = re.compile(
            r'(?:\[|\()?\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\s*(?:[-–—]|-->|to)\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\s*(?:\]|\))?'
        )

        # Regex for single sequential timestamp: [00:04] or (00:04) or at 00:04
        single_regex = re.compile(
            r'(?:\[|\()\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\s*(?:\]|\))'
        )

        for line in lines:
            range_match = range_regex.search(line)
            if range_match:
                start_sec = parse_timestamp_str(range_match.group(1))
                end_sec = parse_timestamp_str(range_match.group(2))
                if start_sec is not None and end_sec is not None:
                    # Remove matched timestamp string to isolate prompt text
                    clean_line = line[:range_match.start()] + " " + line[range_match.end():]
                    p_str, p_num = extract_prompt_number(clean_line)
                    if p_str is None:
                        p_str = f"{index:03d}"
                        p_num = index

                    raw_items.append({
                        "index": index,
                        "prompt_id": p_str,
                        "prompt_num": p_num,
                        "start_seconds": start_sec,
                        "end_seconds": end_sec,
                        "duration": max(0.01, end_sec - start_sec),
                        "text": clean_line.strip(" ,-|:#[]()"),
                        "is_range": True
                    })
                    index += 1
                    continue

            single_match = single_regex.search(line)
            if single_match:
                start_sec = parse_timestamp_str(single_match.group(1))
                if start_sec is not None:
                    prefix_part = line[:single_match.start()]
                    suffix_part = line[single_match.end():]
                    p_str, p_num = extract_prompt_number(prefix_part)
                    if p_str is None and suffix_part:
                        p_str, p_num = extract_prompt_number(suffix_part)
                    if p_str is None:
                        p_str = f"{index:03d}"
                        p_num = index

                    desc = (prefix_part + " " + suffix_part).strip(" ,-|:#[]()")
                    raw_items.append({
                        "index": index,
                        "prompt_id": p_str,
                        "prompt_num": p_num,
                        "start_seconds": start_sec,
                        "end_seconds": 0.0,
                        "duration": 0.0,
                        "text": desc,
                        "is_range": False
                    })
                    index += 1
                    continue

        return [
            TimestampEntry(
                index=item["index"],
                prompt_id=item["prompt_id"],
                prompt_num=item["prompt_num"],
                start_seconds=item["start_seconds"],
                end_seconds=item["end_seconds"],
                duration=item["duration"],
                text=item["text"]
            )
            for item in raw_items
        ]

    @classmethod
    def _finalize_entries(
        cls,
        entries: List[TimestampEntry],
        default_last_duration: float = 4.0,
        total_audio_duration: Optional[float] = None
    ) -> List[TimestampEntry]:
        """
        Sorts entries by start_time, resolves consecutive sequential durations,
        and ensures end-to-end alignment without gaps.
        """
        if not entries:
            return []

        entries.sort(key=lambda e: e.start_seconds)

        for i in range(len(entries)):
            current = entries[i]
            # If duration is 0 or end_seconds <= start_seconds, derive from next entry
            if current.end_seconds <= current.start_seconds or current.duration <= 0:
                if i + 1 < len(entries):
                    next_start = entries[i + 1].start_seconds
                    if next_start > current.start_seconds:
                        current.end_seconds = next_start
                    else:
                        current.end_seconds = current.start_seconds + default_last_duration
                else:
                    # Last entry
                    if total_audio_duration is not None and total_audio_duration > current.start_seconds:
                        current.end_seconds = total_audio_duration
                    else:
                        current.end_seconds = current.start_seconds + default_last_duration
                current.duration = max(0.01, current.end_seconds - current.start_seconds)

            # Re-index
            current.index = i + 1

        # If audio duration is provided, optionally align the final segment or warn
        if total_audio_duration is not None and entries:
            last = entries[-1]
            if last.end_seconds < total_audio_duration:
                # Extend the last segment to match audio duration perfectly
                last.end_seconds = total_audio_duration
                last.duration = max(0.01, last.end_seconds - last.start_seconds)
                last.notes = "Extended to match audio duration"

        return entries
