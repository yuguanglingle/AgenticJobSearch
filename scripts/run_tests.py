"""Run unit tests across agent submodules."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

TEST_DIRS = [
    ROOT / "agents" / "candidate_profile" / "tests",
    ROOT / "agents" / "job_search" / "tests",
    ROOT / "agents" / "job_match" / "tests",
    ROOT / "agents" / "orchestrator" / "tests",
]


def run_tests() -> int:
    """Run unittest discovery for each test directory.

    Args:
        None.

    Returns:
        Exit code (0 if all tests pass).
    """
    exit_code = 0
    for test_dir in TEST_DIRS:
        if not test_dir.exists():
            print(f"Skipping missing tests dir: {test_dir}")
            continue
        print(f"Running tests in: {test_dir}")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(test_dir)],
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            exit_code = result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_tests())
