import json
import os
from zipfile import ZipFile

from tools import run_pc_test


def test_pc_runner_uses_hidden_prompt_process_env_and_never_saves_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(run_pc_test, "run_checks", lambda root: 0)
    monkeypatch.setattr(run_pc_test.getpass, "getpass", lambda prompt: "SYNTHETIC_PC_SECRET_NOT_REAL")
    calls = []
    def fake_cli(arguments):
        assert os.environ["DART_API_KEY"] == "SYNTHETIC_PC_SECRET_NOT_REAL"
        calls.append(arguments)
        print("Synthetic local trial only")
        return 0
    monkeypatch.setattr(run_pc_test, "cli_main", fake_cli)
    assert run_pc_test.run(tmp_path) == 0
    assert "DART_API_KEY" not in os.environ
    assert "--test" in calls[0] and "--all" not in calls[0]
    archive = tmp_path / "logs" / "PC_5_stock_diagnostics.zip"
    with ZipFile(archive) as zipped:
        for name in zipped.namelist():
            assert b"SYNTHETIC_PC_SECRET_NOT_REAL" not in zipped.read(name)


def test_pc_runner_existing_key_skips_prompt_and_retains_original_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "SYNTHETIC_EXISTING_KEY")
    monkeypatch.setattr(run_pc_test, "run_checks", lambda root: 0)
    monkeypatch.setattr(run_pc_test, "cli_main", lambda arguments: 2)
    def forbidden_prompt(prompt):
        raise AssertionError("Prompt must not run")
    monkeypatch.setattr(run_pc_test.getpass, "getpass", forbidden_prompt)
    assert run_pc_test.run(tmp_path) == 2
    assert os.environ["DART_API_KEY"] == "SYNTHETIC_EXISTING_KEY"
    record = json.loads((tmp_path / "logs" / "pc-five-stock-status.json").read_text())
    assert record["exit_code"] == 2
    assert record["live_stage"] == "COMMAND_FAILED_REVIEW_LOGS"


def test_pc_runner_failed_checks_never_prompt_or_start_live_request(tmp_path, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(run_pc_test, "run_checks", lambda root: 1)
    def not_called(*arguments):
        raise AssertionError("Live step must not run after failing software tests")
    monkeypatch.setattr(run_pc_test, "cli_main", not_called)
    monkeypatch.setattr(run_pc_test.getpass, "getpass", not_called)
    assert run_pc_test.run(tmp_path) == 2
    record = json.loads((tmp_path / "logs" / "pc-five-stock-status.json").read_text())
    assert record["software_test_exit"] == 1 and record["live_stage"] == "NOT_STARTED"
