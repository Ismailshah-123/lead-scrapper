"""Convenience script: `python scripts/init_db.py`. Identical to
`python -m app initdb` — provided separately because some people expect a
plain scripts/ entry point rather than a package CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db  # noqa: E402

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
