"""Root pytest configuration: ensure connectors register + fix landing dir in tests."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("EWS_LANDING_DIR", str(Path(__file__).resolve().parent / "_landing"))
