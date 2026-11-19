"""Runner preflight — step [0/6] of the daily runner (TASK-RUNNER-PREFLIGHT).

WHY THIS EXISTS. Three incident classes in two weeks were knowable before the
run spent anything, and each surfaced only mid-run or not at all:

* 2026-10-17/18 — port exhaustion (EADDRNOTAVAIL) killed the run mid-flight;
* 2026-10-23    — OpenRouter credits empty: the run FAILED at the editor after
                  20 minutes of paid work;
* 2026-10-24..26 — DeepSeek balance empty: three days with the planner on its
                  rung 2 and the six flash stages without their fallback rung.

THREE READ-ONLY CHECKS, nothing that can spend:

0. SOCKETS  — the TIME_WAIT count and the ephemeral port range, one INFO line
   on EVERY run (daily and collector), so the run log carries the daily trend
   while TIME_WAIT reaping on this box is unreliable. Never a trigger by itself.
1. NETWORK  — one HEAD request. Failure -> ABORT (exit 3) before step 1, with
   a diagnosis line carrying the errno and the same socket reading, so port
   exhaustion is named, not guessed.
2. OPENROUTER CREDITS — GET /credits. Remaining below the HARD floor -> ABORT
   with the balance; below the SOFT floor -> WARN and continue. Floors live in
   config/preflight.json.
3. DEEPSEEK BALANCE — GET /user/balance. Empty or unreachable -> WARN only,
   never abort: losing channel C is lost resilience, not a lost run.

Collector windows (``--mode collector``) run the network check only.

STDLIB ONLY. The preflight runs before step [2/6] ``uv sync`` — like the branch
guard, it cannot rely on the environment the runner has not set up yet.

CONTRACT. Exit 0 = proceed (warnings, if any, were printed and pinged);
exit 3 = abort, nothing was spent. Any other exit is a crash of the preflight
itself, which ``scripts/preflight.sh`` reports loudly and does NOT treat as an
abort — a broken safety check must not stop a healthy run. Notifications go
through the existing ``scripts/notify.sh`` (``NOTIFY_KIND=warn`` for warnings).
No credential is ever printed: only balances, statuses and errno names.
"""

from __future__ import annotations

import argparse
import errno as errno_mod
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "config" / "preflight.json"
NOTIFY_SH = REPO / "scripts" / "notify.sh"

EXIT_OK = 0
EXIT_ABORT = 3

OK, WARN, ABORT = "OK", "WARN", "ABORT"

CHANNEL_C_EMPTY = (
    "channel C has no funds — six flash stages are running without their "
    "fallback rung (and the planner starts on its rung 2)"
)


@dataclass
class HttpResponse:
    status: int
    body: bytes


Fetch = Callable[[str, str, dict, float], HttpResponse]


@dataclass
class Result:
    check: str
    level: str          # OK / WARN / ABORT
    line: str           # one log line
    notify: str = ""    # WARN: full Telegram text; ABORT: the reason only —
                        # run_preflight frames it per mode (abort vs skip)


def http_fetch(method: str, url: str, headers: dict, timeout: float) -> HttpResponse:
    """One request. An HTTP error status is a RESPONSE (the network worked);
    only a transport failure raises (OSError / URLError)."""
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return HttpResponse(r.status, r.read() if method != "HEAD" else b"")
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, e.read() or b"")


# ------------------------------------------------------------- diagnostics


def _errno_of(exc: BaseException) -> tuple[int | None, str]:
    """Dig the OS errno out of urllib's wrapping (URLError.reason)."""
    seen = exc
    for _ in range(4):
        num = getattr(seen, "errno", None)
        if isinstance(num, int):
            return num, errno_mod.errorcode.get(num, str(num))
        if isinstance(seen, (socket.timeout, TimeoutError)):
            return None, "TIMEOUT"
        nxt = getattr(seen, "reason", None)
        if not isinstance(nxt, BaseException):
            break
        seen = nxt
    if isinstance(seen, socket.gaierror):
        return None, "DNS"
    return None, type(seen).__name__


def time_wait_count() -> str:
    try:
        out = subprocess.run(
            ["netstat", "-an", "-p", "tcp"], capture_output=True, text=True,
            timeout=3,
        ).stdout
        return str(sum(1 for line in out.splitlines() if "TIME_WAIT" in line))
    except Exception:  # noqa: BLE001 — diagnostics are advisory
        return "unknown"


def ephemeral_port_range() -> str:
    try:
        first, last = (
            subprocess.run(
                ["sysctl", "-n", f"net.inet.ip.portrange.{k}"],
                capture_output=True, text=True, timeout=3,
            ).stdout.strip()
            for k in ("first", "last")
        )
        return f"{first}-{last} ({int(last) - int(first) + 1} ports)"
    except Exception:  # noqa: BLE001
        return "unknown"


# ------------------------------------------------------------------ checks


def socket_reading() -> str:
    """One measurement per run: shared by the INFO line and the network
    diagnosis, so the two never disagree and netstat runs once."""
    return (f"TIME_WAIT sockets {time_wait_count()}; "
            f"ephemeral port range {ephemeral_port_range()}")


def check_network(cfg: dict, fetch: Fetch, sockets: str | None = None) -> Result:
    url = cfg["network_probe_url"]
    t0 = time.monotonic()
    try:
        resp = fetch("HEAD", url, {}, float(cfg["timeout_s"]))
    except OSError as exc:
        num, name = _errno_of(exc)
        exhaustion = " — PORT EXHAUSTION" if name == "EADDRNOTAVAIL" else ""
        line = (
            f"NETWORK DOWN: HEAD {url} failed — errno {name}"
            f"{f' ({num})' if num is not None else ''}{exhaustion}: {exc}; "
            f"{sockets or socket_reading()}"
        )
        return Result("network", ABORT, line,
                      f"network down (errno {name}{exhaustion})")
    return Result("network", OK,
                  f"network OK: HEAD {url} -> HTTP {resp.status} in {time.monotonic() - t0:.2f}s")


def check_openrouter_credits(cfg: dict, fetch: Fetch, env: dict) -> Result:
    hard = float(cfg["openrouter_hard_floor_usd"])
    soft = float(cfg["openrouter_soft_floor_usd"])
    key = env.get("OPENROUTER_API_KEY", "")
    if not key:
        return Result("openrouter", ABORT,
                      "OPENROUTER CREDITS: OPENROUTER_API_KEY is not set — every LLM stage would fail",
                      "OPENROUTER_API_KEY not set")
    try:
        resp = fetch("GET", cfg["openrouter_credits_url"],
                     {"Authorization": f"Bearer {key}"}, float(cfg["timeout_s"]))
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        data = json.loads(resp.body)["data"]
        remaining = float(data["total_credits"]) - float(data["total_usage"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Cannot verify is not "empty": warn loudly, let the run decide.
        return Result("openrouter", WARN,
                      f"OPENROUTER CREDITS UNVERIFIED: GET /credits failed ({type(exc).__name__}: {exc}) — continuing",
                      f"WARN: OpenRouter credits could not be checked ({exc}) — the run continues.")
    if remaining < hard:
        return Result("openrouter", ABORT,
                      f"OPENROUTER CREDITS BELOW HARD FLOOR: ${remaining:.2f} remaining < ${hard:.2f} — aborting before any spend",
                      f"OpenRouter credits ${remaining:.2f} < hard floor ${hard:.2f} — top up OpenRouter")
    if remaining < soft:
        return Result("openrouter", WARN,
                      f"OPENROUTER CREDITS LOW: ${remaining:.2f} remaining < soft floor ${soft:.2f} — continuing",
                      f"WARN: OpenRouter credits ${remaining:.2f} < soft floor ${soft:.2f} — the run continues. Top up soon.")
    return Result("openrouter", OK,
                  f"openrouter credits OK: ${remaining:.2f} remaining (soft floor ${soft:.2f}, hard ${hard:.2f})")


def _usd_balance(data: dict) -> float | None:
    infos = data.get("balance_infos") or []
    pick = next((i for i in infos if i.get("currency") == "USD"), infos[0] if infos else None)
    if pick is None:
        return None
    return float(pick.get("total_balance") or 0)


def check_deepseek_balance(cfg: dict, fetch: Fetch, env: dict) -> Result:
    key = env.get("DEEPSEEK_API_KEY", "")
    if not key:
        return Result("deepseek", WARN,
                      f"DEEPSEEK BALANCE: DEEPSEEK_API_KEY is not set — {CHANNEL_C_EMPTY}",
                      f"WARN: {CHANNEL_C_EMPTY}. DEEPSEEK_API_KEY not set. The run continues.")
    try:
        resp = fetch("GET", cfg["deepseek_balance_url"],
                     {"Authorization": f"Bearer {key}"}, float(cfg["timeout_s"]))
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        data = json.loads(resp.body)
        available = bool(data.get("is_available"))
        balance = _usd_balance(data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return Result("deepseek", WARN,
                      f"DEEPSEEK BALANCE UNREACHABLE ({type(exc).__name__}: {exc}) — cannot confirm channel C; continuing",
                      f"WARN: DeepSeek balance unreachable ({exc}) — channel C may have no funds; six flash stages may be running without their fallback rung. The run continues.")
    shown = "unknown" if balance is None else f"{balance:.2f}"
    if not available or balance is None or balance <= 0:
        return Result("deepseek", WARN,
                      f"DEEPSEEK BALANCE EMPTY: is_available={available}, balance {shown} — {CHANNEL_C_EMPTY}; continuing",
                      f"WARN: {CHANNEL_C_EMPTY}. DeepSeek balance {shown}. The run continues.")
    return Result("deepseek", OK, f"deepseek balance OK: {shown} (is_available=True)")


# -------------------------------------------------------------- the runner


def notify_via_script(source: str, text: str, kind: str) -> None:
    """Best-effort ping through scripts/notify.sh, which always exits 0."""
    env = dict(os.environ, NOTIFY_KIND=kind)
    try:
        subprocess.run(["zsh", str(NOTIFY_SH), source, text], env=env, timeout=30)
    except Exception as exc:  # noqa: BLE001 — a ping never breaks the runner
        print(f"[0/6] notify failed ({exc}) — continuing", file=sys.stderr)


def load_config(path: Path | None = None) -> dict:
    p = path or Path(os.environ.get("IW_PREFLIGHT_CONFIG") or DEFAULT_CONFIG)
    return json.loads(p.read_text(encoding="utf-8"))


def run_preflight(
    mode: str,
    source: str,
    cfg: dict,
    fetch: Fetch = http_fetch,
    notify: Callable[[str, str, str], None] = notify_via_script,
    env: dict | None = None,
    out=sys.stdout,
) -> int:
    env = dict(os.environ) if env is None else env
    t0 = time.monotonic()
    say = lambda s: print(s, file=out, flush=True)  # noqa: E731
    say(f"[0/6] preflight ({mode}) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}".rstrip())

    sockets = socket_reading()
    say(f"[0/6]   INFO  {sockets}")

    results = [check_network(cfg, fetch, sockets)]
    if results[0].level == OK and mode == "daily":
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(check_openrouter_credits, cfg, fetch, env),
                pool.submit(check_deepseek_balance, cfg, fetch, env),
            ]
            results += [f.result() for f in futures]

    for r in results:
        say(f"[0/6]   {r.level:<5} {r.line}")

    aborts = [r for r in results if r.level == ABORT]
    for r in results:
        if r.level == WARN:
            notify(source, r.notify, "warn")
    elapsed = time.monotonic() - t0
    if aborts:
        what = "no fetch this window" if mode == "collector" else (
            "No fetch / pull / pipeline / publish / push was performed."
        )
        say("====================================================")
        say(f"ABORT — {source} — preflight — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        for r in aborts:
            say(f"  {r.line}")
        say(f"  {what}")
        say("====================================================")
        reason = "; ".join(r.notify for r in aborts)
        notify(source, f"SKIP: {reason} — no fetch this window." if mode == "collector"
               else f"ABORT: {reason} — nothing ran.", "abort")
        say(f"[0/6] preflight ABORT in {elapsed:.1f}s")
        return EXIT_ABORT
    warns = sum(r.level == WARN for r in results)
    say(f"[0/6] preflight done in {elapsed:.1f}s — {len(results)} check(s), "
        f"{warns} warning(s), 0 aborts")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=("daily", "collector"), default="daily")
    ap.add_argument("--source", default="daily_run.sh")
    args = ap.parse_args(argv)
    return run_preflight(args.mode, args.source, load_config())


if __name__ == "__main__":
    raise SystemExit(main())
