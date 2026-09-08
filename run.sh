#!/usr/bin/env bash
# Start the whole system on localhost, from cold.
#
#   ./run.sh            build the console and serve it with the API
#   ./run.sh --stop     stop both
#   ./run.sh --status   what is listening
#
# Why a script rather than two commands: the failure that kept recurring here
# was two servers half-running on the same ports with stale build output between
# them. The page then renders correct HTML pointing at a stylesheet that no
# longer exists, which looks exactly like a broken design and is not one. This
# frees the ports first, rebuilds from clean, and verifies the stylesheet
# actually loads before telling you it is ready.
set -uo pipefail
cd "$(dirname "$0")"

# Ports are overridable because 3000 is the default for every Next project on a
# machine, and this one lost a race with another app that had claimed it. A
# system that has to be demonstrated should not depend on winning that race.
API_PORT="${SAMVEDNA_API_PORT:-8090}"
WEB_PORT="${SAMVEDNA_WEB_PORT:-3100}"
LOG_DIR="${TMPDIR:-/tmp}/samvedna"
mkdir -p "$LOG_DIR"
# We record what we start, so stopping is a fact rather than a guess. Next
# renames its own process to "next-server (vX)", which contains nothing that
# identifies the project — an args match refused to kill our own server.
API_PID_FILE="$LOG_DIR/api.pid"
WEB_PID_FILE="$LOG_DIR/web.pid"

# Free a port only if what holds it is ours. Killing whatever happens to be
# listening is how a start script takes down somebody else's work — this nearly
# took down another of the owner's apps on :3000.
#
# Ownership is decided by the pid file we wrote when we started it, not by
# inspecting process arguments. Next renames its process to "next-server (vX)",
# which identifies no project, so an args match both fails to recognise our own
# server *and* would have to fall back to something looser to work at all.
free_port() {
  local port="$1" pid_file="$2"
  local pids ours
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  [ -z "$pids" ] && return 0
  ours=$(cat "$pid_file" 2>/dev/null || true)

  for pid in $pids; do
    if [ -n "$ours" ] && [ "$pid" = "$ours" ]; then
      echo "  freeing :$port (pid $pid — started by this script)"
      kill -9 "$pid" 2>/dev/null || true
      continue
    fi
    # Not in our pid file. Check whether it is at least running out of this
    # directory before refusing, so a server started by hand is still ours.
    local cwd
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
    case "$cwd" in
      "$(pwd)"*)
        echo "  freeing :$port (pid $pid — running from this project)"
        kill -9 "$pid" 2>/dev/null || true ;;
      *)
        echo "  :$port is held by something that is not ours:"
        echo "      $(ps -p "$pid" -o args= 2>/dev/null | head -c 100)"
        echo "      working directory: ${cwd:-unknown}"
        echo "  set SAMVEDNA_WEB_PORT / SAMVEDNA_API_PORT to use other ports."
        return 1 ;;
    esac
  done
  sleep 1
}

status() {
  for port in $API_PORT $WEB_PORT; do
    local pid
    pid=$(lsof -ti :"$port" 2>/dev/null | head -1 || true)
    if [ -n "$pid" ]; then
      printf '  :%-5s  pid %-8s %s\n' "$port" "$pid" "$(ps -p "$pid" -o comm= 2>/dev/null)"
    else
      printf '  :%-5s  free\n' "$port"
    fi
  done
}

case "${1:-}" in
  --stop)
    echo "stopping…"
    free_port "$API_PORT" "$API_PID_FILE" || true
    free_port "$WEB_PORT" "$WEB_PID_FILE" || true
    rm -f "$API_PID_FILE" "$WEB_PID_FILE"
    status; exit 0 ;;
  --status)
    status; exit 0 ;;
esac

echo "SAMVEDNA — starting"
free_port "$API_PORT" "$API_PID_FILE" || exit 1
free_port "$WEB_PORT" "$WEB_PID_FILE" || exit 1

echo "  building the console"
( cd web && rm -rf .next && npm run --silent build >"$LOG_DIR/build.log" 2>&1 ) || {
  echo "  BUILD FAILED — see $LOG_DIR/build.log"; tail -20 "$LOG_DIR/build.log"; exit 1;
}

echo "  starting the API on :$API_PORT   (a REPLAY night runs first)"
nohup uv run samvedna serve --units 4 --strength 60 --port "$API_PORT" \
  >"$LOG_DIR/api.log" 2>&1 &
echo $! >"$API_PID_FILE"

echo "  starting the console on :$WEB_PORT"
( cd web && nohup npx next start --port "$WEB_PORT" >"$LOG_DIR/web.log" 2>&1 &
  echo $! >"$WEB_PID_FILE" )

# Wait on the thing that actually matters: a page whose STYLESHEET resolves.
#
# Waiting on the page alone is what hid this bug twice — the HTML returned 200
# while the stylesheet it referenced returned 404, and the page rendered as raw
# browser defaults. Python rather than curl, because curl is not on every host
# this has to run on and a missing curl silently turned this loop into a stall.
echo "  waiting for the console and its stylesheet"
if ! uv run --quiet python - "$WEB_PORT" "$API_PORT" <<'PYCHECK'
import re, sys, time, urllib.request, urllib.error

web, api = sys.argv[1], sys.argv[2]

def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception:
        return 0, ""

for _ in range(90):
    status, home = fetch(f"http://127.0.0.1:{web}/")
    if status == 200:
        sheets = re.findall(r'href="(/_next/static/css/[^"]+)"', home)
        if sheets and all(fetch(f"http://127.0.0.1:{web}{s}")[0] == 200 for s in sheets):
            print(f"  console ready, stylesheet {sheets[0][-24:]} resolves")
            break
    time.sleep(2)
else:
    print("  console did not come up cleanly")
    raise SystemExit(1)

for _ in range(90):
    if fetch(f"http://127.0.0.1:{api}/api/health")[0] == 200:
        print("  api ready, nightly run complete")
        break
    time.sleep(2)
else:
    print("  api did not come up — the nightly run may still be generating")
    raise SystemExit(1)
PYCHECK
then
  echo
  echo "  startup failed. Logs:"
  echo "    console: $LOG_DIR/web.log"
  echo "    api:     $LOG_DIR/api.log"
  tail -15 "$LOG_DIR/web.log" 2>/dev/null
  exit 1
fi

echo
echo "  ready:  http://localhost:$WEB_PORT"
echo "  api:    http://localhost:$API_PORT/docs"
echo "  logs:   $LOG_DIR"
echo
echo "  Start at /demo for the guided walkthrough, or /signin to pick a role."
