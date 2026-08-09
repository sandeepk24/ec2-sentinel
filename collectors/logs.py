"""
Log pattern scanner: scan log files for error patterns.

Answers the question: "Has anything exploded in the logs since I last checked?"
Handles glob patterns, rotated logs, and large files efficiently.
"""

import glob
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class LogMatch:
    file: str
    pattern: str
    count: int
    last_line: str       # most recent matching line (truncated)
    last_position: int   # byte offset of last match — for resume scanning


@dataclass
class LogReport:
    timestamp: str
    matches: list[LogMatch]
    files_scanned: int
    files_failed: list[str]  # files we couldn't read (permission, missing)
    scan_duration_ms: float

    @property
    def total_hits(self) -> int:
        return sum(m.count for m in self.matches)

    @property
    def has_alerts(self) -> bool:
        return self.total_hits > 0


# Track where we left off per file to avoid re-scanning old content
POSITION_FILE = Path("/tmp/ec2_sentinel_log_positions.json")


def _load_positions() -> dict:
    if POSITION_FILE.exists():
        try:
            import json
            return json.loads(POSITION_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_positions(positions: dict) -> None:
    try:
        import json
        POSITION_FILE.write_text(json.dumps(positions))
    except OSError:
        pass


def _resolve_file_globs(file_patterns: list[str]) -> list[str]:
    """Expand glob patterns like /var/log/tomcat*/catalina.out"""
    resolved = []
    for pattern in file_patterns:
        if "*" in pattern or "?" in pattern:
            resolved.extend(glob.glob(pattern))
        else:
            resolved.append(pattern)
    return list(set(resolved))


def _scan_file(
    filepath: str,
    patterns: list[re.Pattern],
    pattern_strings: list[str],
    start_offset: int = 0,
    max_bytes: int = 50 * 1024 * 1024,  # 50 MB cap per file
) -> tuple[list[LogMatch], int]:
    """
    Scan a single file for matching patterns.
    Returns (matches, new_offset) for resume support.
    """
    matches_by_pattern: dict[str, LogMatch] = {}

    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        return [], start_offset

    # If file is smaller than our last offset, it was rotated — start from 0
    if file_size < start_offset:
        start_offset = 0

    # Cap how much we read
    read_size = min(file_size - start_offset, max_bytes)
    if read_size <= 0:
        return [], file_size

    try:
        with open(filepath, "r", errors="replace") as f:
            f.seek(start_offset)
            content = f.read(read_size)
            new_offset = f.tell()
    except (OSError, PermissionError):
        return [], start_offset

    for line in content.splitlines():
        for i, compiled in enumerate(patterns):
            if compiled.search(line):
                pat_str = pattern_strings[i]
                if pat_str in matches_by_pattern:
                    matches_by_pattern[pat_str].count += 1
                    matches_by_pattern[pat_str].last_line = line[:300]
                else:
                    matches_by_pattern[pat_str] = LogMatch(
                        file=filepath,
                        pattern=pat_str,
                        count=1,
                        last_line=line[:300],
                        last_position=new_offset,
                    )

    return list(matches_by_pattern.values()), new_offset


def collect_logs(
    patterns: list[str],
    files: list[str],
    incremental: bool = True,
) -> LogReport:
    """
    Scan log files for error patterns.

    Args:
        patterns: List of regex patterns to search for (case-insensitive).
        files: List of file paths or glob patterns.
        incremental: If True, only scan new content since last run.
    """
    import time
    start_time = time.monotonic()

    # Compile patterns once
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error:
            compiled.append(re.compile(re.escape(p), re.IGNORECASE))

    resolved_files = _resolve_file_globs(files)
    positions = _load_positions() if incremental else {}

    all_matches = []
    failed_files = []
    scanned = 0

    for filepath in sorted(resolved_files):
        if not os.path.isfile(filepath):
            failed_files.append(filepath)
            continue

        if not os.access(filepath, os.R_OK):
            failed_files.append(filepath)
            continue

        offset = positions.get(filepath, 0) if incremental else 0
        matches, new_offset = _scan_file(filepath, compiled, patterns, offset)

        all_matches.extend(matches)
        positions[filepath] = new_offset
        scanned += 1

    if incremental:
        _save_positions(positions)

    elapsed = (time.monotonic() - start_time) * 1000

    return LogReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        matches=all_matches,
        files_scanned=scanned,
        files_failed=failed_files,
        scan_duration_ms=round(elapsed, 1),
    )
