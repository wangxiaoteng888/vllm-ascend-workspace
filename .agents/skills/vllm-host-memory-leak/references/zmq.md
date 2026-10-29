# ZMQ / 共享内存通知专项

## 先核对当前版本的实际代码

定位服务解释器加载的 `vllm/distributed/device_communicators/shm_broadcast.py`，检查是否仍有 SpinCondition、last_read、busy_loop_s、local_notify_socket、CONFLATE 和 wait 分支。新版本可能已重构；本 skill 的补丁适配本次遇到的结构，匹配失败就停下审阅，不猜行号强行替换。

在本次结构中：Worker 本地结果写入共享内存并发布可读标志后调用 notify，发送 `b"\x00"`。EngineCore 优先检查共享内存；有未读结果直接取，不必先收通知。没有结果时进入 wait，但默认距上次成功读取的 1 秒内只 sched_yield；每次成功读取又刷新 last_read，所以 wait_calls 可以很多而 poll_calls 仍为 0。这个 1 秒不是请求超时，检查失败本身不刷新 last_read。

ZMQ IPC 后台 I/O 线程可以在业务线程不调用 poll 时接收通知并把内部命令写进 socket 的 mailbox。要区分三层：共享内存结果、ZMQ 单字节通知、libzmq 的内部 command_t。CONFLATE 作用于消息，不能据此断言 `_cpipe` 只有一个元素。

## 被动计数：先预览

```bash
python3 "$KIT/scripts/instrument_notify.py" --target "$SHM_BROADCAST" \
  --output "$RUN/notify-preview"
```

查看 diff；确认没有新增 socket.poll/recv/getsockopt(EVENTS)，没有改变原分支、读标志、busy_loop_s 或通知发送频率。应用使用预览保存的 baseline SHA256：

```bash
python3 "$KIT/scripts/instrument_notify.py" --target "$SHM_BROADCAST" \
  --expected-sha256 "$BASELINE_SHA256" --apply --output "$RUN/notify-install"
```

只在源码修改属于本次授权时执行。**脚本不重启服务**；对已导入模块的进程修改磁盘文件不会生效。需要新增计数时，在获准的下一次服务启动中设置：

```bash
export VLLM_NOTIFY_DIAG_DIR="$RUN/notify"
export VLLM_NOTIFY_DIAG_INTERVAL=10
```

helper 在线程中定期输出 JSONL，只有 Python 计数与时间读取，不查询 ZMQ EVENTS。为了诊断而从报告线程调用同一个 SUB socket，既可能违反线程使用约束，又会改变积压现象，禁止用这种方式“看一眼队列”。`socket_pointer` 来自 pyzmq underlying 指针属性，不是 EVENTS 查询。

计数是低开销近似快照，不是原子事务；新增 Python 代码、日志线程本身仍有时序开销，不能称“绝对零扰动”。对象指针不能跨进程、跨重启比较；新 helper 额外输出 created_mono 便于识别对象复用。

恢复：

```bash
python3 "$KIT/scripts/instrument_notify.py" --restore "$RUN/notify-install/installation.json"
```

恢复前校验当前文件仍是安装时的哈希；有后续改动就拒绝覆盖。同样不会重启已运行进程。保留 baseline/diff/manifest 作为证据。

## 指标语义

- `shm_reads`：该 reader 成功完成的共享内存读取次数。
- `wait_calls`：进入 wait 次数；不代表真的进入 ZMQ 等待。
- `spin_returns`：wait 内的忙等分支次数。
- `poll_calls/poll_returns`：开始调用 / 返回；两者差值可能只是当时阻塞在 poll。
- `notify_recvs`：通知 recv 成功返回次数；不等于内部命令消费数。
- `notify_sends`：send 返回次数；不等于对端实际收到的次数。
- `since_last_*_s`：对应动作距当前的秒数；null 是自计数创建以来尚未发生，不是零秒。
- `queue/notify_address/socket_pointer`：逐对象关联线索；不要把多个 mailbox 聚合结果说成 TP0 某个队列。

```bash
python3 "$KIT/scripts/notify_report.py" --input "$RUN/notify/notify-PID-SESSION.jsonl" \
  --output "$RUN/notify-summary.json"
```

可用 --since/--until epoch 限定同一窗口。全时间 poll=0 的表述必须给出记录起止、是否覆盖进程创建，以及日志是否有缺口。输出 first/last totals 和 delta，避免只看一个末值。

## 4.3.5 的可核验源码链

阅读下面固定 tag 的链接，不能据此推断未来版本行为完全相同：

1. [官方 CONFLATE 文档](https://github.com/zeromq/libzmq/blob/v4.3.5/doc/zmq_setsockopt.txt#L122-L137)：不接收可出现增长，建议查询 ZMQ_EVENTS 推进。
2. [ypipe_conflate](https://github.com/zeromq/libzmq/blob/v4.3.5/src/ypipe_conflate.hpp)：flush 与 reader_awake。
3. [pipe flush](https://github.com/zeromq/libzmq/blob/v4.3.5/src/pipe.cpp#L234-L241)：触发 send_activate_read。
4. [command 创建](https://github.com/zeromq/libzmq/blob/v4.3.5/src/object.cpp#L242-L248) → [ctx 路由](https://github.com/zeromq/libzmq/blob/v4.3.5/src/ctx.cpp#L595-L598) → [mailbox 入队](https://github.com/zeromq/libzmq/blob/v4.3.5/src/mailbox.cpp#L30-L37)。
5. [mailbox 类型](https://github.com/zeromq/libzmq/blob/v4.3.5/src/mailbox.hpp#L38-L41) 的 `_cpipe` 是 command_t 队列；[granularity=16](https://github.com/zeromq/libzmq/blob/v4.3.5/src/config.hpp#L15-L17) 表示每块元素数，不是整个队列容量上限。
6. [yqueue 扩容与 pop](https://github.com/zeromq/libzmq/blob/v4.3.5/src/yqueue.hpp)：按块增长，pop 用完块后保留备用块并释放旧备用；并非每个命令都单独 free。
7. [ZMQ_EVENTS](https://github.com/zeromq/libzmq/blob/v4.3.5/src/socket_base.cpp#L434-L443) → [process_commands](https://github.com/zeromq/libzmq/blob/v4.3.5/src/socket_base.cpp#L1356-L1401)：取出并执行命令，不是直接丢弃队列。

这解释一种积压机制；是否解释本次现场全部内存增长，需要运行时数据。不能仅以 PR 降内存、版本相同、或 USS 曲线相似作为根因证明。

## 数据结构级验证与修复

第一层是 Python 计数，第二层是 BCC allocator 栈，第三层才是具体 mailbox 对象：

- 锁定确切 .so 哈希与匹配符号/反汇编，对 send/recv 成功路径按 `this` 指针和 cmd.type 计数。
- 关联 socket pointer → mailbox → `_cpipe` → chunks；布局必须来自该构建的 debug info 或核实的反汇编，不能复制旧对象偏移。
- 同一对象的成功入队减成功出队得到附加后的深度变化；要绝对深度需初始基线或可靠的当前结构快照。读取并发变化的指针时要考虑一致性，不能随便遍历就宣称精确。
- 针对该结构证明块数增长/释放，再与同窗口 USS 比较数量级。原生存活字节和 USS 不要求严格 1:1；数量级不符时必须找剩余增长来源。
- 修复候选是让 socket 在拥有它的线程中定期通过正常 API 推进，而不是丢内部命令。保证共享内存状态仍为真相，检查等待前后的竞态、关闭/超时、热路径开销。
- 对照实验：同负载基线、只加计数、候选修复；比较业务正确性、吞吐/延迟、poll、目标队列深度/块数与 USS。不能只拿“修改后内存下降”当安全性证据。
