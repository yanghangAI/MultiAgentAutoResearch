#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.dashboard import build_dashboard  # noqa: E402


def main() -> None:
    build_dashboard(root=Path.cwd())


if __name__ == "__main__":
    main()
