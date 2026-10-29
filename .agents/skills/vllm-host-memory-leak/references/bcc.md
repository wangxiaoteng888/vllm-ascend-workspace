# BCC memleak：安装、验证、采集、归因

## 安装与前置检查

通常在宿主机使用与运行内核匹配的 BCC，目标 PID 也是宿主机 PID。也可在已具备权限和内核资源的诊断容器中运行，但不能只看到 PID 就宣称 tracing 可用。不自动给服务容器扩大权限。

```bash
uname -r
cat /etc/os-release
command -v memleak-bpfcc
/usr/bin/python3 -c 'import bcc; print(bcc.__file__)'
ls -ld /lib/modules/"$(uname -r)"/build /sys/kernel/btf/vmlinux
```

使用发行版匹配的软件源和内核开发包。Ubuntu 常见包为 `bpfcc-tools python3-bpfcc linux-headers-$(uname -r)`；openEuler/RHEL 系列先通过包管理器查询 `bcc`、Python bindings、`kernel-devel`/`kernel-headers` 的精确匹配版本再安装。内核不匹配、缺 BTF/headers、权限不足时先解决原因，不把“没有结果”当成“没有泄漏”。不自动升级内核或重启机器。

需要下载时按用户指定的代理设置 `http_proxy/https_proxy`，只用于这次安装；不固化本次实验代理地址、账号密码或 `GIT_SSL_NO_VERIFY=true`。安装前后记录包版本。BCC Python 要用能 import bcc 的解释器，通常是 `/usr/bin/python3`，不是 vLLM 的 Python。

## 原版调用是什么

先运行目标版本的 `--help`，确认参数语义：

```bash
/usr/bin/python3 /usr/sbin/memleak-bpfcc --help
/usr/bin/python3 -u /usr/sbin/memleak-bpfcc -p "$HOST_PID" -o 1000 -T 100 -s 1 30
```

这表示按指定 PID 跟踪用户态分配/释放，每 30 秒输出，忽略年龄不足 1000ms 的存活分配，最多显示 100 条栈，采样率为每次分配都跟踪。不要漏 `-p` 而意外进入内核分配模式。`-z/-Z` 是大小过滤，`-a` 输出分配地址（输出可能很大）；根据该版本源码确认。

工具是通过 uprobes 观察 allocator，**只知道挂载之后观察到的分配**。它不扫描整个历史堆，不暂停目标做完整 heap dump。挂载本身有开销，先小窗口确认吞吐和延迟影响。

## 必须先验证分配和释放都可见

```bash
/usr/bin/python3 "$KIT/scripts/bcc_validate.py" --output "$RUN/bcc-validation"
```

验证脚本只启动自己的测试进程：申请 1000 个 12347 字节块，释放 900 个，再释放剩余 100 个，检查报告按顺序出现 1000 → 100 → 0。先等观察器真正产生报告，再开始分配。验证不通过，不对现场发布“只有申请没有释放”的结论。

如果验证异常，排查：malloc/free 是否均成功挂载、权限、kernel headers、Python/native BCC ABI、符号解析、目标是否使用另一 allocator、stack map/map capacity、`stderr`。不要仅因工具名叫 memleak 就信任其结果。

### 本次遇到的特殊 ABI 问题

某个 BCC 0.29.1 环境的 Python binding 按 6 个参数调用 `bpf_attach_uprobe`，实际 native 函数接受含 `ref_ctr_offset` 的 7 个参数。仅在**已对当前 libbcc 头文件/符号/反汇编确认相同不匹配**时，才使用：

```bash
/usr/bin/python3 "$KIT/scripts/bcc_validate.py" --output "$RUN/bcc-validation-compat" \
  --verified-ref-counter-abi
```

`bcc_compat.py` 只在观察进程中补第七个参数 0，不修改系统包。不因为版本号相同或探针失败就自动启用；错误 ABI 调用可使观察器崩溃。原版验证通过时不使用兼容层。

## 有界采集

从 inspect_target 输出取当前 start_ticks，参数化执行：

```bash
/usr/bin/python3 "$KIT/scripts/bcc_capture.py" \
  --pid "$HOST_PID" --expected-start-ticks "$START_TICKS" \
  --seconds 640 --interval 30 --older-ms 1000 --top 100 --sample-rate 1 \
  --output "$RUN/bcc-01"
```

640 秒为默认 30 秒报告间隔预留了挂载时间；是否得到完整十分钟报告，以实际第一/最后报告为准。运行期间保持监控；需要后台执行用该工作区的远程任务能力或 nohup，并保存观察 PID。结束仅终止该脚本自己的 observer，不向 EngineCore 发信号。

可选：`--notify-file /.../notify-CONTAINER_PID-SESSION.jsonl`、`--load-status /.../status.json`。这些是辅助快照，不存在/格式异常会记录错误，不终止采集。宿主机和容器路径要按实际挂载映射。工作负载非本次连续压测器格式时，不强行假定 completed 字段含义。

产物：metadata.json（PID 身份、实际命令、库/工具哈希）、maps.start.txt、工具源码副本、stdout/stderr、每 5 秒目标内存与可选计数快照。结束状态 `finished-review-logs` 表示采集结束，不表示证实泄漏或观察器零错误。

## 分配栈与代码位置

```bash
python3 "$KIT/scripts/bcc_parse.py" --capture "$RUN/bcc-01" \
  --library libzmq --output "$RUN/bcc-01-summary.json"
```

统计名称是 `selected_printed_bytes/blocks`：只汇总被 top-N 打印出来的匹配栈。某条栈没出现可能只是跌出 top-N，不能填“实际占用为零”。全栈缺符号时也不能草率排除。

映射到文件偏移：`file_offset = runtime_address - mapping_start + mapping_file_offset`。再用 `readelf -lW` 核对 PT_LOAD：**文件偏移不一定等于 ELF 虚拟地址**，不能直接把文件偏移交给 addr2line。一般虚拟地址为 `p_vaddr + (file_offset - p_offset)`，适用段必须包含该偏移。BCC 栈帧通常是返回地址，需结合架构与反汇编找前面的 call，不能机械减一个固定常数跨架构通用。

```bash
readelf -n "$EXACT_LIBRARY"
readelf -lW "$EXACT_LIBRARY"
objdump -d -C "$EXACT_LIBRARY"
addr2line -e "$EXACT_LIBRARY" -f -C "$VERIFIED_ELF_VA"
```

strip 后可能只能确认 malloc 大小和调用链结构。使用匹配 Build-ID 的符号文件，或明确记录“反汇编推断、尚无源码行符号”。源码 tag、`zmq_version()` 相同不足以证明打包构建没有补丁。

确认精确构建和偏移后才加 `--frame-file-offset` 过滤；它只筛选栈，并不把栈自动认定为某个队列对象。记录为什么该偏移对应目标函数。

## 如何对比，如何进一步证明

- 同一次持续挂载内，比较相同栈/对象范围，且年龄、top-N、采样率相同。
- 两次独立十分钟窗口只比较“各自挂载后分配集合的存活趋势”；不能以末值相减计算凌晨到现在队列增量。
- 默认 memleak 看到 allocator 接口，不保证覆盖自定义内存池、所有 mmap、设备内存或所有 realloc 特殊语义。看所用工具源码；验证脚本只验证 malloc/free 基本路径。
- 656 字节块不等于 656 字节 USS，也不等于一条命令。对齐、备用块、allocator 缓存和页粒度都影响对应关系。
- 真正的队列级证明需要按 mailbox/pipe 对象指针关联成功入队、成功出队、命令类型和块分配/释放，保存初始基线。中途附加仅能得到 `入队数 − 出队数` 的变化，不能恢复此前绝对深度。
- 任一 map 溢出、丢失事件、缺失释放探针或无效栈都会限制结论；保留原始 stderr 并降低采集开销或换工具后重测。

官方参考：[BCC memleak](https://github.com/iovisor/bcc/blob/master/tools/memleak.py)、[BCC 工具说明](https://github.com/iovisor/bcc/blob/master/tools/memleak_example.txt)。这些链接用于阅读；实际执行应锁定当前安装版本并存源码哈希，不临时下载 master 覆盖系统工具。
