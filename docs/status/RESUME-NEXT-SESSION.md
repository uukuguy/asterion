# Live Session Checkpoint

> Updated: 2026-09-06 03:25. **Session remains active — not a final handoff.**

## Direction

按评估后的主线持续推进直至完成。Asterion核心为统一框架与能力包集成协议；Prime和Native并行，先收口Prime七项。用户纠偏：研发验证只保留正常链路与关键边界断言；不追加极端矩阵、native测试helper或反复promotion。根Sol协调整合，Terra明确实现，Astra复杂契约；机械任务可用Luna，但旧Luna thread额度耗尽。

Canonical: docs/status/PRIME-TYPICAL-APPLICATIONS.md
Plan: docs/superpowers/plans/2026-09-05-prime-authority-bundle-and-linux-launch.md

## Current implementation and evidence

本地实现已推进至764c6f3b；未push。主要新增提交：
- d103447 qualification IPC/bootstrap；真实Linux四个focused checks通过（normal/cancel/identity/handoff ownership）。不发production receipt。
- 6408ab9等待cell completion并保持可snapshot；c4a7969可cancel/reap模型子进程；9a6c789接development host/broker/oracle。
- 1a12fda Dockerfile对齐canonical context；f371e1a修真实CLI参数、interactive start握手、env/namespace/absence投影。
- f689b69修canonical worker ID与daemon ID分离、workspace tmpfs UID/GID65534 mode0700、标准kernel mount/sentinel适配。
- d3f9c92新增development-only local-root proc snapshot；真实initial snapshot已成功。不能声称降权authority有此能力。
- 850365c固定P1请求thinking disabled，并仅解包单个完整Markdown code fence；两项provider-free检查通过（0.006s）。随后一次有限真实模型调用仍安全失败且完成清理，未盲重试。
- 15efffd7/46cfc62e新增并收紧SDK结构化两轮DeepSeek provider：P1-A专用8192 input/1024 output/10000 cost/60秒预算；首轮768 output、次轮保留至少256；第二轮只能追加首轮签发的原样assistant tool call和相关toolResult。terminal usage仅在两轮完整成功后可见。固定bridge options只校验不转发；HTTP禁ambient proxy；fork child只保留私有pipe descriptors。六项focused unittest与ruff通过。
- 4f3c88be/c8ae1e8c新增Python继承FD gateway并修active prompt取消回收；0362c161区分worker外层一次exchange与SDK内部两次provider callback。
- c309abd1/1082d9e8完成P1-A host接线、隔离SDK workspace并固定一次IPython验证prompt；764c6f3b兼容后端tool-call的空字符串content。

P1-A现已完成一次真实有界链路：Prime SDK `session.prompt()`→两次真实provider callback→一次Docker IPython→post snapshot→host oracle→broker revoke→容器清理，输出`p1-a-development/unpromoted` trace。完整P1仍未PASS。Prime SDK会话属于host-side TypeScript Gateway，Python保留授权、预算、模型进程、Docker、snapshot与最终oracle；restricted worker仅保留IPython kernel/workspace。下一步是P1-B持久session/kernel、两次prompt和一次真实compaction，然后接public runtime。

## Next concrete action

1. 设计P1-B exact contract：同一Prime session、同一Docker IPython kernel、两次prompt之间保留namespace/import/function/cwd/file witness，并执行一次真实`session.compact()`；计数、预算和证据不得复用P1-A常量猜测。
2. 在现有TypeScript Gateway扩展独立P1-B adapter/protocol版本；Python继续只做授权、provider/Docker broker、snapshot/oracle/cleanup，不复制session逻辑。
3. 只验证正常持久链路、compaction witness、取消回收和脱敏边界；不跑promotion/发布矩阵。P1-B完成后接public runtime preset。
4. 所有模型继续使用repo `.env`的operator wiring，禁止打印值或增加公开provider/model/budget旋钮。

## Actual environment

- Linux为OrbStack `ubuntu`，使用`orb -m ubuntu -u root`；Docker29.2.1与host同一guest，/usr/bin/docker，/var/run/docker.sock，GID988。Mac /tmp不是guest /tmp。
- Python live命令使用`/private/tmp/asterion-p1-sdk-run-20260906.py`；guest Node22.23.2位于`/tmp/asterion-node22/bin/node`并按官方SHA256校验。这是live-source开发边界，不是sealed bundle运行。
- 当前image `sha256:cdaa182cd3dfd3377aaf93757d8edfdd2c96025e2becf0be86f2fb9e6a053d5c`，linux/arm64，tag `asterion-p1-development:20260906`。input739aeadbb639c78cb9cb40e9e02881989efb9f8d8165e9de7526d250aef0dcfe。
- Context Mac `/private/tmp/asterion-p1-development-context-v3-20260906.tar`；build log同目录`asterion-p1-development-build-v3-20260906.log`。
- 官方Moby docker-v29.2.1默认seccomp已保存guest `/tmp/asterion-p1-development-seccomp.json`；canonical hash7ce699efbba58df5691185a87189ecc0a47ff01c48ec8fc5708465954b672979。未promotion。
- 原qualification bundle仍为guest `/tmp/asterion-authority-candidate-9hpk1mgz`与.release.json（CPython3.13.7/658files/5external libs）。不要混作development image/完整authority。

## Agents and preservation

P1-A实现/复审agent均已结束；P1-B契约设计是下一任务。没有正在运行的model调用或完整测试流程。

保留既有`.superpowers/sdd/task-1-report.md`、JOURNAL/RESUME未提交修改、未跟踪旧计划和tmp目录。不要整体暂存、重置、删除或push。完整ARC/global harness activation/发布不在本轮范围。
