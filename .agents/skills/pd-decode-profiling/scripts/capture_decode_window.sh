#!/usr/bin/env bash
set -euo pipefail

: "${D_URL:?Set D_URL, for example http://decoder-host:9123}"
: "${RUN_DIR:?Set RUN_DIR to the run directory visible inside the container}"

PROFILE_SECONDS="${PROFILE_SECONDS:-5}"
DECODE_WAIT_SECONDS="${DECODE_WAIT_SECONDS:-900}"
CONTROL_DIR="${CONTROL_DIR:-${RUN_DIR}/profile_control}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METRICS_DELTA_SCRIPT="${METRICS_DELTA_SCRIPT:-${SCRIPT_DIR}/metrics_delta.py}"

mkdir -p "$CONTROL_DIR"

metric_total() {
    curl -fsS --max-time 30 "${D_URL}/metrics" \
        | awk '/^vllm:generation_tokens_total/ {sum += $NF} END {printf "%.0f\n", sum + 0}'
}

profile_started=0
profile_stopped=0

stop_profile_on_exit() {
    if [[ "$profile_started" -eq 1 && "$profile_stopped" -eq 0 ]]; then
        curl -sS --max-time 1800 -X POST "${D_URL}/stop_profile" \
            >"${CONTROL_DIR}/stop_profile_cleanup_body.json" || true
    fi
}
trap stop_profile_on_exit EXIT

date -Ins >"${CONTROL_DIR}/wait_decode_begin.txt"
previous="$(metric_total)"
decode_seen=0
for ((second = 1; second <= DECODE_WAIT_SECONDS; second++)); do
    sleep 1
    current="$(metric_total)"
    if (( current > previous )); then
        decode_seen=1
        {
            printf 'previous=%s current=%s\n' "$previous" "$current"
            date -Ins
        } >"${CONTROL_DIR}/decode_detected.txt"
        break
    fi
    previous="$current"
done
[[ "$decode_seen" -eq 1 ]] || exit 10

date -Ins >"${CONTROL_DIR}/start_profile_begin.txt"
start_code="$(curl -sS --max-time 1200 -X POST \
    -o "${CONTROL_DIR}/start_profile_body.json" -w '%{http_code}' "${D_URL}/start_profile")"
printf '%s\n' "$start_code" >"${CONTROL_DIR}/start_profile_http.txt"
date -Ins >"${CONTROL_DIR}/start_profile_end.txt"
[[ "$start_code" == "200" ]] || exit 11
profile_started=1

curl -fsS --max-time 30 "${D_URL}/metrics" >"${CONTROL_DIR}/D_metrics_before_window.prom"
date -Ins >"${CONTROL_DIR}/window_begin.txt"
sleep "$PROFILE_SECONDS"
date -Ins >"${CONTROL_DIR}/window_end.txt"
curl -fsS --max-time 30 "${D_URL}/metrics" >"${CONTROL_DIR}/D_metrics_after_window.prom"

set +e
python3 "$METRICS_DELTA_SCRIPT" \
    "${CONTROL_DIR}/D_metrics_before_window.prom" \
    "${CONTROL_DIR}/D_metrics_after_window.prom" \
    "${CONTROL_DIR}/D_decode_window_delta.json" \
    >"${CONTROL_DIR}/metrics_delta_console.json"
decode_rc=$?
set -e

date -Ins >"${CONTROL_DIR}/stop_profile_begin.txt"
stop_code="$(curl -sS --max-time 1800 -X POST \
    -o "${CONTROL_DIR}/stop_profile_body.json" -w '%{http_code}' "${D_URL}/stop_profile")"
printf '%s\n' "$stop_code" >"${CONTROL_DIR}/stop_profile_http.txt"
date -Ins >"${CONTROL_DIR}/stop_profile_end.txt"
[[ "$stop_code" == "200" ]] || exit 12
profile_stopped=1
trap - EXIT

[[ "$decode_rc" -eq 0 ]] || exit 13

python3 - "$CONTROL_DIR" "$PROFILE_SECONDS" <<'PY'
import json
import sys
from pathlib import Path

control_dir = Path(sys.argv[1])
delta = json.loads((control_dir / "D_decode_window_delta.json").read_text())
print(json.dumps({
    "status": "ok",
    "control_dir": str(control_dir),
    "profile_seconds": float(sys.argv[2]),
    "total_decode_tokens": delta["total_delta"],
    "active_engines": delta["active_engines"],
    "metrics_before": str(control_dir / "D_metrics_before_window.prom"),
    "metrics_after": str(control_dir / "D_metrics_after_window.prom"),
    "delta_file": str(control_dir / "D_decode_window_delta.json"),
}, separators=(",", ":")))
PY
