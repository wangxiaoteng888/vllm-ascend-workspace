# 本版本验证记录

验证日期：2026-10-22。验证只使用隔离小进程、一次性源码副本和已有采集记录，没有给运行中的推理服务安装本 skill 的新补丁，也没有重启服务。

## 已完成

- 全部 12 个 Python 文件语法编译；9 个面向用户的 Python CLI 的 `--help` 正常。
- Linux AArch64 隔离测试：指定 PID 的 smaps_rollup 采样两次，再 `--resume` 追加一次，共三条；核对身份、start_ticks、NSpid 与内存字段。
- 源码副本上的 instrumentation preview 不修改目标；apply 需要匹配 SHA256；restore 后源码 SHA256 与原始文件完全相同，新增 helper 被移除。
- 用本次实验 898 个 smem 样本测试解析和作图，末值 USS 为 2884.6171875 MiB。过期数据默认拒绝，显式历史模式生成标记 HISTORICAL 的图；人工检查 PNG 排版。
- 用已有通知日志验证逐队列统计，输出五个对象，保留首末累计值与差值，不把 send-recv 当深度。
- 用此前 BCC 采集的 21 份报告验证解析结果，目标分配路径的字节数逐份与原始审计结果一致；末份 282736 字节。该测试用于确认解析器，没有把目标偏移写进执行脚本默认值。
- 在既有 BCC 0.29.1 验证环境重新核对 native 函数第七参数 ABI 后，使用显式兼容模式运行新的 `bcc_validate.py`：12347 字节块，观测顺序为 `0,1000,1000,1000,1000,100,100,100,100,0,0,0,0`，通过 malloc/free 双向验证。
- 新 `bcc_capture.py` 在一次性 worker 上完成 8 秒有界采集，生成 BCC 报告、至少两条内存快照和身份 manifest；observer 正常退出，目标 worker 在采集结束后仍存活，随后由验证程序自行回收。真实服务未被挂载本次验证探针。

## 验证边界

- 一次环境上的 BCC 验证不能替代下次目标环境验证；stock BCC 的内核/权限/绑定组合可能不同。兼容模式不是通用默认。
- 当前插桩模板只验证本次 SpinCondition 源码结构；不保证自动适配后续重构版本。脚本依赖唯一文本匹配并失败关闭。
- 隔离验证没有证明某个服务发生泄漏，没有验证某个修复 PR 的业务正确性，也没有测得当前任一 mailbox 的绝对深度。
- smem 源自用户提供的监控包，保留原文件版权声明与 GPL-2.0-or-later 说明；`scripts/smem/COPYING` 附 GPL v2 文本。`run_smem.py` 将扫描进程数固定为 4，shell 包装器增加独立日志、锁与超时。
- 作图需要 matplotlib；BCC 运行时使用系统安装的工具，skill 不私自安装、升级或替换目标机器的 BCC/内核。

脚本和说明进一步修改后，重新验证受影响的行为；不要把此记录作为永久兼容性保证。

## Contribution packaging checks (2026-10-29)

The earlier record is retained as author-provided history; its external runtime
artifacts were not re-executed or imported for this contribution.

Seven offline regression cases passed with Python 3.12.10 on Windows:
mapping-aware BCC frame offsets, PID reuse rejection and lifetime selection,
stale-data refusal, notification interval deltas, counter-reset rejection,
mixed-process rejection, and refusal to patch a source with the wrong hash.
Run them with `python3 -m unittest discover -s
.agents/skills/vllm-host-memory-leak/tests -v` from the workspace root.

These cases use synthetic inputs and temporary files. They do not attach BCC,
inspect a live process, run smem, modify a service, or reproduce Ascend inference.
