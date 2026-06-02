# Mac Mini Production Runner

How the daily pipeline runs unattended on the Mac Mini, and how to reproduce or
manage the setup. Established 2026-06-02.

## Architecture (two-machine)

- **MacBook Air** = development. Work happens here with the Architect; commits push to `main`.
- **Mac Mini** = production runner. Always on. Each day it pulls `main`, produces the
  three Topic Packages, publishes, and commits/pushes **only `site/`**. It never
  originates code changes.

This separation keeps development and production from colliding: the Mini's daily
`site/` commits and the Air's code commits touch different files.

## Paths & toolchain (Mini)

- Repo: `~/Documents/independent-wire/repo-clone`
- Package manager: `uv` at `~/.local/bin/uv` (installed via `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python: 3.11.x, managed by `uv` (project requires `>=3.11`); `uv sync` installs it and all deps from `uv.lock`
- Secrets: `~/Documents/independent-wire/repo-clone/.env` (gitignored). Only
  `OPENROUTER_API_KEY` is required (covers LLM calls and Perplexity search).
  NOTE: the code reads `os.environ` directly (no python-dotenv), so `daily_run.sh`
  sources `.env` into the environment before running anything.

## Git push auth (SSH deploy key)

The Mini authenticates to GitHub with a **repo-scoped deploy key** (not an account key —
the machine's GitHub login is `shivenek`, which lacks write access to the
`deniz-schwenk/independent-wire` repo; a deploy key is attached to the repo itself and
sidesteps that).

- Key: `~/.ssh/iw_deploy` (ed25519, no passphrase — required for unattended use)
- SSH host alias in `~/.ssh/config`:
  ```
  Host github.com-iw
    HostName github.com
    User git
    IdentityFile ~/.ssh/iw_deploy
    IdentitiesOnly yes
  ```
- Remote: `git@github.com-iw:deniz-schwenk/independent-wire.git`
- The **public** key (`~/.ssh/iw_deploy.pub`) is registered on the repo:
  GitHub → repo → Settings → Deploy keys → with **"Allow write access"** checked.
- Local git identity on the Mini: `shivenek <57815225+deniz-schwenk@users.noreply.github.com>`
  (`git config --local`).

## Previous-coverage bootstrap (follow-up mechanic)

The Editor's follow-up links come from `_scan_previous_coverage` (in
`src/stages/run_stages.py`), which reads local `output/{date}/tp-*.json` for the last
7 days. Because `output/` is gitignored, a fresh clone has no history. One-time bootstrap:
copy the last ~7 days of `output/{date}/` from the Air into the Mini's `output/`.
After ~7 days of its own runs the Mini is self-sustaining and never needs the Air for this.

## Daily flow — `scripts/daily_run.sh`

Deterministic, no LLM-orchestration. Steps, logged to `~/iw-logs/run-YYYY-MM-DD.log`
(last line is `SUCCESS` or `FAILED`):

1. `git pull --rebase origin main`  (latest code from the Air)
2. `uv sync`                        (match deps to pulled code)
3. `scripts/fetch_feeds.py`         (RSS → `raw/{date}/feeds.json`)
4. `scripts/run.py --hydrated`      (the pipeline; ~€1/run)
5. `scripts/publish.py`             (TP-JSON → `site/` HTML)
6. `git add site/` (explicit) → commit if changed → `git push origin main`

It sets its own `PATH` and sources `.env` because launchd runs with a minimal environment.

NOTE on first run after a template change: `publish.py` re-renders the last several days
of TPs with the current code. A render/template change therefore re-renders older pages
and commits those diffs on the next run. This is expected, not an error.

## Scheduler — launchd

- Agent: `~/Library/LaunchAgents/org.independent-wire.daily.plist`
- Fires daily at **06:00** local (`StartCalendarInterval`), runs
  `/bin/zsh -lc <repo>/scripts/daily_run.sh`
- launchd stdout/stderr: `/tmp/iw-launchd.{out,err}`; the real log is `~/iw-logs/`.
- **No pmset wake needed:** the Mini does not sleep (`pmset -g` → `sleep 0`).

Management:
- Status:  `launchctl list | grep independent-wire`
- Run now (triggers a REAL run): `launchctl start org.independent-wire.daily`
- Disable: `launchctl unload ~/Library/LaunchAgents/org.independent-wire.daily.plist`
- Re-enable: `launchctl load -w ~/Library/LaunchAgents/org.independent-wire.daily.plist`

## Report layer — Hermes + Claude Code (07:00)

A separate scheduler (Hermes) runs at 07:00 — after the 06:00 pipeline has finished
(~06:40) — and invokes Claude Code in print mode (`claude -p ... --max-turns 10`) with
workdir = the repo, to read that day's log + produced TP JSONs + `git log`, then deliver
a short German report via Telegram. The prompt instructs: **report only, never commit
code fixes** — real errors go in the report and are fixed on the Air, not patched
autonomously overnight. (Hermes' own auth context avoids the unsolved question of whether
`claude -p` works headless under launchd with a subscription rather than an API key.)

## Reproduce from scratch (Mini)

1. `git clone git@github.com-iw:deniz-schwenk/independent-wire.git ~/Documents/independent-wire/repo-clone`
   (after the SSH deploy key + `~/.ssh/config` alias are in place)
2. `cd` in; `~/.local/bin/uv sync`
3. `cp .env.example .env` and set `OPENROUTER_API_KEY`
4. Bootstrap previous coverage (copy last 7 days of `output/{date}/` from the Air)
5. Install the launchd agent (plist above) and `launchctl load -w` it
6. Point Hermes' 07:00 report job at the repo

## Open follow-ups

- Phase 2 hardening: if/when wanted, verify `claude -p` headless auth under launchd with
  the subscription, to allow a fully self-contained report job without Hermes.
