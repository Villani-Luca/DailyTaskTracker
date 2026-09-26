"""Vercel entrypoint: Vercel serves the FastAPI instance named ``app`` in this file.

Locally, run ``tasktracker`` instead. See "Deploy to Vercel" in the README.
"""

import sys
from pathlib import Path

# Make the src/ layout importable whether or not the build installed the package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tasktracker.main import create_app  # noqa: E402

app = create_app()
