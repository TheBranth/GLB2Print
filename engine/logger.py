"""
logger.py - Centralized logging and crash diagnostics for GLB2Print.
Writes persistent logs to glb2print.log and retains in-memory rolling buffer for UI diagnostics.
"""

import os
import sys
import time
import threading
import traceback
from collections import deque
from pathlib import Path
from typing import List, Optional

LOG_FILENAME = "glb2print.log"
_MAX_BUFFER_LINES = 1000
_log_buffer = deque(maxlen=_MAX_BUFFER_LINES)
_log_lock = threading.Lock()

def get_log_path() -> Path:
    """Returns the absolute path to glb2print.log in the project root."""
    root_dir = Path(__file__).resolve().parent.parent
    return root_dir / LOG_FILENAME

def _format_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def log(msg: str, level: str = "INFO", print_console: bool = True):
    """Logs a message with timestamp and level to file, memory buffer, and stdout."""
    line = f"[{_format_timestamp()}] [{level.upper():5s}] {msg}"
    with _log_lock:
        _log_buffer.append(line)
        try:
            log_file = get_log_path()
            with open(log_file, "a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
        except Exception:
            pass

    if print_console:
        print(line, flush=True)

def log_info(msg: str):
    log(msg, level="INFO")

def log_warn(msg: str):
    log(msg, level="WARN")

def log_error(msg: str):
    log(msg, level="ERROR")

def log_crash(title: str, exc: Optional[BaseException] = None, extra_context: Optional[str] = None):
    """Writes a prominent, formatted crash report block to the log file and buffer."""
    sep = "=" * 70
    crash_lines = [
        "",
        sep,
        f"🚨 GLB2PRINT CRASH / ERROR REPORT: {title}",
        f"Timestamp: {_format_timestamp()}",
        f"Platform: {sys.platform} ({os.name})",
        f"Python: {sys.version.split()[0]}",
    ]
    if extra_context:
        crash_lines.append(f"Context: {extra_context}")
    if exc:
        crash_lines.append("Traceback:")
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        crash_lines.append(tb_str.strip())
    crash_lines.append(sep)
    crash_lines.append("")

    full_report = "\n".join(crash_lines)
    with _log_lock:
        for cl in crash_lines:
            _log_buffer.append(cl)
        try:
            log_file = get_log_path()
            with open(log_file, "a", encoding="utf-8", errors="replace") as f:
                f.write(full_report + "\n")
        except Exception:
            pass

    print(full_report, file=sys.stderr, flush=True)

def get_recent_logs(max_lines: int = 300) -> List[str]:
    """Returns the most recent log lines from the in-memory buffer."""
    with _log_lock:
        lines = list(_log_buffer)
    if len(lines) > max_lines:
        return lines[-max_lines:]
    return lines

def clear_logs():
    """Clears log buffer and truncates log file."""
    with _log_lock:
        _log_buffer.clear()
        try:
            log_file = get_log_path()
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"[{_format_timestamp()}] [INFO ] Log file initialized.\n")
        except Exception:
            pass
