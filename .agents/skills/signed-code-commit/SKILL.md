---
name: signed-code-commit
description: 按 wangxiaoteng 的 Git 身份创建带 DCO Signed-off-by 的代码提交。用户要求提交代码、commit、推送已有修改或更新 PR 时使用；仅编写或审查代码不代表授权提交或推送。
---

# 代码提交约定

姓名：`wangxiaoteng`

邮箱：`wangxiaoteng@huawei.com`

提交参数：`-sm`

`-s` 添加 DCO `Signed-off-by`，`-m` 指定提交说明；这不是 GPG 签名的 `-S`。

## 提交

1. 确认目标仓库、分支、remote 和用户授权范围。查看 `git status --short`、暂存区和未暂存 diff，保留不属于本次任务的修改；按明确路径暂存，不使用无差别 `git add .`。
2. 按仓库要求完成相关验证，并用 `git diff --cached --check` 检查。核对暂存文件，不纳入凭据、实验日志、生成报告、运行时文件或子模块指针，除非它们就是本次提交对象。
3. 提交说明遵循目标仓库约定；没有特别约定时使用简短英文 Conventional Commit，例如 `fix(kv-transfer): preserve host block ownership`。
4. 使用命令级身份配置，不修改全局 Git 配置：

   ```bash
   git -c user.name=wangxiaoteng -c user.email=wangxiaoteng@huawei.com var GIT_AUTHOR_IDENT
   git -c user.name=wangxiaoteng -c user.email=wangxiaoteng@huawei.com var GIT_COMMITTER_IDENT
   git -c user.name=wangxiaoteng -c user.email=wangxiaoteng@huawei.com commit -sm "<type>(<scope>): <summary>"
   ```

   提交前确认两条 `git var` 都显示上述姓名和邮箱。环境变量可能覆盖 `-c` 配置；若身份不符，只在本次命令范围内消除覆盖后再提交，不修改其他人的提交归属。
5. 提交后检查：

   ```bash
   git log -1 --format=full
   git show --stat --oneline HEAD
   ```

   新提交的 Author、Committer 应为上述身份，提交消息应包含：

   ```text
   Signed-off-by: wangxiaoteng <wangxiaoteng@huawei.com>
   ```

## 推送与 PR

- 仅在用户要求推送、提交到远端或更新 PR 时推送；创建 skill 或普通代码修改本身不授权推送。
- 核对实际 push URL 与目标分支，不因为 remote 名为 `origin` 就默认它是用户的 fork。使用明确的 `git push <remote> HEAD:<target-branch>`。
- 更新已有 PR 时使用它的实际源仓库和源分支，保留原提交记录，默认追加新提交；不擅自新建 PR、amend、squash、rebase 或 force-push。
- 新提交加签不会补齐旧提交的 DCO。需要改写历史或改变旧作者时，先说明影响并取得相应授权；不要批量改成当前身份。
- push 遇到非快进、认证失败或保护规则时，不反复强推、不降低 TLS 校验；保留提交并报告具体状态。
- 推送后核对远端分支 SHA。交付提交 SHA、目标分支、验证结果和实际推送状态，未推送成功时不要声称远端已更新。
