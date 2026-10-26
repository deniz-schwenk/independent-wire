"""Runner preflight — TASK-RUNNER-PREFLIGHT.

Each check both ways (ok / triggering) through a fake transport that records
every request, so the abort paths are shown to spend nothing: the only calls
ever made are the read-only HEAD/GET probes named in config/preflight.json.
The zsh wrapper and notify.sh are exercised for real (NOTIFY_DRY=1, a closed
local port for "network down") — no external request, no Telegram send.
"""

from __future__ import annotations

import ast
import errno
import io
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import preflight as pf  # noqa: E402

CFG = pf.load_config(REPO / "config" / "preflight.json")
ENV = {"OPENROUTER_API_KEY": "or-test", "DEEPSEEK_API_KEY": "ds-test"}


def _credits(remaining: float) -> pf.HttpResponse:
    return pf.HttpResponse(200, json.dumps(
        {"data": {"total_credits": 100.0, "total_usage": 100.0 - remaining}}).encode())


def _balance(amount: str, available: bool = True) -> pf.HttpResponse:
    return pf.HttpResponse(200, json.dumps({
        "is_available": available,
        "balance_infos": [{"currency": "USD", "total_balance": amount,
                           "granted_balance": "0.00", "topped_up_balance": amount}],
    }).encode())


class FakeFetch:
    """Answers by URL; an Exception value is raised (a transport failure)."""

    def __init__(self, network=None, credits=None, balance=None):
        self.routes = {
            CFG["network_probe_url"]: network or pf.HttpResponse(200, b""),
            CFG["openrouter_credits_url"]: credits or _credits(50.0),
            CFG["deepseek_balance_url"]: balance or _balance("12.34"),
        }
        self.requests: list[tuple[str, str]] = []

    def __call__(self, method, url, headers, timeout):
        self.requests.append((method, url))
        answer = self.routes[url]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _run(fetch, mode="daily", env=ENV):
    notes: list[tuple[str, str, str]] = []
    out = io.StringIO()
    rc = pf.run_preflight(mode, f"{'daily_run' if mode == 'daily' else 'collector_run'}.sh",
                          CFG, fetch=fetch,
                          notify=lambda s, t, k: notes.append((s, t, k)),
                          env=env, out=out)
    return rc, out.getvalue(), notes


def _assert_spent_nothing(fetch: FakeFetch) -> None:
    allowed = {("HEAD", CFG["network_probe_url"]),
               ("GET", CFG["openrouter_credits_url"]),
               ("GET", CFG["deepseek_balance_url"])}
    assert set(fetch.requests) <= allowed, fetch.requests
    assert not any("completions" in url for _, url in fetch.requests)


@pytest.fixture(autouse=True)
def _fixed_diagnostics(monkeypatch):
    monkeypatch.setattr(pf, "time_wait_count", lambda: "16211")
    monkeypatch.setattr(pf, "ephemeral_port_range", lambda: "49152-65535 (16384 ports)")


# ------------------------------------------------------------------ sockets


@pytest.mark.parametrize("mode", ["daily", "collector"])
def test_time_wait_is_logged_as_info_on_every_run(mode):
    """The daily TIME_WAIT trend belongs in the run log on green runs too,
    not only in the failure diagnosis."""
    rc, out, notes = _run(FakeFetch(), mode=mode)
    assert rc == pf.EXIT_OK and notes == []
    assert ("[0/6]   INFO  TIME_WAIT sockets 16211; ephemeral port range "
            "49152-65535 (16384 ports)") in out.splitlines()


def test_sockets_are_measured_once_per_run(monkeypatch):
    calls = []
    monkeypatch.setattr(pf, "time_wait_count", lambda: calls.append(1) or "7")
    exc = urllib.error.URLError(OSError(errno.EADDRNOTAVAIL, "x"))
    rc, out, _ = _run(FakeFetch(network=exc))
    assert rc == pf.EXIT_ABORT and len(calls) == 1
    assert out.count("TIME_WAIT sockets 7;") == 3     # INFO, check line, banner


# ------------------------------------------------------------------ network


def test_all_green_proceeds_with_three_checks_and_no_ping():
    fetch = FakeFetch()
    rc, out, notes = _run(fetch)
    assert rc == pf.EXIT_OK and notes == []
    assert "network OK" in out and "credits OK: $50.00" in out and "balance OK: 12.34" in out
    assert "0 warning(s), 0 aborts" in out
    assert len(fetch.requests) == 3
    _assert_spent_nothing(fetch)


def test_port_exhaustion_aborts_before_anything_else_and_names_itself():
    exc = urllib.error.URLError(OSError(errno.EADDRNOTAVAIL, "Can't assign requested address"))
    fetch = FakeFetch(network=exc)
    rc, out, notes = _run(fetch)
    assert rc == pf.EXIT_ABORT
    assert fetch.requests == [("HEAD", CFG["network_probe_url"])]   # nothing after
    assert "errno EADDRNOTAVAIL (49) — PORT EXHAUSTION" in out
    assert "TIME_WAIT sockets 16211" in out and "49152-65535 (16384 ports)" in out
    assert "ABORT — daily_run.sh — preflight" in out
    assert "No fetch / pull / pipeline / publish / push was performed." in out
    assert notes == [("daily_run.sh",
                      "ABORT: network down (errno EADDRNOTAVAIL — PORT EXHAUSTION) — nothing ran.",
                      "abort")]


def test_other_network_errors_are_named_too():
    fetch = FakeFetch(network=urllib.error.URLError(TimeoutError("timed out")))
    rc, out, _ = _run(fetch)
    assert rc == pf.EXIT_ABORT and "errno TIMEOUT" in out and "PORT EXHAUSTION" not in out


def test_an_http_error_status_still_means_the_network_works():
    rc, out, _ = _run(FakeFetch(network=pf.HttpResponse(503, b"")))
    assert rc == pf.EXIT_OK and "HTTP 503" in out


# --------------------------------------------------------- openrouter credits


def test_credits_below_hard_floor_abort_with_the_balance():
    fetch = FakeFetch(credits=_credits(1.25))
    rc, out, notes = _run(fetch)
    assert rc == pf.EXIT_ABORT
    assert "BELOW HARD FLOOR: $1.25 remaining < $3.00" in out
    assert ("daily_run.sh",
            "ABORT: OpenRouter credits $1.25 < hard floor $3.00 — top up OpenRouter — nothing ran.",
            "abort") in notes
    _assert_spent_nothing(fetch)


def test_credits_below_soft_floor_warn_and_continue():
    rc, out, notes = _run(FakeFetch(credits=_credits(5.5)))
    assert rc == pf.EXIT_OK
    assert "WARN  OPENROUTER CREDITS LOW: $5.50 remaining < soft floor $8.00" in out
    assert notes == [("daily_run.sh",
                      "WARN: OpenRouter credits $5.50 < soft floor $8.00 — the run continues. Top up soon.",
                      "warn")]


def test_floors_come_from_config(monkeypatch):
    cfg = dict(CFG, openrouter_hard_floor_usd=60.0)
    fetch = FakeFetch()
    rc = pf.run_preflight("daily", "daily_run.sh", cfg, fetch=fetch,
                          notify=lambda *a: None, env=ENV, out=io.StringIO())
    assert rc == pf.EXIT_ABORT                       # $50 < configured $60


def test_unverifiable_credits_warn_not_abort():
    rc, out, notes = _run(FakeFetch(credits=pf.HttpResponse(500, b"")))
    assert rc == pf.EXIT_OK and "CREDITS UNVERIFIED" in out and notes[0][2] == "warn"


def test_missing_openrouter_key_aborts():
    fetch = FakeFetch()
    rc, out, _ = _run(fetch, env={"DEEPSEEK_API_KEY": "ds-test"})
    assert rc == pf.EXIT_ABORT and "OPENROUTER_API_KEY is not set" in out
    assert ("GET", CFG["openrouter_credits_url"]) not in fetch.requests


# ----------------------------------------------------------- deepseek balance


@pytest.mark.parametrize("balance", [
    _balance("0.00", available=False),
    _balance("0.00", available=True),
    pf.HttpResponse(200, json.dumps({"is_available": False, "balance_infos": []}).encode()),
])
def test_empty_channel_c_warns_never_aborts(balance):
    rc, out, notes = _run(FakeFetch(balance=balance))
    assert rc == pf.EXIT_OK
    assert "DEEPSEEK BALANCE EMPTY" in out
    assert pf.CHANNEL_C_EMPTY in notes[0][1] and notes[0][2] == "warn"


def test_unreachable_channel_c_warns_never_aborts():
    rc, out, notes = _run(FakeFetch(balance=urllib.error.URLError(OSError(errno.ECONNRESET, "reset"))))
    assert rc == pf.EXIT_OK and "DEEPSEEK BALANCE UNREACHABLE" in out
    assert notes and notes[0][2] == "warn"


def test_soft_credits_and_empty_channel_c_ping_twice_and_continue():
    rc, _, notes = _run(FakeFetch(credits=_credits(4.0), balance=_balance("0.00", False)))
    assert rc == pf.EXIT_OK and [k for *_, k in notes] == ["warn", "warn"]


# ------------------------------------------------------------- collector mode


def test_collector_runs_the_network_check_only():
    fetch = FakeFetch(credits=_credits(0.0), balance=_balance("0.00", False))
    rc, out, notes = _run(fetch, mode="collector")
    assert rc == pf.EXIT_OK and notes == []
    assert fetch.requests == [("HEAD", CFG["network_probe_url"])]


def test_collector_network_down_skips_the_window():
    fetch = FakeFetch(network=urllib.error.URLError(OSError(errno.EADDRNOTAVAIL, "x")))
    rc, out, notes = _run(fetch, mode="collector")
    assert rc == pf.EXIT_ABORT and "no fetch this window" in out
    assert notes[0][1].startswith("SKIP: network down (errno EADDRNOTAVAIL")
    assert notes[0][1].endswith("— no fetch this window.")


# ---------------------------------------------------------- module contract


def test_preflight_module_is_stdlib_only():
    """It runs before `uv sync`, like the branch guard."""
    tree = ast.parse((REPO / "scripts" / "preflight.py").read_text())
    mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    assert mods - {"__future__"} <= set(sys.stdlib_module_names), mods


def test_errno_extraction_through_urllib_wrapping():
    num, name = pf._errno_of(urllib.error.URLError(OSError(errno.EADDRNOTAVAIL, "x")))
    assert (num, name) == (errno.EADDRNOTAVAIL, "EADDRNOTAVAIL")


# ------------------------------------------- the real shell wrapper + notify


def _shell(tmp_path, cfg: dict, mode="daily", extra_env=None):
    cfg_path = tmp_path / "preflight.json"
    cfg_path.write_text(json.dumps(cfg))
    log = tmp_path / "run.log"
    env = dict(os.environ, IW_PREFLIGHT_CONFIG=str(cfg_path), NOTIFY_DRY="1",
               **(extra_env or {}))
    rc = subprocess.run(
        ["zsh", str(REPO / "scripts" / "preflight.sh"), mode,
         "daily_run.sh" if mode == "daily" else "collector_run.sh", str(log)],
        env=env, timeout=60,
    ).returncode
    return rc, log.read_text()


def test_shell_wrapper_network_down_exits_3_with_banner_and_dry_ping(tmp_path):
    # 127.0.0.1:9 (discard) is closed: a real ECONNREFUSED, no external request.
    rc, log = _shell(tmp_path, dict(CFG, network_probe_url="http://127.0.0.1:9/"))
    assert rc == 3
    assert "errno ECONNREFUSED" in log and "TIME_WAIT sockets" in log
    assert "--- NOTIFY_DRY: would send ---" in log and "🚨" in log
    assert "ABORT: network down (errno ECONNREFUSED) — nothing ran." in log


def test_shell_wrapper_survives_a_crashing_preflight(tmp_path):
    """A broken safety check must not stop a healthy run: exit 0, loud line,
    warn ping."""
    log = tmp_path / "run.log"
    env = dict(os.environ, IW_PREFLIGHT_CONFIG=str(tmp_path / "missing.json"), NOTIFY_DRY="1")
    rc = subprocess.run(["zsh", str(REPO / "scripts" / "preflight.sh"), "daily",
                         "daily_run.sh", str(log)], env=env, timeout=60).returncode
    text = log.read_text()
    assert rc == 0
    assert "preflight could not run (exit 1) — continuing WITHOUT it" in text
    assert "⚠️" in text and "The run continues." in text


def test_notify_warn_kind_and_default_kind():
    def dry(kind):
        env = dict(os.environ, NOTIFY_DRY="1")
        if kind:
            env["NOTIFY_KIND"] = kind
        return subprocess.run(["zsh", str(REPO / "scripts" / "notify.sh"), "src", "reason"],
                              env=env, capture_output=True, text=True, timeout=30).stdout
    assert "⚠️" in dry("warn") and "The run continues." in dry("warn")
    assert "🚨" in dry(None) and "No run was completed." in dry(None)


# ------------------------------------------------------------- runner wiring


def test_daily_runner_preflights_after_the_guards_and_before_step_one():
    s = (REPO / "scripts" / "daily_run.sh").read_text()
    pre = s.index('scripts/preflight.sh" daily')
    assert s.index("end stale git index.lock guard") < pre
    assert pre < s.index("trap '") < s.index('echo "[1/6] git pull')
    block = s[pre:s.index("end preflight")]
    assert "PREFLIGHT_RC == 3" in block and "exit 1" in block


def test_collector_runner_preflights_network_only_before_the_fetch():
    s = (REPO / "scripts" / "collector_run.sh").read_text()
    pre = s.index('scripts/preflight.sh" collector')
    assert s.index("Branch guard") < pre < s.index("fetch_feeds.py --collector-window")
    assert "exit 0" in s[pre:s.index("collector window — $(date)")]
