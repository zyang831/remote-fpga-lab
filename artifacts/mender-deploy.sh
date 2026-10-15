#!/bin/bash
# Upload a prebuilt .mender artifact (skipped if the server already has one of
# that name), deploy it to the coredla board and wait. Same API calls as
# lab-backend/mender_client.py. MENDER_USER/MENDER_PASS from the environment.
#   ./mender-deploy.sh file.mender
set -eu
U=${MENDER_URL:-https://mender.example.ts.net}
DEV=${DEVICE_ID:-56bc13f6-c33d-4637-8f25-c4eb03605b40}
FILE=$1
NAME=$(mender-artifact read "$FILE" | sed -n 's/^ *Name: //p' | head -1)
[ -n "$NAME" ] || { echo "cannot read artifact name from $FILE" >&2; exit 1; }

JWT=$(curl -sf -u "$MENDER_USER:$MENDER_PASS" -X POST "$U/api/management/v1/useradm/auth/login")
H="Authorization: Bearer $JWT"
if [ "$(curl -sf -H "$H" "$U/api/management/v1/deployments/artifacts?name=$NAME" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')" = 0 ]; then
    curl -sf -o /dev/null -H "$H" -F "artifact=@$FILE" "$U/api/management/v1/deployments/artifacts"
    echo "uploaded $NAME"
fi
ID=$(curl -sf -D - -o /dev/null -H "$H" -H "Content-Type: application/json" \
    -d "{\"name\":\"$NAME\",\"artifact_name\":\"$NAME\",\"devices\":[\"$DEV\"]}" \
    "$U/api/management/v1/deployments/deployments" | tr -d '\r' | sed -n 's#^[Ll]ocation: .*/##p')
echo "artifact $NAME  deployment $ID"

T0=$(date +%s)
until [ "$(curl -sf -H "$H" "$U/api/management/v1/deployments/deployments/$ID" | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')" = finished ]; do
    [ $(( $(date +%s) - T0 )) -lt 900 ] || { echo "timeout" >&2; exit 1; }
    sleep 3
done
STATS=$(curl -sf -H "$H" "$U/api/management/v1/deployments/deployments/$ID/statistics")
echo "finished in $(( $(date +%s) - T0 ))s: $STATS"
echo "$STATS" | grep -q '"failure":0' && echo "$STATS" | grep -qE '"(success|already-installed)":1'
