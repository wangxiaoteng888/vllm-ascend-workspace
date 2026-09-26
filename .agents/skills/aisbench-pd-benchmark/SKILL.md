---
name: aisbench-pd-benchmark
description: Prepare and run AISBench performance cases for vLLM Ascend services and two-node PD proxy deployments, including tokenizer-based normal or repeated-prefix dataset construction, warmup and formal runs, exact concurrency/request-count semantics, and result capture. Use when the user explicitly requests aisbench, ais_bench, or aisbench_auto_tools_prefix. Do not use for vllm bench or profiler collection.
---

# AISBench PD Benchmark

Build a reproducible AISBench run without modifying the shared tool checkout.
For PD separation, send requests through the official PD proxy unless the user
explicitly requests a direct-D mixed/prefill+decode experiment.

## Workflow

1. Read [references/aisbench-workflow.md](references/aisbench-workflow.md) and
   resolve the service topology, model, cache settings, workload, and lifecycle.
2. Copy and configure an isolated run with `scripts/prepare_run.py`.
3. Start and verify P, D, and `load_balance_proxy_server_example.py` when this is
   a PD experiment. Set AISBench `HOST_IP` and `HOST_PORT` to the proxy.
4. Run warmup and formal measurements with `scripts/run_case.sh`.
5. Verify return codes, completed request count, token lengths, and failures.
6. Preserve the commands, console output, AISBench output tree, service logs,
   and effective configuration.

## Invariants

- Concurrency and dataset size are independent. "1 concurrency, 4 data" means
  `--concurrency 1 --data_num 4`, so four requests run sequentially.
- `DATASET_TYPE=normal` and `REPEAT_RATE=0` are the ordinary no-prefix-hit case.
- Repeated-prefix data does not enable server prefix caching. Record P and D
  cache flags independently from the dataset repetition setting.
- A PD result targets the proxy. Direct D traffic is labelled mixed-step and is
  never reported as PD-separated performance.
- Use one isolated run directory per configuration and version. Never patch the
  shared `aisbench_auto_tools_prefix` checkout in place.
- Do not run two cases concurrently against the same AISBench `WORK_PATH`; the
  wrapper updates a shared model-config symlink inside that installation.
- A warmup is not a formal result. Keep separate logs and return codes.
- `request_rate=0` means submit as fast as the configured concurrency permits;
  it does not mean zero requests.
- Never write host passwords or API keys into a skill, command log, or result
  directory. Use the managed credential mechanism already available.
- Do not stop services after the test when the user asks to leave them running.

## Handoff

Report the run directory, exact formal command, target endpoint and whether it
was proxy or direct, service/cache/recompute/task-queue/MTP settings, completed
and failed request counts, and the key throughput/latency fields with their
units. Link or identify the formal console log and AISBench result files.
