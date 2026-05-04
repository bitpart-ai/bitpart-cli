"""Per-row progress printing.

Two modes, controlled by the ``debug`` flag in the pipeline:

* ``skip`` / ``error``   - always full message (these are the user-visible signal)
* ``created`` / ``file_exists`` - just a dot per row, with an every-50 milestone line

State (``need_newline``) is threaded as a dict so callers can drop a newline
before printing a non-dot message and not break the dot progress display.
"""


def print_progress(
    state: dict,
    debug: bool,
    kind: str,
    message: str,
    filename_for_milestone: str | None = None,
    success_count: int | None = None,
) -> None:
    """Print a row-level progress event. See module docstring for the kinds."""
    if kind in ("skip", "error"):
        if state.get("need_newline"):
            print()
            state["need_newline"] = False
        print(message)
        return
    if kind in ("created", "file_exists"):
        if debug:
            if state.get("need_newline"):
                print()
                state["need_newline"] = False
            print(message)
        else:
            print(".", end="", flush=True)
            state["need_newline"] = True
        if success_count is not None and success_count % 50 == 0 and filename_for_milestone:
            if state.get("need_newline"):
                print()
                state["need_newline"] = False
            print(f"  {success_count} processed - {filename_for_milestone}")
