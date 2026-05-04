"""Helpers used by **two or more** ``bitpart`` subcommands.

If a helper is only used by one subcommand, it belongs in that subcommand's
package (e.g. ``bitpart.tts.csv_io``), not here. This rule is what keeps
``shared`` from rotting into a junk drawer.

Current contents:

    bitpart.shared.color    - ANSI color helpers + TTY auto-detection
"""
