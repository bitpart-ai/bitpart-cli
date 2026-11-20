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


def warn(s: str) -> None:
    """Print a warning line in yellow (plain text when color is disabled)."""
    if _USE_COLOR:
        print(f"\033[33m{s}\033[0m")
    else:
        print(s)
