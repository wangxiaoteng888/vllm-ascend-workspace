---
name: vllm-host-memory-leak
description: "定位 vLLM/Ascend EngineCore 或 Worker 的主机内存持续增长、疑似泄漏和 ZMQ 通知积压。提供 USS/PSS/RSS 与 smem 监控、被动队列计数、BCC memleak 验证和采集、原生分配栈归因及对照实验流程。适用于进程 RAM 问题；NPU HBM/OOM 使用 ascend-memory-profiling。"
---

# vLLM 主机内存泄漏定位

目标是形成可复核的证据链：**哪个进程在何种负载下增长 → 哪条分配路径未释放 → 对应数据结构为何滞留 → 有针对性的修复是否消除增长且不破坏业务**。不能从 USS 曲线或一条栈直接宣布根因。

## 最短路径

1. **确认对象和时间**：读主机时间、服务健康、负载完成/失败/在途数、监控文件最新样本。运行 `scripts/inspect_target.py`，记录 PID、start_ticks、boot_id、NSpid、镜像 digest、包版本与实际映射库 SHA256。远程操作使用本工作区 `.remote-dev` 工具；命令在目标 Linux 环境执行。
2. **建立连续内存记录**：优先 `scripts/memory_watch.py`（每 60 秒），需要与本次实验保持一致时再挂独立的 `scripts/smem/mem_monitor.sh`。不重启已有服务。先验证首个样本，再在至少一个采样间隔后验证文件继续增长。
3. **画图并分类**：运行 `scripts/plot_memory.py`。同一进程生命周期看全程、负载后和近 30/60 分钟 USS；PSS/RSS 辅助。标明启动、换轮、空闲、图捕获、重启及数据缺口。采样过期先排查，不能用 `--historical` 冒充最新图。
4. **选定位分支**：Python 对象增长考虑受控复现中的 tracemalloc/Memray；原生堆增长用 BCC；共享页或文件映射增长检查 smaps；不要先假定 ZMQ。详见 [定位与监控](references/workflow.md)。
5. **BCC 先验证再采集**：读 [BCC 操作手册](references/bcc.md)。在隔离小进程验证 malloc 和 free 都能跟踪，再对真实 PID 做约 10 分钟有界采集。BCC 不重启目标，但有 CPU、内存和 uprobe 开销，记录采集前后负载。
6. **ZMQ 专项**：只有调用链涉及该通知路径时，读 [ZMQ 专项](references/zmq.md)。统计每个队列的共享内存读取、忙等、poll 和 recv；诊断线程绝不读取 socket 的 EVENTS。补丁默认只预览，应用需要匹配源码哈希。已有运行进程不会因修改 .py 文件自动获得计数。
7. **归因和交付**：记录已证实、源码支持的机制、仍缺的测量。数据结构级证明需对象地址/命令类型/入出队或存活块关联；修复验证保持相同工作负载。附上可运行命令、manifest、原始数据、时间窗和代码位置。

## 重要边界

- `USS ↑` 不等于泄漏；BCC outstanding 不等于永不释放；分配栈聚合不等于单个 socket。两次独立 BCC 采集不共享历史账本。
- 无 `poll/recv` 可以说明这个 Python 路径未被调用，不能单凭它计算 `_cpipe` 元素或字节；send 减 recv 也不是命令队列深度。
- socket 的 `poll` 可以执行内部命令，`recv` 取通知消息；两者都不是手工丢弃命令。释放给 malloc 分配器不保证 USS 立即下降。
- 读共享内存结果与处理通知是两条路径。进入 `wait()` 仍可能处于忙等；不能把 `wait_calls` 当成 `poll_calls`。
- 不为了证明泄漏而清空命令队列、调用 malloc_trim、给正在运行的普通 ZMQ socket 添加跨线程操作，或偷偷切换 eager/graph、PP、模型、KV 精度、并发。
- 脚本、报告不保存密码或代理凭据。安装工具使用用户指定代理，仅在需要安装的命令环境里设置；不默认关闭 TLS 校验。

## 资源入口

- [references/workflow.md](references/workflow.md)：PID/容器映射、监控、画图、数据过期恢复、实验控制、下一层工具。
- [references/bcc.md](references/bcc.md)：安装检查、原生 memleak 调用、受控验证、采集、符号化、比较限制。
- [references/zmq.md](references/zmq.md)：被动打印安装/恢复、指标语义、源码证据与精确队列验证方案。
- [references/case-notes.md](references/case-notes.md)：本次实验沉淀的故障与证据边界，不当作新现场结论。
- [references/validation.md](references/validation.md)：此版本脚本的实际验证范围与未验证项。

脚本不包含固定主机、模型路径、PID、端口或 libzmq 偏移；每个脚本支持 `--help`（smem 的 shell 包装器见操作手册）。Python 监控只依赖标准库；画图额外需要 matplotlib；BCC 使用能 `import bcc` 的系统 Python。

## License and offline checks

Keep the complete package, [MIT license](LICENSE), [attribution notice](NOTICE),
and [smem GPL license](scripts/smem/COPYING). The bundled smem retains
GPL-2.0-or-later; the workspace MIT license does not replace its terms.

Run host-only helper checks from the workspace root:

```bash
python3 -m unittest discover -s .agents/skills/vllm-host-memory-leak/tests -v
```

These tests use synthetic data and temporary files. Linux process inspection,
BCC attachment, and service workload validation still require the target
environment described in the workflow.
