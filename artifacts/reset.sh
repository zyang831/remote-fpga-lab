#!/bin/bash
# Put the whole demo back to a known good state, before or after a session:
#   0. board reachable: its only uplink is Ethernet to this PC (eno1, NM profile
#      board-share sharing the PC's WiFi); checked first so nothing is torn down
#   1. stop lab-backend (drops the in-memory queue, stops it racing our deploy)
#   2. board -> default classifier (catalog fruit artifact), same call the
#      backend makes on release
#   3. board health: model name, coredla-fpga / dla-server / ustreamer active
#      (restarts a dead unit if BOARD_SUDO_PASS is set)
#   4. start lab-backend, wait for it, check /session/models and /session/model
#
#   ./reset.sh [artifact-name]
#
# Mender creds: MENDER_USER / MENDER_PASS from the environment, else from the
# backend's ~/mender/lab-backend/lab-backend.env (the systemd unit reads the same file).
# Optional: SESSION_SECONDS (longer slot for a demo), BOARD_SUDO_PASS.
set -eu
U=${MENDER_URL:-https://mender.example.ts.net}
DEV=${DEVICE_ID:-56bc13f6-c33d-4637-8f25-c4eb03605b40}
NAME=${1:-coredla-model-fruit-7580298c}   # same as the backend catalog default (camera arch)
BOARD=${BOARD_SSH:-terasic@coredla}
STREAM=${BOARD_STREAM_URL:-http://coredla:8080/stream}
LAB=~/mender/lab-backend
PATTERN="uvicorn main:app --host 0.0.0.0 --port 8000"
UNITS="coredla-fpga dla-server ustreamer"
FAIL=0
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
step() { printf '\n== %s\n' "$*"; }
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 $BOARD"

# ---- creds -----------------------------------------------------------------
if [ -z "${MENDER_USER:-}" ] || [ -z "${MENDER_PASS:-}" ]; then
    set -a; . "$LAB/lab-backend.env"; set +a
fi
[ -n "${MENDER_USER:-}" ] && [ -n "${MENDER_PASS:-}" ] || {
    echo "MENDER_USER / MENDER_PASS not set and not in $LAB/lab-backend.env" >&2; exit 1; }

# ---- 0. board uplink ---------------------------------------------------------
step "board uplink"
nmcli -t -f NAME,DEVICE con show --active | grep -qx 'board-share:eno1' \
    && ok "PC shares its WiFi to the board (board-share on eno1)" \
    || bad "board-share not active on eno1, board has no network (fix: sudo nmcli con up board-share)"
$SSH true 2>/dev/null && ok "board reachable ($BOARD)" \
    || { bad "cannot ssh $BOARD; nothing changed (see demo/RUNBOOK.md 'Board unreachable')"; exit 1; }

# ---- 1. stop backend, clear leftovers ---------------------------------------
step "stop lab-backend"
sudo systemctl stop lab-backend   # unit: ~/mender/lab-backend/lab-backend.service
pkill -f "$PATTERN" || true       # a stray hand-started one would hold :8000
for _ in $(seq 1 20); do pgrep -f "$PATTERN" >/dev/null || break; sleep 0.5; done
pgrep -f "$PATTERN" >/dev/null && { pkill -9 -f "$PATTERN" || true; sleep 1; }  # stray stuck on open tabs
pgrep -f "$PATTERN" >/dev/null && bad "backend still running" || ok "stopped (queue wiped)"
N=$(find "$LAB/uploads" -name '*.rbf' 2>/dev/null | wc -l)
find "$LAB/uploads" -name '*.rbf' -delete 2>/dev/null || true
ok "removed $N stale uploaded .rbf"

# ---- 2. board -> default classifier -----------------------------------------
step "board -> $NAME"
JWT=$(curl -sf -u "$MENDER_USER:$MENDER_PASS" -X POST "$U/api/management/v1/useradm/auth/login") \
    || { bad "Mender login failed ($U)"; exit 1; }
H="Authorization: Bearer $JWT"
# Identity is the eth0 MAC; if it ever changes the board reappears as a new
# pending device and a deployment to $DEV just sits there.
ST=$(curl -sf -H "$H" "$U/api/management/v2/devauth/devices/$DEV" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo missing)
[ "$ST" = accepted ] || {
    bad "device $DEV is '$ST' on Mender; pending devices:"
    curl -sf -H "$H" "$U/api/management/v2/devauth/devices?status=pending" \
        | python3 -c 'import sys,json;[print("    ",d["id"],d["identity_data"],d["created_ts"]) for d in json.load(sys.stdin)]'
    echo "  accept the right one in the Mender UI, then DEVICE_ID=<id> $0"; exit 1; }
ID=$(curl -sf -D - -o /dev/null -H "$H" -H "Content-Type: application/json" \
    -d "{\"name\":\"$NAME\",\"artifact_name\":\"$NAME\",\"devices\":[\"$DEV\"]}" \
    "$U/api/management/v1/deployments/deployments" | tr -d '\r' | sed -n 's#^[Ll]ocation: .*/##p')
[ -n "$ID" ] || { bad "could not create deployment"; exit 1; }
echo "  deployment $ID"
T0=$(date +%s); LAST=
until [ "$(curl -sf -H "$H" "$U/api/management/v1/deployments/deployments/$ID" | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')" = finished ]; do
    [ $(( $(date +%s) - T0 )) -lt 900 ] || { bad "deployment timeout after 900 s"; exit 1; }
    S=$(curl -sf -H "$H" "$U/api/management/v1/deployments/deployments/$ID/devices" \
        | python3 -c 'import sys,json;print(next((d["status"] for d in json.load(sys.stdin)), "?"))' 2>/dev/null || echo "?")
    [ "$S" = "$LAST" ] || { printf '  board: %s (%ss)\n' "$S" $(( $(date +%s) - T0 )); LAST=$S; }
    sleep 3
done
STATS=$(curl -sf -H "$H" "$U/api/management/v1/deployments/deployments/$ID/statistics")
if echo "$STATS" | grep -q '"failure":0' && echo "$STATS" | grep -qE '"(success|already-installed)":1'; then
    ok "finished in $(( $(date +%s) - T0 ))s: $STATS"
else
    bad "deployment did not succeed: $STATS"
fi

# ---- 3. board health ---------------------------------------------------------
step "board health ($BOARD)"
if OUT=$($SSH "cat /var/lib/dla/model/name; systemctl is-active $UNITS" 2>&1); then
    LIVE=$(echo "$OUT" | sed -n 1p)
    [ "$LIVE" = "$(echo "$NAME" | sed 's/^coredla-model-//; s/-v[0-9]*-[0-9a-f]*$//; s/-[0-9a-f]*$//')" ] \
        && ok "model on board: $LIVE" || bad "model on board is '$LIVE'"
    i=2
    for unit in $UNITS; do
        st=$(echo "$OUT" | sed -n ${i}p); i=$((i + 1))
        if [ "$st" = active ]; then ok "$unit active"; continue; fi
        if [ -n "${BOARD_SUDO_PASS:-}" ]; then
            $SSH "echo '$BOARD_SUDO_PASS' | sudo -S -p '' systemctl restart $unit" 2>/dev/null || true
            sleep 3
            st=$($SSH "systemctl is-active $unit" 2>/dev/null || echo unknown)
            [ "$st" = active ] && ok "$unit restarted" || bad "$unit $st after restart"
        else
            bad "$unit $st  (fix: ssh $BOARD 'sudo systemctl restart $unit', or set BOARD_SUDO_PASS)"
        fi
    done
else
    bad "ssh failed: $OUT"
fi
CODE=$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$STREAM" || true)
[ "$CODE" = 200 ] && ok "camera stream $STREAM" || bad "camera stream $STREAM -> HTTP ${CODE:-none}"

# ---- 4. start backend, verify -----------------------------------------------
step "start lab-backend"
# SESSION_SECONDS reaches the unit through the manager environment (unset = default).
if [ -n "${SESSION_SECONDS:-}" ]; then sudo systemctl set-environment SESSION_SECONDS="$SESSION_SECONDS"
else sudo systemctl unset-environment SESSION_SECONDS; fi
sudo systemctl start lab-backend
for _ in $(seq 1 30); do curl -sf -o /dev/null http://localhost:8000/config && break; sleep 0.5; done
curl -sf -o /dev/null http://localhost:8000/config && ok "up (pid $(pgrep -n -f "$PATTERN"))" \
    || { bad "backend not answering on :8000, see $LAB/uvicorn.log"; exit 1; }
CAT=$(curl -sf http://localhost:8000/session/models) && ok "catalog $CAT" || bad "/session/models failed"
if M=$(curl -sf http://localhost:8000/session/model); then
    ok "board answers: $(echo "$M" | python3 -c 'import sys,json;m=json.load(sys.stdin);print(m["name"], len(m["categories"]), "classes")')"
else
    bad "/session/model failed: board classifier not answering over ssh"
fi
[ -z "${SESSION_SECONDS:-}" ] || ok "session length $SESSION_SECONDS s"

echo
if [ "$FAIL" = 0 ]; then
    echo "READY. Open http://localhost:8000 and click Join queue (an old tab shows 'Session lost' - that is expected, join again)."
else
    echo "NOT READY: fix the FAIL lines above and rerun." >&2
    exit 1
fi
