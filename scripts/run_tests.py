"""Run unit tests across agent submodules."""

from pathlib import Path
import argparse
import io
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

TEST_DIRS = [
    ROOT / "agents" / "candidate_profile" / "tests",
    ROOT / "agents" / "job_search" / "tests",
    ROOT / "agents" / "job_match" / "tests",
    ROOT / "agents" / "orchestrator" / "tests",
]


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.passed_tests: list[str] = []
        self.failed_tests: list[str] = []
        self.skipped_tests: list[str] = []

    def addSuccess(self, test) -> None:
        super().addSuccess(test)
        self.passed_tests.append(test.id())

    def addFailure(self, test, err) -> None:
        super().addFailure(test, err)
        self.failed_tests.append(test.id())

    def addError(self, test, err) -> None:
        super().addError(test, err)
        self.failed_tests.append(test.id())

    def addSkip(self, test, reason) -> None:
        super().addSkip(test, reason)
        self.skipped_tests.append(test.id())


def run_single_dir(test_dir: Path) -> int:
    """Run unittest discovery for a single test directory.

    Args:
        test_dir: Directory containing tests.

    Returns:
        Exit code (0 if all tests pass).
    """
    if not test_dir.exists():
        print(f"Skipping missing tests dir: {test_dir}")
        return 0

    print(f"Running tests in: {test_dir}")
    suite = unittest.defaultTestLoader.discover(str(test_dir))
    runner = unittest.TextTestRunner(
        stream=io.StringIO(),
        verbosity=0,
        resultclass=RecordingResult,
    )
    result = runner.run(suite)
    total_count = result.testsRun
    passed_count = len(result.passed_tests)
    failed_count = len(result.failed_tests)
    skipped_count = len(result.skipped_tests)
    status = "PASSED" if result.wasSuccessful() else "FAILED"
    print(f"Results: {status} | ran={total_count} passed={passed_count} failed={failed_count} skipped={skipped_count}")
    print(
        f"__SUMMARY__ ran={total_count} passed={passed_count} failed={failed_count} "
        f"skipped={skipped_count} status={status}"
    )
    if result.passed_tests:
        print("Passed tests:")
        for test_name in result.passed_tests:
            print(f"- {test_name}")
    if result.failed_tests:
        print("Failed tests:")
        for test_name in result.failed_tests:
            print(f"- {test_name}")
    if result.skipped_tests:
        print("Skipped tests:")
        for test_name in result.skipped_tests:
            print(f"- {test_name}")
    return 0 if result.wasSuccessful() else 1


def run_tests() -> int:
    """Run unittest discovery for each test directory in isolated processes.

    Args:
        None.

    Returns:
        Exit code (0 if all tests pass).
    """
    exit_code = 0
    total_tests = 0
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    script_path = Path(__file__).resolve()
    for test_dir in TEST_DIRS:
        result = subprocess.run(
            [sys.executable, str(script_path), "--dir", str(test_dir)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(result.stdout, end="")
            for line in result.stdout.splitlines():
                if not line.startswith("__SUMMARY__"):
                    continue
                parts = dict(item.split("=", 1) for item in line.split()[1:])
                total_tests += int(parts.get("ran", 0))
                total_passed += int(parts.get("passed", 0))
                total_failed += int(parts.get("failed", 0))
                total_skipped += int(parts.get("skipped", 0))
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode != 0:
            exit_code = result.returncode
    if total_tests:
        status = "PASSED" if exit_code == 0 else "FAILED"
        print(
            f"Total: {status} | ran={total_tests} passed={total_passed} "
            f"failed={total_failed} skipped={total_skipped}"
        )
    return exit_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, help="Run tests in a single directory.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.dir:
        raise SystemExit(run_single_dir(args.dir))
    raise SystemExit(run_tests())
