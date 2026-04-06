#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import dashboard, deploy, results, status, submit  # noqa: E402
from scripts.lib.layout import repo_root  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified scripts CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize_parser = subparsers.add_parser("summarize-results")
    summarize_parser.add_argument("--root", type=Path, default=repo_root())

    sync_parser = subparsers.add_parser("sync-status")
    sync_parser.add_argument("--root", type=Path, default=repo_root())

    submit_parser = subparsers.add_parser("submit-implemented")
    submit_parser.add_argument("--root", type=Path, default=repo_root())
    submit_parser.add_argument("--max-jobs", type=int, default=30)
    submit_parser.add_argument("--dry-run", action="store_true")

    submit_test_parser = subparsers.add_parser("submit-test")
    submit_test_parser.add_argument("target_dir", nargs="?", type=Path, default=None)
    submit_test_parser.add_argument("--root", type=Path, default=repo_root())
    submit_test_parser.add_argument("--dry-run", action="store_true")

    submit_train_parser = subparsers.add_parser("submit-train")
    submit_train_parser.add_argument("train_py", type=Path)
    submit_train_parser.add_argument("job_name", nargs="?", default="train_job")
    submit_train_parser.add_argument("--root", type=Path, default=repo_root())

    setup_design_parser = subparsers.add_parser("setup-design")
    setup_design_parser.add_argument("src", type=Path)
    setup_design_parser.add_argument("dst", type=Path)
    setup_design_parser.add_argument("--root", type=Path, default=repo_root())

    build_parser_cmd = subparsers.add_parser("build-dashboard")
    build_parser_cmd.add_argument("--root", type=Path, default=repo_root())

    deploy_parser = subparsers.add_parser("deploy-dashboard")
    deploy_parser.add_argument("--root", type=Path, default=repo_root())
    deploy_parser.add_argument("--allow-dirty", action="store_true")
    deploy_parser.add_argument("--no-push", action="store_true")

    update_parser = subparsers.add_parser("update-all")
    update_parser.add_argument("--root", type=Path, default=repo_root())
    update_parser.add_argument("--allow-dirty", action="store_true")
    update_parser.add_argument("--no-push", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "summarize-results":
        results.summarize_results(root=args.root)
    elif args.command == "sync-status":
        status.sync_all(root=args.root)
    elif args.command == "submit-implemented":
        submit.submit_implemented(root=args.root, max_jobs=args.max_jobs, dry_run=args.dry_run)
    elif args.command == "submit-test":
        submit.submit_test(
            root=args.root,
            target_dir=args.target_dir,
            dry_run=args.dry_run,
        )
    elif args.command == "submit-train":
        submit.submit_train_script(
            train_script=(args.root / args.train_py).resolve() if not args.train_py.is_absolute() else args.train_py,
            job_name=args.job_name,
            root=args.root,
        )
    elif args.command == "setup-design":
        from scripts.tools.setup_design import setup_design  # noqa: E402

        setup_design(
            src=(args.root / args.src).resolve() if not args.src.is_absolute() else args.src,
            dst=(args.root / args.dst).resolve() if not args.dst.is_absolute() else args.dst,
            root=args.root,
        )
    elif args.command == "build-dashboard":
        dashboard.build_dashboard(root=args.root)
    elif args.command == "deploy-dashboard":
        deploy.deploy_dashboard(root=args.root, allow_dirty=args.allow_dirty, push=not args.no_push)
    elif args.command == "update-all":
        status.sync_all(root=args.root)
        dashboard.build_dashboard(root=args.root)
        deploy.deploy_dashboard(root=args.root, allow_dirty=args.allow_dirty, push=not args.no_push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
