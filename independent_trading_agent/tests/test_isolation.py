"""Proof that the app stays out of TradingAgents' way."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from independent_trading_agent.config import settings as settings_mod
from independent_trading_agent.config.settings import PACKAGE_DIR, load_settings
from independent_trading_agent.core.runtime import AlreadyRunning, RunLock, redact
from independent_trading_agent.integrations import tradingagents_adapter
from independent_trading_agent.integrations.llm_client import LLMClient, LLMUnavailable

ROOT = PACKAGE_DIR.parent


def test_only_prefixed_env_vars_are_read(tmp_path):
    env = {"TRADINGAGENTS_LLM_PROVIDER": "anthropic", "INDEPENDENT_AGENT_TOP_N": "7",
           "INDEPENDENT_AGENT_MARKETS": "forex,crypto", "TOP_N": "99"}
    s = load_settings(env_file=None, toml_file=None, environ=env)
    assert s.top_n == 7 and s.markets == ["forex", "crypto"]
    assert not hasattr(s, "llm_provider")


def test_env_file_only_loads_prefixed_keys(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("INDEPENDENT_AGENT_TOP_N=3\nGOOGLE_API_KEY=should-not-load\n", encoding="utf-8")
    monkeypatch.delenv("INDEPENDENT_AGENT_TOP_N", raising=False)
    values = settings_mod._parse_env_file(f)
    assert values == {"INDEPENDENT_AGENT_TOP_N": "3"}


def test_storage_lives_inside_the_app_folder():
    s = load_settings(env_file=None, toml_file=None, environ={})
    for path in (s.db_path, Path(s.reports_dir), Path(s.logs_dir)):
        assert PACKAGE_DIR in Path(path).resolve().parents or Path(path).resolve() == PACKAGE_DIR
    assert s.db_path.name == "independent_agent.db"


def test_settings_hold_no_secrets(monkeypatch):
    monkeypatch.setenv("INDEPENDENT_AGENT_GEMINI_API_KEY", "AIzaFAKEFAKEFAKEFAKEFAKE123")
    s = load_settings(env_file=None, toml_file=None)
    assert "AIzaFAKE" not in str(s.public_dict())


def test_importing_the_app_does_not_import_tradingagents():
    code = ("import sys, independent_trading_agent.app.runs, independent_trading_agent.dashboard.server; "
            "print('tradingagents' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stderr


def test_integration_failure_is_contained(monkeypatch, tmp_path):
    monkeypatch.setattr(tradingagents_adapter, "is_available", lambda: False)
    res = tradingagents_adapter.run_deep_analysis("EURUSD=X", "2026-11-12", asset_type="stock",
                                                  analysts="market", timeout=5, data_dir=str(tmp_path))
    assert res["ok"] is False
    opinion = tradingagents_adapter.to_opinion(res)
    assert opinion.confidence == 0  # carries no weight in the decision


def test_llm_without_keys_is_unavailable(monkeypatch):
    for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(f"INDEPENDENT_AGENT_{k}", raising=False)
    llm = LLMClient("gemini:x,openrouter:y", 5, 1)
    assert not llm.available
    with pytest.raises(LLMUnavailable):
        llm.chat("s", "u")


def test_redaction_masks_keys(monkeypatch):
    monkeypatch.setenv("INDEPENDENT_AGENT_OPENROUTER_API_KEY", "sk-or-v1-abcdefabcdefabcdef1234")
    text = redact("failed with key sk-or-v1-abcdefabcdefabcdef1234 and api_key=SECRETVALUE123")
    assert "abcdef" not in text and "SECRETVALUE123" not in text


def test_single_instance_lock(tmp_path):
    lock = tmp_path / "x.lock"
    with RunLock(lock), pytest.raises(AlreadyRunning), RunLock(lock):
        pass
    lock.write_text("999999 stale")  # a dead owner's lock is taken over
    with RunLock(lock):
        assert lock.exists()
    assert not lock.exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_no_repository_file_outside_the_app_changed_since_baseline():
    base = (PACKAGE_DIR / "docs" / "BASELINE").read_text().strip().split("=", 1)[1]
    if subprocess.run(["git", "cat-file", "-e", base], cwd=ROOT).returncode != 0:
        pytest.skip("baseline commit not in this clone")
    changed = subprocess.run(["git", "diff", "--name-only", base], cwd=ROOT, capture_output=True, text=True).stdout
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                               text=True).stdout
    outside = [p for p in (changed + untracked).splitlines() if p and not p.startswith(PACKAGE_DIR.name + "/")]
    assert outside == [], f"files outside {PACKAGE_DIR.name}/ changed: {outside}"


def test_dashboard_binds_to_localhost_only():
    src = (PACKAGE_DIR / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '"127.0.0.1"' in src and "0.0.0.0" not in src


def test_main_tradingagents_tests_untouched():
    assert os.path.isdir(ROOT / "tests") and os.path.isdir(ROOT / "tradingagents")
