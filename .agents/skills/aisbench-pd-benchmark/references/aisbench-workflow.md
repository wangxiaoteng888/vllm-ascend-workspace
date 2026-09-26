# AISBench dataset and PD benchmark workflow

This workflow targets `rayn-zzz/aisbench_auto_tools_prefix`, which wraps
AISBench and builds tokenizer-based fixed-length or repeated-prefix datasets.

## 1. Resolve and label the experiment

Before changing services, record:

- container/version and model path;
- P and D host roles and the official proxy endpoint;
- P and D TP/DP layout, MTP, recompute scheduler, and task-queue setting;
- P prefix-cache state and D prefix-cache state independently;
- input length, output length, concurrency, request count, request rate, and
  stream/text mode;
- normal or prefix-cache dataset, repeat ratio, prefix count, DP size, and seed;
- number of warmup and formal rounds;
- whether services should remain running.

Do not store passwords in the run directory. Never infer host roles or ports
from an earlier experiment.

## 2. Obtain the tool only when it is absent

Repository:

```text
https://github.com/rayn-zzz/aisbench_auto_tools_prefix
```

If the environment requires the user's download proxy, set it only for the
download/build shell:

```bash
export CCW_HOST_IP=<proxy-host>
export http_proxy="http://${CCW_HOST_IP}:3128"
export https_proxy="${http_proxy}"
export ftp_proxy="${http_proxy}"
export GIT_SSL_NO_VERIFY=true
git clone https://github.com/rayn-zzz/aisbench_auto_tools_prefix.git
```

Unset those variables after installation if normal service traffic should not
use the proxy. Prefer the already installed checkout and package when present.
Find AISBench's Python work path with:

```bash
pip show ais-bench-benchmark
```

Use its `Location` value as `--work-path`.

## 3. Create an isolated run directory

Run the helper on the machine/container where AISBench will execute:

```bash
python3 scripts/prepare_run.py \
  --tool-dir <aisbench_auto_tools_prefix-checkout> \
  --run-dir <run>/aisbench \
  --model-name <served-model-name> \
  --model-path <tokenizer/model-path> \
  --host-ip <proxy-host> \
  --host-port <proxy-port> \
  --work-path <aisbench-python-location> \
  --pod-info <P-host:P-metrics-port> \
  --pod-info <D-host:D-metrics-port>
```

The helper copies the checkout's top-level Python files, creates `datasets/`
and `outputs/`, patches only the copied `config.py`, and writes
`run_config.json`. It deliberately refuses to reuse a non-empty directory
unless `--overwrite` is supplied.

The upstream wrapper still updates a model-config symlink under `WORK_PATH`.
Serialize cases that share one AISBench installation; concurrent cases can
overwrite each other's endpoint/concurrency configuration.

For a PD test, `HOST_IP` and `HOST_PORT` must point to
`load_balance_proxy_server_example.py`. A direct-D endpoint measures a
mixed/prefill+decode path and must be named and reported as such.

## 4. Construct and run a normal 2K/2K case

The wrapper generates the dataset using the tokenizer at `MODEL_PATH`. For one
concurrent request and four total requests with no deliberate prefix reuse:

```bash
cd <run>/aisbench
INPUT_LEN=2048 \
OUTPUT_LEN=2048 \
DATA_NUM=4 \
CONCURRENCY=1 \
REQUEST_RATE=0 \
DATASET_TYPE=normal \
REPEAT_RATE=0 \
WARMUP=1 \
bash <skill>/scripts/run_case.sh
```

This produces one warmup request followed by four sequential formal requests.
For other common cases, change both independent values explicitly:

```text
4 concurrency, 16 data  -> CONCURRENCY=4  DATA_NUM=16
16 concurrency, 64 data -> CONCURRENCY=16 DATA_NUM=64
2K input, 1 output      -> INPUT_LEN=2048 OUTPUT_LEN=1
```

`REQUEST_RATE=0` tells the wrapper to drive requests as fast as concurrency
allows. `OUTPUT_LEN` is a generation limit; the wrapper normally configures
`ignore_eos=True`, but verify the formal details show the intended output token
count before accepting the result.

## 5. Construct and run a 100% repeated-prefix case

Dataset repetition and server prefix caching are separate controls. First
launch the requested P/D cache configuration, then run:

```bash
cd <run>/aisbench
INPUT_LEN=2048 \
OUTPUT_LEN=2048 \
DATA_NUM=4 \
CONCURRENCY=1 \
DATASET_TYPE=prefix_cache \
REPEAT_RATE=1.0 \
PREFIX_NUM=1 \
DP_SIZE=1 \
SEED=1 \
WARMUP=1 \
PREFIX_TEST=0 \
bash <skill>/scripts/run_case.sh
```

The separate warmup is regenerated with the same seed and prefix settings so
the formal requests can hit the warmed prefix. `PREFIX_TEST=1` additionally
asks the wrapper to run its built-in prefix pre-test and calculate hit-rate
metrics; do not enable it accidentally when comparing a single warmup protocol.
When DP is greater than one, set `DP_SIZE` and `POD_INFO` correctly so the
prefix generator and hit-rate reporting match the deployment.

## 6. Capture evidence while AISBench runs

Before warmup, snapshot:

- P, D, and proxy processes and effective launch commands;
- relevant environment variables, including `TASK_QUEUE_ENABLE`;
- service health and model endpoint;
- prefix-cache/recompute/MTP settings from the actual logs.

Capture P, D, and proxy terminal output continuously through formal completion.
Use separate incremental logs when the service logs already contain older
runs. Preserve:

```text
warmup_command.txt
warmup_console.log
warmup_return_code.txt
formal_command.txt
formal_console.log
formal_return_code.txt
aisbench.log
aisbench_all.log
aisbench_result.csv
datasets/
outputs/
run_config.json
```

AISBench usually writes detailed result files below `outputs/performances/`.
Locate the newest formal output rather than assuming a fixed timestamped name.

## 7. Acceptance checks and reporting

Accept a formal result only when:

- `formal_return_code.txt` is `0`;
- the console/result details show the requested number of completed samples;
- no failed requests or malformed responses are hidden in the summary;
- prompt/output token counts match the requested case closely enough for the
  tool's tokenization behavior;
- the target is confirmed as the proxy for a PD-separated result;
- the service configuration matches the experiment label.

Report output-token throughput separately from request throughput, and include
the exact units printed by AISBench. Also report latency/TTFT/TPOT fields that
the result provides; do not compare a token/s field against requests/s or a
direct-D mixed result against a PD-proxy result.
