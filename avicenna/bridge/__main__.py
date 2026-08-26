"""`python -m avicenna.bridge` — what the TUI spawns."""

from __future__ import annotations

import sys

from avicenna.bridge.server import main

if __name__ == "__main__":
    sys.exit(main())
