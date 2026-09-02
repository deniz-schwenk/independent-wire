#!/bin/zsh
# Best-effort Telegram ping for runner aborts (TASK-ABORT-NOTIFY).
#
# WHY THIS EXISTS. On 2026-08-27 the 06:00 run hit the branch guard, wrote its
# refusal to a log file, and stopped. Nothing else happened, and nothing said
# so — the silent morning was discovered at noon. An abort and a crash are
# equally invisible when the only witness is a log nobody is reading.
#
# WHY zsh + curl RATHER THAN THE `telegram` EXTRA. The earliest abort path in
# daily_run.sh — the branch guard — runs BEFORE step [2/6] `uv sync`, so at
# that moment the venv may hold whatever the last run left behind and
# python-telegram-bot may not be importable at all. A notifier that depends on
# the environment the runner has not set up yet cannot report the failure to
# set it up. curl is always there. It is also ~20 lines against a dependency.
#
# CONTRACT
#   scripts/notify.sh <source> <reason...>
#   ALWAYS exits 0. A notification that breaks the runner is worse than no
#   notification, so every failure here is swallowed after one line on stderr.
#   NOTIFY_DRY=1 prints the message and sends nothing.
#
# CREDENTIALS. TELEGRAM_BOT_TOKEN and TELEGRAM_HOME_CHANNEL, looked up in the
# repo .env first and then ~/.hermes/.env (the existing Hermes bot). The repo
# .env carries neither today, so the Hermes file is the live source — that is
# deliberate: duplicating a bot token into a second file to save one fallback
# branch is a worse trade than the fallback. Values are read into locals, never
# echoed, never written to the log, and never placed in a filename. The API URL
# embeds the token, so it is built inline and `curl` is given -s -o /dev/null;
# only the HTTP status is ever surfaced.

emit_err() { print -r -- "$1" >&2; }

SOURCE="${1:-unknown}"
shift 2>/dev/null || true
REASON="${*:-no reason given}"
# First line only, trimmed — an abort banner is many lines and Telegram is not
# a log viewer. The log remains the full record; this is the pointer to it.
REASON="${${REASON%%$'\n'*}##[[:space:]]#}"

REPO="${${0:A}:h:h}"
STAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || echo host)"
TEXT="🚨 Independent Wire — ${SOURCE}
${STAMP} on ${HOSTNAME_SHORT}
${REASON}
No run was completed. See ~/iw-logs/."

if [[ -n "${NOTIFY_DRY:-}" ]]; then
  print -r -- "--- NOTIFY_DRY: would send ---"
  print -r -- "$TEXT"
  print -r -- "------------------------------"
  exit 0
fi

# --- credentials ------------------------------------------------------------
read_var() {  # read_var <name> <file>  -> value on stdout, nothing on miss
  [[ -r "$2" ]] || return 1
  local line="${(@)${(f)"$(<"$2")"}[(r)${1}=*]}"
  [[ -n "$line" ]] || return 1
  local v="${line#*=}"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  print -r -- "${v//[[:space:]]/}"
}

TOKEN=""; CHAT=""
for f in "$REPO/.env" "$HOME/.hermes/.env"; do
  [[ -z "$TOKEN" ]] && TOKEN="$(read_var TELEGRAM_BOT_TOKEN "$f" 2>/dev/null)"
  [[ -z "$CHAT"  ]] && CHAT="$(read_var TELEGRAM_HOME_CHANNEL "$f" 2>/dev/null)"
done

if [[ -z "$TOKEN" || -z "$CHAT" ]]; then
  emit_err "notify: no TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL found — ping skipped"
  exit 0
fi

# --- send -------------------------------------------------------------------
# 10s connect / 20s total: the runner must not hang on a network stall.
CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  --connect-timeout 10 --max-time 20 \
  "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${CHAT}" \
  --data-urlencode "text=${TEXT}" \
  --data-urlencode "disable_web_page_preview=true" 2>/dev/null || echo 000)"

if [[ "$CODE" != "200" ]]; then
  emit_err "notify: Telegram send failed (HTTP ${CODE}) — continuing anyway"
fi
exit 0
