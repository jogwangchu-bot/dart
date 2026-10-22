"""Run the bounded five-stock trial locally without putting a key in a file.

The cloud's OpenDART proxy is currently unavailable. This helper uses the
user's normal PC connection; it never bypasses TLS or proxy configuration.
"""
from __future__ import annotations

import contextlib
import getpass
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pit_dart.cli import main as cli_main
from pit_dart.core import atomic_write


class Tee:
    def __init__(self, console, file):
        self.console, self.file = console, file

    def write(self, text):
        self.console.write(text)
        self.file.write(text)
        self.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.file.flush()


def run_checks(root):
    child_env = dict(os.environ)
    # Test fixtures never need the user's real key.
    child_env.pop("DART_API_KEY", None)
    child_env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests", "--junitxml=logs/tests-pc.xml"],
                            cwd=root, env=child_env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    atomic_write(root / "logs" / "pc-software-tests.txt", (result.stdout + result.stderr).encode("utf-8"))
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def diagnostic_zip(root):
    path = root / "logs" / "PC_5_stock_diagnostics.zip"
    files = [root / "logs" / name for name in ("pc-five-stock.txt", "pc-five-stock-status.json", "pc-software-tests.txt", "tests-pc.xml", "events.jsonl")]
    batch = root / "output" / "2019-09-18" / "batch_001_005"
    files += [batch / name for name in ("coverage.csv", "missing.csv", "manifest.csv", "collection_report.md")]
    staging = path.with_suffix(".tmp")
    try:
        with ZipFile(staging, "w", ZIP_DEFLATED) as archive:
            for source in files:
                if source.is_file():
                    archive.write(source, source.relative_to(root))
        staging.replace(path)
    finally:
        if staging.exists():
            staging.unlink()
    return path


def run(root: Path | None = None):
    root = (root or PROJECT_ROOT).resolve()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    result = {"started_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
              "selected_stock_limit": 5, "asof": "2019-09-18", "live_stage": "NOT_STARTED", "software_test_exit": None}
    previous_directory = Path.cwd()
    original_key_present = bool(os.environ.get("DART_API_KEY"))
    injected_here = False
    exit_code = 2
    try:
        os.chdir(root)
        print("First: running software tests. No real API key is used in these tests.")
        result["software_test_exit"] = run_checks(root)
        if result["software_test_exit"] != 0:
            print("Software tests failed. Live requests were not started.")
            return 2
        if not original_key_present:
            key = getpass.getpass("OpenDART API key (input hidden; never sent to chat): ").strip()
            if not key:
                print("No key entered. No live API requests were started.")
                return 2
            os.environ["DART_API_KEY"] = key
            del key
            injected_here = True
        print("Starting only the first 5 stocks. This may take several minutes.")
        print("The API key is used only in this process and is not written to a file.")
        result["live_stage"] = "ATTEMPTED"
        with (root / "logs" / "pc-five-stock.txt").open("w", encoding="utf-8") as log:
            with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
                exit_code = cli_main(["--workspace", str(root), "--input", str(root / "input" / "universe.xlsx"),
                                      "--asof", "2019-09-18", "--expected-count", "390", "--test", "--resume"])
        result["live_stage"] = "COMMAND_FINISHED_REVIEW_COVERAGE" if exit_code == 0 else "COMMAND_FAILED_REVIEW_LOGS"
        print("Command finished. Read coverage.csv; a download is not historical approval.")
        return exit_code
    except (EOFError, KeyboardInterrupt):
        exit_code = 130
        result["live_stage"] = "INTERRUPTED"
        print("Interrupted. Existing checkpoints are preserved.")
        return exit_code
    except Exception:
        # Never print arbitrary exception contents or frame locals around a key.
        result["live_stage"] = "LOCAL_RUNNER_ERROR"
        print("Local runner error. No credential details were logged.", file=sys.stderr)
        return 2
    finally:
        if injected_here:
            os.environ.pop("DART_API_KEY", None)
        result["exit_code"] = exit_code
        atomic_write(root / "logs" / "pc-five-stock-status.json", json.dumps(result, ensure_ascii=False, indent=2).encode())
        try:
            path = diagnostic_zip(root)
            print("Send this diagnostic ZIP for review:", path)
            print("Do not send your API key. This ZIP is not an investor evaluation pack.")
        except OSError:
            print("Could not create the diagnostic ZIP; keep the logs folder.")
        os.chdir(previous_directory)


if __name__ == "__main__":
    raise SystemExit(run())
