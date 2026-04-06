#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import status  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action")

    p1 = subparsers.add_parser("add_idea")
    p1.add_argument("idea_id")
    p1.add_argument("idea_name")

    p2 = subparsers.add_parser("update_idea")
    p2.add_argument("idea_id")
    p2.add_argument("status")

    p3 = subparsers.add_parser("add_design")
    p3.add_argument("idea_id")
    p3.add_argument("design_id")
    p3.add_argument("desc")

    p4 = subparsers.add_parser("update_design")
    p4.add_argument("idea_id")
    p4.add_argument("design_id")
    p4.add_argument("status")

    p5 = subparsers.add_parser("get_idea_status")
    p5.add_argument("idea_id")

    p6 = subparsers.add_parser("get_design_status")
    p6.add_argument("idea_id")
    p6.add_argument("design_id")

    p7 = subparsers.add_parser("get_ideas_by_status")
    p7.add_argument("status")

    p8 = subparsers.add_parser("get_designs_by_status")
    p8.add_argument("idea_id")
    p8.add_argument("status")

    p9 = subparsers.add_parser("update_both")
    p9.add_argument("idea_id")
    p9.add_argument("design_id")
    p9.add_argument("idea_status")
    p9.add_argument("design_status")

    p10 = subparsers.add_parser("auto_sync")
    p10.add_argument("idea_id")
    p10.add_argument("design_id")

    subparsers.add_parser("sync_all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "add_idea":
        status.add_idea(args.idea_id, args.idea_name, root=Path.cwd())
    elif args.action == "update_idea":
        status.update_idea(args.idea_id, args.status, root=Path.cwd())
    elif args.action == "add_design":
        status.add_design(args.idea_id, args.design_id, args.desc, root=Path.cwd())
    elif args.action == "update_design":
        status.update_design(args.idea_id, args.design_id, args.status, root=Path.cwd())
    elif args.action == "get_idea_status":
        status.get_idea_status(args.idea_id, root=Path.cwd())
    elif args.action == "get_design_status":
        status.get_design_status(args.idea_id, args.design_id, root=Path.cwd())
    elif args.action == "get_ideas_by_status":
        status.get_ideas_by_status(args.status, root=Path.cwd())
    elif args.action == "get_designs_by_status":
        status.get_designs_by_status(args.idea_id, args.status, root=Path.cwd())
    elif args.action == "update_both":
        status.update_both(
            args.idea_id,
            args.design_id,
            args.idea_status,
            args.design_status,
            root=Path.cwd(),
        )
    elif args.action == "auto_sync":
        status.auto_update_status(args.idea_id, args.design_id, root=Path.cwd())
    elif args.action == "sync_all":
        status.sync_all(root=Path.cwd())
    else:
        build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
