#!/usr/bin/env bash
# Deploy / control the live persona bot.
#
#   ./restart.sh            syntax-check, run tests, restart, verify
#   SKIP_TESTS=1 ./restart.sh   deploy without the test gate (escape hatch)
#   ./restart.sh status     running? since when? config loaded? anything stale?
#   ./restart.sh stop       shut it down
#   ./restart.sh logs       follow the log
#
# The PID lives in .bot.pid so nothing has to go hunting through ps.
set -uo pipefail
cd "$(dirname "$(realpath "$0")")"

PY=.venv/bin/python
PIDFILE=.bot.pid
LOG=live.log
PATTERN='\.venv/bin/python bot\.py --live'
# brain.py is imported at startup, so a change to it needs a restart.
# brain/people/*.md are deliberately NOT here: those are re-read from
# disk on every reply, so editing a profile takes effect immediately.
WATCHED=(bot.py brain.py persona.md .env)

# --- helpers ---------------------------------------------------------------

bot_pid() {
    # Trust the pidfile if the process it names is really ours; otherwise fall
    # back to a scan, so a manually-started bot is still found and managed.
    if [ -f "$PIDFILE" ]; then
        local pid
        pid=$(cat "$PIDFILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null &&
           tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'bot.py'; then
            echo "$pid"
            return 0
        fi
        rm -f "$PIDFILE"
    fi
    pgrep -f "$PATTERN" | head -1
}

check_tests() {
    # The suite is fast and hermetic (no network, no real .env), so it can gate
    # every deploy rather than being something to remember to run.
    if [ ! -x "$PY" ] || ! $PY -c "import pytest" 2>/dev/null; then
        echo "    (pytest not installed - skipping tests)"
        return 0
    fi
    local out
    if ! out=$($PY -m pytest tests/ -q 2>&1); then
        echo "TESTS FAILED - not deploying:"
        echo "$out" | tail -15 | sed 's/^/    /'
        return 1
    fi
    echo "    $(echo "$out" | grep -E '^[0-9]+ passed' | tail -1)"
}

check_syntax() {
    if ! $PY -c "import ast, sys; ast.parse(open('bot.py').read())" 2>/tmp/pb_syntax; then
        echo "SYNTAX ERROR in bot.py — not deploying:"
        sed 's/^/    /' /tmp/pb_syntax
        return 1
    fi
}

# Is anything on disk newer than the running process?
check_stale() {
    local pid=$1 started stale=0
    started=$(date -d "$(ps -o lstart= -p "$pid")" +%s 2>/dev/null) || return 0
    for f in "${WATCHED[@]}"; do
        [ -f "$f" ] || continue
        if [ "$(stat -c %Y "$f")" -gt "$started" ]; then
            echo "    STALE: $f edited after the bot started"
            stale=1
        fi
    done
    return $stale
}

stop() {
    local pid
    pid=$(bot_pid)
    if [ -z "$pid" ]; then
        rm -f "$PIDFILE"
        echo "not running"
        return 0
    fi
    kill "$pid" 2>/dev/null
    # Wait for it to actually exit. Starting a second instance while the first
    # is alive means every message gets answered twice.
    for _ in $(seq 40); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null
    rm -f "$PIDFILE"
    echo "stopped (was pid $pid)"
}

start() {
    setsid nohup $PY bot.py --live > "$LOG" 2>&1 < /dev/null &
    local pid=$!
    echo "$pid" > "$PIDFILE"
    for _ in $(seq 60); do
        grep -q 'Live mode:' "$LOG" 2>/dev/null && break
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    if ! grep -q 'Live mode:' "$LOG" 2>/dev/null; then
        echo "FAILED to start. Last lines of $LOG:"
        grep -viE 'pynacl|davey' "$LOG" | tail -15 | sed 's/^/    /'
        rm -f "$PIDFILE"
        return 1
    fi
}

status() {
    local pid
    pid=$(bot_pid)
    if [ -z "$pid" ]; then
        echo "NOT RUNNING"
        return 1
    fi
    echo "running  pid $pid  since $(ps -o lstart= -p "$pid" | xargs)"
    grep -E 'Live mode:|Mentions:|Allies:|New day|Poking|Idle openers:' "$LOG" 2>/dev/null |
        tail -6 | sed 's/^.*personabot: /    /'
    local extra
    extra=$(pgrep -cf "$PATTERN")
    [ "$extra" -gt 1 ] && echo "    WARNING: $extra instances running — run ./restart.sh"
    if check_stale "$pid"; then
        echo "    up to date"
    fi
}

# --- commands --------------------------------------------------------------

case "${1:-deploy}" in
    stop)   stop ;;
    status) status ;;
    logs)   tail -f "$LOG" ;;
    deploy|restart|start)
        check_syntax || exit 1
        [ "${SKIP_TESTS:-}" = "1" ] || check_tests || exit 1
        stop > /dev/null
        start || exit 1
        status ;;
    *) echo "usage: $0 [deploy|status|stop|logs]"; exit 2 ;;
esac
