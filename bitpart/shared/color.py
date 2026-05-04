"""ANSI color helpers, with TTY auto-detection.

Color is suppressed automatically when stdout is redirected to a file or
piped — log files stay clean. On Windows we run ``os.system("")`` once to
flip on VT processing for the current console session (a well-known trick
that works on Windows 10+, modern PowerShell, Windows Terminal, and the
VS Code integrated terminal).
"""
import os
import sys


def _supports_color() -> bool:
    """Best-effort detection: is the current stdout a terminal that handles ANSI color?"""
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            os.system("")
        except Exception:
            return False
    return True


_USE_COLOR = _supports_color()


def yellow(s: str) -> str:
    """Wrap a string in ANSI yellow, or return as-is if color isn't supported."""
    return f"\033[33m{s}\033[0m" if _USE_COLOR else s
