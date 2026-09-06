# Live Session Checkpoint

> Updated: 2026-09-06. **Session remains active — not a final handoff.**

## Direction

按评估后的主线持续推进直至完成。Asterion核心为统一框架与能力包集成协议；Prime和Native并行，先收口Prime七项。用户纠偏：研发验证只保留正常链路与关键边界断言；不追加极端矩阵、native测试helper或反复promotion。根Sol协调整合，Terra明确实现，Astra复杂契约；机械任务可用Luna，但旧Luna thread额度耗尽。

Canonical: docs/status/PRIME-TYPICAL-APPLICATIONS.md
Plan: docs/superpowers/plans/2026-09-05-prime-authority-bundle-and-linux-launch.md

## Current implementation and evidence

P3 live checkpoint：`67d321ea`/`6e971c46`完成可重入 gateway 且保持 P1/P2 同步回调；`6f549035`固定真实 SDK 拓扑为 root4/implementation2/review4、总计10次模型回调和4次工具调用；`ac99738a`完成真实 RLM child/follow-up/cleanup，`32ddbbd5`补齐 review follow-up 错误终态拒绝，Sol 最终复审 APPROVE。`74f98d50`已接通 Python 五种 closed nested command。当前并行实现具体 Docker 生命周期、角色 provider/host 和 P3 installed route；`aecb8444`仅为 scaffolding，不构成真实 E2E 证据。

本地实现已推进至6f496311及后续P1-B清理修复；未push。主要状态：
- d103447 qualification IPC/bootstrap；真实Linux四个focused checks通过（normal/cancel/identity/handoff ownership）。不发production receipt。
- 6408ab9等待cell completion并保持可snapshot；c4a7969可cancel/reap模型子进程；9a6c789接development host/broker/oracle。
- 1a12fda Dockerfile对齐canonical context；f371e1a修真实CLI参数、interactive start握手、env/namespace/absence投影。
- f689b69修canonical worker ID与daemon ID分离、workspace tmpfs UID/GID65534 mode0700、标准kernel mount/sentinel适配。
- d3f9c92新增development-only local-root proc snapshot；真实initial snapshot已成功。不能声称降权authority有此能力。
- 850365c固定P1请求thinking disabled，并仅解包单个完整Markdown code fence；两项provider-free检查通过（0.006s）。随后一次有限真实模型调用仍安全失败且完成清理，未盲重试。
- 15efffd7/46cfc62e新增并收紧SDK结构化两轮DeepSeek provider：P1-A专用8192 input/1024 output/10000 cost/60秒预算；首轮768 output、次轮保留至少256；第二轮只能追加首轮签发的原样assistant tool call和相关toolResult。terminal usage仅在两轮完整成功后可见。固定bridge options只校验不转发；HTTP禁ambient proxy；fork child只保留私有pipe descriptors。六项focused unittest与ruff通过。
- 4f3c88be/c8ae1e8c新增Python继承FD gateway并修active prompt取消回收；0362c161区分worker外层一次exchange与SDK内部两次provider callback。
- c309abd1/1082d9e8完成P1-A host接线、隔离SDK workspace并固定一次IPython验证prompt；764c6f3b兼容后端tool-call的空字符串content。

P1-A与P1-B开发链路均已真实完成。P1-B使用一个Prime SDK session、两次prompt、一次真实compact、五次provider callback、两次Docker IPython cell、同一kernel及十二项连续性probe；双snapshot、AST oracle、provider/Node/container cleanup均完成。安全结果为`p1-b-development/unpromoted`与`sha256:21ba3699ff291d98349bf2895b3453adacd1a48dd0b6f9fdfd6803321f403d46`。Prime SDK会话仍属于host-side TypeScript Gateway；Python保留授权、预算、模型进程、Docker、snapshot与最终oracle。

## Next concrete action

1. 以已验证的 P1/P3 runtime、provider、gateway、Docker 和 host-service 脊柱实现 P4 长会话连续性。
2. 接通实际 detach/attach、一次 compact、恢复后同一 oracle，禁止盲目重放外部效果。
3. 增加 exact installed application 与 `make prime-p4-run`，执行一次真实 CLI 并检查零残留。
4. 研发验证只覆盖正常流程和身份、恢复边界、取消清理、公开脱敏；不运行 promotion 或极端矩阵。

P2精确命令`prime.programmatic-long-context@1.0.0`已退出0：一个Prime SDK session、两次model callback、一次Docker IPython cell、固定八记录corpus oracle和cleanup均完成。安全结果为`p2-development/unpromoted`与trace `4ec38c0cb80010941892523610bb9cdbf8b37c213ed6c759fcd794f30d57a62e`。最终guest中P2 Node进程与容器均为0；Sol最终复审APPROVE。

最新进展：`6bd2a764`/`a1861acc`增加并收紧私有provider失败分类；`23c7faee`/`e45cacd0`增加经Sol复审的operator私有阶段观察器。一次观察运行完成5/5 callback与2/2 cell，无失败；随后精确命令`--application prime.ipython-coding@1.0.0`退出0并返回安全trace。先前省略版本的命令只在selector处失败，并未进入host。最终guest中Prime Node进程与P1-B容器均为0。

## Actual environment

- Linux为OrbStack `ubuntu`，使用`orb -m ubuntu -u root`；Docker29.2.1与host同一guest，/usr/bin/docker，/var/run/docker.sock，GID988。Mac /tmp不是guest /tmp。
- Python live命令使用`/private/tmp/asterion-p1-sdk-run-20260906.py`；guest Node22.23.2位于`/tmp/asterion-node22/bin/node`并按官方SHA256校验。这是live-source开发边界，不是sealed bundle运行。
- P1-A image `sha256:cdaa182cd3dfd3377aaf93757d8edfdd2c96025e2becf0be86f2fb9e6a053d5c`；P1-B image `sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657`，均为linux/arm64且未promotion。
- Context Mac `/private/tmp/asterion-p1-development-context-v3-20260906.tar`；build log同目录`asterion-p1-development-build-v3-20260906.log`。
- 官方Moby docker-v29.2.1默认seccomp已保存guest `/tmp/asterion-p1-development-seccomp.json`；canonical hash7ce699efbba58df5691185a87189ecc0a47ff01c48ec8fc5708465954b672979。未promotion。
- 原qualification bundle仍为guest `/tmp/asterion-authority-candidate-9hpk1mgz`与.release.json（CPython3.13.7/658files/5external libs）。不要混作development image/完整authority。

## Agents and preservation

P1/P2/P3 开发实现均已结束。P3 的干净 Make 入口退出 0，trace 为
`sha256:b961b0ffc13a1e686a73361b9b25b9169690c942a5a84a3604d52f87e5ebe796`；
14 个聚焦测试通过，容器、网关进程和临时目录均为零。下一项是 P4。

保留既有`.superpowers/sdd/task-1-report.md`、JOURNAL/RESUME未提交修改、未跟踪旧计划和tmp目录。不要整体暂存、重置、删除或push。完整ARC/global harness activation/发布不在本轮范围。
