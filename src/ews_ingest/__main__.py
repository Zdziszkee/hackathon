"""Entry point: ``python -m ews_ingest``."""

from __future__ import annotations

import sys

from ews_ingest.cli import main

if __name__ == "__main__":
    sys.exit(main())
