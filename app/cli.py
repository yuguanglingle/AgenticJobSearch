"""CLI entrypoint for reproducible local runs."""

from __future__ import annotations

import argparse
import json

from .runtime import run_pipeline_command


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agentic Job Search CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_name in ("run", "daily"):
        command = subparsers.add_parser(command_name, help=f"Run pipeline ({command_name}).")
        command.add_argument("--profile", default="default", help="Profile name from config/profiles/<name>.json")
        command.add_argument("--candidate-id", help="Override candidate id")
        command.add_argument("--limit", type=int, help="Override limit_to_score")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    result = run_pipeline_command(
        command_name=args.command,
        profile_name=args.profile,
        candidate_id=args.candidate_id,
        limit_to_score=args.limit,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
