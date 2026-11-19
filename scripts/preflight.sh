#!/bin/zsh
# Runner preflight wrapper — step [0/6] (TASK-RUNNER-PREFLIGHT).
#
#   scripts/preflight.sh <daily|collector> <source> <log>
#
# Runs scripts/preflight.py (stdlib only) with the repo .env loaded, appending
# its section to <log>. It runs BEFORE `uv sync`, so it uses the venv the last
# run left behind and falls back to the system python3.
#
# EXIT 0 = proceed (warnings were printed and pinged by preflight.py).
# EXIT 3 = abort: preflight.py already wrote the ABORT banner and sent the ping;
#          the caller only exits (daily_run.sh -> exit 1; collector -> skip).
# A CRASH of the preflight itself (any other exit) is reported loudly — one log
# line and a warn ping — and does NOT stop the run: a broken safety check must
# never take down a healthy morning.

MODE="${1:?mode}"; SOURCE="${2:?source}"; LOG="${3:?log}"
REPO="${${0:A}:h:h}"
PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 2>/dev/null || echo python3)"

RC=0
(
  if [[ -f "$REPO/.env" ]]; then set -a; source "$REPO/.env"; set +a; fi
  exec "$PY" "$REPO/scripts/preflight.py" --mode "$MODE" --source "$SOURCE"
) >>"$LOG" 2>&1 || RC=$?

case "$RC" in
  0) exit 0 ;;
  3) exit 3 ;;
  *)
    echo "[0/6] preflight could not run (exit $RC) — continuing WITHOUT it" >>"$LOG"
    NOTIFY_KIND=warn zsh "$REPO/scripts/notify.sh" "$SOURCE" \
      "WARN: preflight could not run (exit $RC) — the run continues unchecked." \
      >>"$LOG" 2>&1 || true
    exit 0
    ;;
esac
