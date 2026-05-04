"""Pytest config.

With the package installed via ``pip install -e .`` the ``bitpart.*`` imports
resolve through site-packages directly, so no ``sys.path`` munging is needed.
We still insert the repo root so ``from tests.tts.fixtures...`` works (lets
test files share helpers without ``conftest`` magic).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
