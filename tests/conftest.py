"""Shared test setup.

Specula's tests drive the pipeline with fake agents and no web app. Point the toolkit at the stub in
tests/fixtures/webkit_stub/, so the real stack step and deterministic gates run without Docker.
"""

import os
from pathlib import Path

os.environ.setdefault("SPECULA_WEBKIT", str(Path(__file__).resolve().parent / "fixtures" / "webkit_stub"))
