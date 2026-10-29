#!/usr/bin/env bash
# Companion to the user's smem: keep an independent monitor if another sampler fails.
set -u
cd -- "$(dirname -- "$(readlink -f -- "$0")")" || exit 1
ulimit -n 65536 || exit 1
logdir="${SMEM_LOG_DIR:?Set SMEM_LOG_DIR to a new or existing monitor output directory}"
mkdir -p -- "$logdir" || exit 1
exec 9>"$logdir/smem.lock"
flock -n 9 || exit 1
export TZ="${TZ:-Asia/Shanghai}"
logfile="$logdir/$(hostname)_$(date '+%Y%m%d_%H%M%S').log"
printf '%s\n' "$$" > "$logdir/monitor.pid"
printf 'smem log=%s scanner_processes=4\n' "$logfile"
while true; do
    {
        date '+%Y-%m-%d %H:%M:%S %z'
        ps -ef
        printf '%s\n' '----------------------'
        free -m
        printf '%s\n' '----------------------'
        if ! timeout "${SMEM_TIMEOUT:-180}" "${PYTHON:-python3}" ./run_smem.py; then
            printf '%s\n' 'SMEM_SAMPLE_FAILED: inspect errors; no zero-memory sample inferred'
        fi
        printf '%s\n' '======================'
    } 2>&1 | tee -a "$logfile"
    sleep "${SMEM_INTERVAL:-60}"
done
