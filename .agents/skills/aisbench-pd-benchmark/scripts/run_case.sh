#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${RUN_DIR:-$PWD}"
INPUT_LEN="${INPUT_LEN:-2048}"
OUTPUT_LEN="${OUTPUT_LEN:-2048}"
DATA_NUM="${DATA_NUM:-4}"
CONCURRENCY="${CONCURRENCY:-1}"
REQUEST_RATE="${REQUEST_RATE:-0}"
TEST_TYPE="${TEST_TYPE:-stream}"
REPEAT="${REPEAT:-1}"
NPU_NUM="${NPU_NUM:-32}"
DATASET_TYPE="${DATASET_TYPE:-normal}"
REPEAT_RATE="${REPEAT_RATE:-0}"
PREFIX_NUM="${PREFIX_NUM:-1}"
DP_SIZE="${DP_SIZE:-1}"
SEED="${SEED:-1}"
WARMUP="${WARMUP:-1}"
WARMUP_DATA_NUM="${WARMUP_DATA_NUM:-1}"
PREFIX_TEST="${PREFIX_TEST:-0}"
DATASET_FILE="${DATASET_FILE:-}"

cd "${RUN_DIR}"
if [[ ! -f aisbench_test.py || ! -f config.py ]]; then
  echo "RUN_DIR is not an AISBench run prepared by prepare_run.py: ${RUN_DIR}" >&2
  exit 2
fi

common_args=(
  --input_len "${INPUT_LEN}"
  --output_len "${OUTPUT_LEN}"
  --concurrency "${CONCURRENCY}"
  --request_rate "${REQUEST_RATE}"
  --test_type "${TEST_TYPE}"
  --repeat "${REPEAT}"
  --npu_num "${NPU_NUM}"
  --dataset_type "${DATASET_TYPE}"
  --repeat_rate "${REPEAT_RATE}"
  --prefix_num "${PREFIX_NUM}"
  --dp "${DP_SIZE}"
  --seed "${SEED}"
)

run_one() {
  local label="$1"
  local count="$2"
  local use_dataset="$3"
  local use_prefix_test="$4"
  local args=("${common_args[@]}" --data_num "${count}")
  if [[ -n "${use_dataset}" ]]; then
    args+=(--dataset "${use_dataset}")
  fi
  if [[ "${use_prefix_test}" == "1" ]]; then
    args+=(--prefix_test)
  fi

  {
    printf '%q ' python3 aisbench_test.py "${args[@]}"
    printf '\n'
  } > "${label}_command.txt"

  set +e
  python3 aisbench_test.py "${args[@]}" 2>&1 | tee "${label}_console.log" >&2
  LAST_RC="${PIPESTATUS[0]}"
  set -e
  printf '%s\n' "${LAST_RC}" > "${label}_return_code.txt"
}

LAST_RC=0
warmup_rc=0
if [[ "${WARMUP}" == "1" ]]; then
  # Regenerate from the same seed so a prefix-cache warmup uses the same prefix.
  run_one warmup "${WARMUP_DATA_NUM}" "" 0
  warmup_rc="${LAST_RC}"
  if [[ "${warmup_rc}" -ne 0 ]]; then
    python3 - "$RUN_DIR" "$warmup_rc" <<'PY'
import json, sys
print(json.dumps({
    "status": "warmup_failed",
    "run_dir": sys.argv[1],
    "warmup_return_code": int(sys.argv[2]),
    "warmup_console": f"{sys.argv[1]}/warmup_console.log",
}, separators=(",", ":")))
PY
    exit "${warmup_rc}"
  fi
fi

run_one formal "${DATA_NUM}" "${DATASET_FILE}" "${PREFIX_TEST}"
formal_rc="${LAST_RC}"
python3 - "$RUN_DIR" "$warmup_rc" "$formal_rc" <<'PY'
import json, sys
print(json.dumps({
    "status": "ok" if int(sys.argv[3]) == 0 else "formal_failed",
    "run_dir": sys.argv[1],
    "warmup_return_code": int(sys.argv[2]),
    "formal_return_code": int(sys.argv[3]),
    "formal_command": f"{sys.argv[1]}/formal_command.txt",
    "formal_console": f"{sys.argv[1]}/formal_console.log",
}, separators=(",", ":")))
PY
exit "${formal_rc}"
