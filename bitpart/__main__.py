"""Enables ``python -m bitpart ...`` as an alternative to the ``bitpart`` console script.

Useful when the venv's Scripts directory isn't on PATH but the package is installed.
"""
from bitpart.cli import main


if __name__ == "__main__":
    main()
