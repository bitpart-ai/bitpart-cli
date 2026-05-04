"""Top-level ``bitpart`` CLI dispatcher.

Each subcommand lives in its own subpackage and exposes two functions:

    register(subparsers) -> ArgumentParser   # adds its subparser + args
    handle(args)         -> None             # runs it

Adding a new subcommand is a two-line change here: import its ``cli`` module and
append it to ``SUBCOMMANDS``. Everything else (help text, dispatch, error
handling) is wired automatically.
"""
import argparse
import sys

from bitpart import __version__
from bitpart.tts import cli as tts_cli

# Order here is the order shown in ``bitpart --help``.
SUBCOMMANDS = (tts_cli,)


def main() -> None:
    """Entry point for the ``bitpart`` console script and ``python -m bitpart``."""
    parser = argparse.ArgumentParser(
        prog="bitpart",
        description="Bitpart CLI — game-content automation tools.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"bitpart {__version__}",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        title="commands",
    )

    handlers: dict[str, callable] = {}
    for module in SUBCOMMANDS:
        sub_parser = module.register(subparsers)
        # ``sub_parser.prog`` is e.g. ``"bitpart tts"`` — last token is the subcommand name.
        handlers[sub_parser.prog.rsplit(maxsplit=1)[-1]] = module.handle

    args = parser.parse_args()

    if not args.command:
        parser.print_help(sys.stderr)
        sys.exit(2)

    handlers[args.command](args)
