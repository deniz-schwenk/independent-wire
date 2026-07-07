# Intraday Collector

Spreads the day's **deterministic pre-work** (RSS delta fetch, dedup-on-append,
and — when translation is enabled — MADLAD prewarm of new non-Latin titles)
across five 4-hour windows instead of one 06:00 pass. Publication stays **1×/day**;
curation (LLM topic discovery) stays a **single pass at 06:00**. Intraday states
have no consumer — nothing publishes between runs.

Spec: `BACKLOG-INTRADAY-COLLECTOR.md` (Design sketch + Invariants apply verbatim).

## What it does

- **Schedule (local):** windows at **10:00 / 14:00 / 18:00 / 22:00 / 02:00**.
  The **06:00** slot is the main run (`org.independent-wire.daily`), which
  performs the final delta fetch itself — no collector/main-run collision.
- **Append-only day store** at `raw/{target-date}/feeds.json` — the *same* file
  the 06:00 run reads. Each window fetches the last-24h delta and dedup-appends
  it (URL, else source+title; deterministic Python — no LLM touches the store).
  Every entry carries an additive `first_seen` ISO timestamp (set once, on first
  append), enabling future narrative tracking without redesign.
- **Store is scoped to exactly ONE production run**, keyed by the target run
  date. Windows at/after 06:00 collect into *tomorrow's* store (10:00/14:00/
  18:00/22:00 → next day); the pre-dawn **02:00** window collects into *today's*
  06:00 run. After the 06:00 run consumes the store, a fresh one begins.
- **Translation prewarm (Phase 3, flag-gated):** when `IW_CLUSTER_TRANSLATE` is
  set, each window also translates the delta into the exact cache the 06:00
  sidecar reads (`output/_translate_cache/google__madlad400-3b-mt.json`),
  spreading the MADLAD load across ~6 small windows instead of one ~24.7 GB
  06:00 peak. Flag unset (production default) → prewarm is a silent no-op.

## Failure isolation & self-healing

- **Own LaunchAgent**, separate from `daily_run.sh`: a collector failure can
  never endanger the main run. The collector does **no** git pull / uv sync /
  publish / push — it only fetches into the store.
- **Missed windows self-heal:** the next window (or the 06:00 final delta fetch)
  picks up the items. A thin or empty night delta is a cheap no-op.
- **Branch guard:** `collector_run.sh` refuses to run unless `main` is checked
  out (same leftover-checkout hazard as the daily runner), and never
  auto-checkouts. A skip is a deliberate `exit 0`, not a retry-storm.
- **Corrupt store tolerated:** `load_store()` returns `[]` on an unreadable
  store, so a bad window rewrites it from fetch rather than crashing.
- **Concurrent-window safety:** the 4h grid guarantees windows never overlap (a
  fetch is seconds–minutes), so the file-based `undated_seen.json` and the
  store's read-modify-write are never concurrent. No locking needed.

## Logs

- Wrapper (launchd) trail: `~/iw-logs/collector-run-YYYY-MM-DD.log`.
- Per-window data line (target, fetched, new-after-dedup, wall):
  `~/iw-logs/collector-{target-date}.log`.
- launchd stdout/stderr: `/tmp/iw-collector.{out,err}`.

## Install / uninstall (Deniz — manual, its own landing window)

Activation is **not** automated. The plist ships in `scripts/`; install it only
when the collector is ready to go live (its own one-production-change window).

```sh
# Install (symlink so repo edits track through; then load without RunAtLoad):
ln -sf ~/iw/independent-wire/scripts/org.independent-wire.collector.plist \
       ~/Library/LaunchAgents/org.independent-wire.collector.plist
launchctl load -w ~/Library/LaunchAgents/org.independent-wire.collector.plist

# Status / run one window now (a REAL fetch into the target store):
launchctl list | grep independent-wire
launchctl start org.independent-wire.collector

# Uninstall:
launchctl unload -w ~/Library/LaunchAgents/org.independent-wire.collector.plist
rm ~/Library/LaunchAgents/org.independent-wire.collector.plist
```

## Manual invocation (testing)

Always point `--raw-root` at a throwaway dir — a stray write into the real
`raw/{tomorrow}/feeds.json` would contaminate the next production run.

```sh
uv run python scripts/fetch_feeds.py --collector-window \
  --raw-root /tmp/collector-smoke --run-date 2026-07-08 \
  --log-dir /tmp/collector-smoke-logs --window-label TEST
```
