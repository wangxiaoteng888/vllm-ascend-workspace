# 主机内存增长：现场流程

## 1. 先建立身份，不先猜根因

记录：机器/容器名与镜像 digest、模型、vLLM/Ascend/Python/pyzmq/libzmq 版本、PP/TP/DP、图模式、KV 配置、服务启动时间、负载开始与换轮时间。身份至少是 host + boot_id + PID + start_ticks，不能只认 PID。

Linux 命令例（`$KIT` 是已上传的 skill 目录，`$RUN` 是本次新建证据目录）：

```bash
date -Ins
python3 "$KIT/scripts/inspect_target.py" --match 'VLLM::EngineCore' --output "$RUN/targets.json"
docker inspect --format '{{.Image}} {{.State.Pid}}' "$CONTAINER"
docker top "$CONTAINER" -eo pid,ppid,comm,args
```

从宿主机观察容器进程时，用宿主机 PID；从容器 `/proc` 观察时用该命名空间 PID。`/proc/HOST_PID/status` 的 `NSpid` 和 start_ticks 可交叉核对。BCC 能看到目标 `/proc` 不代表具备内核跟踪权限或用户库符号解析条件。

`inspect_target.py` 保存目标已映射 libzmq 的哈希，读取 `/proc/PID/root/...` 可穿过目标 mount namespace。若文件已删除、无法读取或库后来发生替换，应记录不确定性；版本字符串不能证明二进制与某个源码 tag 完全一致。

在服务使用的解释器里查版本，而不是宿主机默认 Python：

```bash
python3 -c 'import zmq; print(zmq.__version__, zmq.zmq_version(), zmq.__file__)'
```

远程执行遵循工作区 `.remote-dev/tools/remote_bash.py`、`remote_write.py`、`remote_read.py` 等接口。Windows 用 `py -3`；不要拼接密码或借 JSON 序列化当 shell 转义。复杂命令上传脚本执行。此次旧 wrapper 出现过 CRLF `set` 告警，应同时检查实际退出码、stderr 和输出完整性，不能忽略真实错误。

## 2. 启动持续监控

只读检查和挂指定进程监控通常在诊断授权内；记录资源开销，不停止无关服务。

```bash
ulimit -n 65536
python3 "$KIT/scripts/memory_watch.py" --pid "$PID" \
  --output "$RUN/memory" --label 'P / PP2' --interval 60 --background
```

想追踪所有新启动的 EngineCore 时用 `--match 'VLLM::EngineCore'` 替代 `--pid`。固定 PID 模式遇到 PID 复用会拒绝拼接生命周期；match 模式按每条记录保存的 start_ticks 分图。可重复 `--pid` 监控多个目标。

检查 `memory/status.json` 中的 `sample_at`、`matched`、`errors`，以及 `memory.jsonl` 是否持续追加；`status=running` 的旧文件不能证明当前仍在运行。停止只给 monitor.json 记录且身份匹配的观察进程发 SIGTERM。恢复用同一参数加 `--resume`；文件锁防同一目录双写。

独立 smem 路径（附带用户提供的版本，保留 GPL 头和许可证）：

```bash
SMEM_LOG_DIR="$RUN/smem" SMEM_INTERVAL=60 PYTHON=python3 \
  nohup bash "$KIT/scripts/smem/mem_monitor.sh" > "$RUN/smem-launch.log" 2>&1 < /dev/null &
```

smem 包装器限制为 4 个扫描进程，单次默认 timeout 180 秒；一次失败会记录错误而不是伪造零值。它扫描可见进程，开销高于只采指定 PID。时间戳在每批扫描开始时记录，实际每行有扫描延迟；采样间隔是扫描耗时加 sleep。`flock`、`timeout` 来自 util-linux/coreutils。

新 memory_watch 不把 HTTP metrics 放在采样循环中。服务健康和负载状态单独保存，避免一次 HTTP 协议异常终止内存采样。

## 3. 画图与增长速率

```bash
python3 "$KIT/scripts/plot_memory.py" --input "$RUN/memory/memory.jsonl" \
  --pid "$PID" --output "$RUN/plots/p-latest-001" --label 'P EngineCore USS' \
  --load-start '2026-10-22T08:00:00+08:00'
```

根据真实时间修改 load-start；不能沿用例子的日期。matplotlib 可在本地分析环境安装，无需给服务环境安装。Windows 如需中文标题，用 `--font C:/Windows/Fonts/msyh.ttc`。输出 PNG、CSV、JSON，前缀必须未使用，保留历史图。

```bash
python3 "$KIT/scripts/plot_memory.py" --input "$RUN/smem/HOST_TIMESTAMP.log" \
  --format smem --pid "$PID" --output "$RUN/plots/p-smem-001"
```

- 默认最新样本超过 180 秒会失败；检查主机时钟/监控/服务/负载，不直接加 `--historical`。
- 离线历史分析可显式加 `--historical`，标题会标记历史。跨主机时钟偏差不能默默修正；记录偏差和对齐方式。
- 同 PID 不同 start_ticks 拒绝合并。smem 没有 start_ticks，必须从服务日志/身份记录验证未重启；输入只包含同一主机的记录。
- 超过 180 秒的数据缺口不连线；恢复监控不得插值冒充实测。另一独立 smem 有数据时单独出图并标来源。
- USS 是主要观察指标；PSS 分摊共享页，RSS 含共享页，均不是 HBM。近 30/60 分钟采用实际采样端点净变化，不能当稳定泄漏率或外推全天；采样缺口、突跳、回落、工作负载变化都要注明。

## 4. 分类后选工具

- Python 活对象：受控复现中使用 tracemalloc 快照差值或 Memray。tracemalloc 无法回溯未启用前的分配，也不能覆盖所有 C/C++ malloc。
- 原生 malloc/free：BCC memleak 先做隔离验证，再短窗口真实采集；见 [bcc.md](bcc.md)。
- 文件页/共享映射：比较 smaps 的 Private/Shared、Anon/File/Shmem 和映射数；不要把 RSS 共享页误归因给 ZMQ。
- 线程/队列/句柄：记录线程数、FD 数、请求数与对象生命周期。排查请求完成后是否仍被容器/引用持有。
- 分配器保留/碎片：应用活对象下降但 USS 不降并不矛盾；不用强制 trim 后下降来宣布修复。需要在受控实验中区分 allocator retention 和活分配。

## 5. 实验控制与交付

保持镜像、补丁、模型、并行、图模式、输入 token 分布、输出、并发、前缀复用和业务成功率相同。AISBench `while true` 在换轮时可能重新生成/加载数据而暂停请求；这种间隙可能让通知进入 poll，必须标记。若需要不间断负载，应预加载数据并持续补足指定并发，记录在途数量，而不是仅检查压测进程存在。

现场结论格式：

1. 观测时间与数据新鲜度；服务、负载是否活跃；同一进程身份。
2. USS/PSS/RSS 的实际窗口变化、峰值、回落与负载阶段。
3. BCC 覆盖与验证、目标分配路径、未释放块变化；缺失栈/截断/错误。
4. 源码版本、精确位置、对象类型，以及运行时证据能否对应具体实例。
5. 已确认结论、尚未证实的假设、下一项能区分假设的测量。

交付原始数据、采集命令、镜像/库哈希、补丁 diff、图与统计脚本。不要把某次环境偶然得到的地址或偏移写成下一次默认值。
