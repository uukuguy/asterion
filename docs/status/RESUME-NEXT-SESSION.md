# Live Session Checkpoint

> Updated: 2026-09-24 04:01 CST. Fixed P3–P6 live preset repair is complete; this is a state checkpoint, not a final handoff.

## 当前任务

用户要求修复 P3–P6 只有确定性 witness、没有真实模型应用运行的缺口。之前的 P1 修复与一次真实完成收据已在 `fa889cfa` 合入 main；那不是 P3–P6 真实能力证据。云 GPU 话题已由用户撤销。

## 已验证事实

- 原有 `make asterion-prime-p3/p4/p5/p6-run` 均运行确定性 worker；P3/P5/P6 虽走 provider→assembly→runner，核心产物来自假函数。P4 原 operator 绕过组合入口；P4 assembly 原仅有 declarative policy，没有 executable binding。
- `f8199923` 让 P4 旧确定性 commit/recover 走组合入口，修复 recover mode 恒选 commit 与第二代 checkpoint 未写入。`a2dce55e` 将真实 P4 recover 的代际切换延后到模型结果校验及进程清理后；暂态模型失败保留 gen1，可同根重试。磁盘切换后失败仍 fail closed，不假造回滚。
- `586c6ade` 增加应用侧固定限额 `LiveModelSession`；`33194eeb` 又将缓存 token 纳入输入预算、用私有 Pi 配置限制 provider 输出 512 tokens 并在首次 prompt 前核验实际模型状态。成本字段是按固定价格对缓存 token 全价估算的保守上界，非账单数值。
- 修复限额后再次运行 `make asterion-prime-p3-run`：本地已安装 wheel 两个独立 Pi 会话真实完成，收据 `cfa2546cb73309e246774c24c686a8cd42ea371c2565f336cb22fd7ea30391a5`。这是固定 Pi 文本子任务，不是 IPython worker。
- `a2dce55e` 后再次运行 `make asterion-prime-p4-run`：两个独立本地 wheel 进程真实完成 commit/recover，第二代引用第一代 checkpoint，第二代收据 `929c4f5e7c6723e4c863e98345ba3999a81a0eeaab3cd1dae562976137a3ea13`。恢复的是固定任务状态 transcript，不是任意 IPython 内存。
- 再次运行 `make asterion-prime-p5-run`：模型首轮答对，1 次提案/1 次验证/0 次修复，收据 `e4a439fdcc3211518e9aaf16f05d24df1c935a2c34806b728bd58a61d38755be`；真实修复分支未发生。
- 再次运行 `make asterion-prime-p6-run`：模型候选经独立 holdout 改进检查和项目范围显式促升，收据 `71e3faebde4651f5a1e2055efffed7e04d2ee8d7ad1e12a93f81a242b81156ed`；未进行全局激活。
- P3–P6 旧确定性路径分别保留为 `asterion-prime-p3-witness`、`p4-witness`、`p5-witness`、`p6-witness`，限额见证仍用原 `-run-limits` 名称。修复预算后的 313 项 P3–P6 相关本地测试、Ruff、docs-check 通过；P4 重试补丁之后 30 项定向测试和真实双进程运行通过。

## 当前判断和历史边界

- 四个固定有界小任务已真实完成，但一次通过不能推断稳定率、广域任务能力或论文复现。P5 真实首轮修复、P6 真实回滚均未发生；仅本地注入测试覆盖这些分支。
- P4 已验证跨进程固定任务 checkpoint 消费及暂态模型失败后的同根重试；一旦进入代际切换而磁盘写入失败，仍需人工恢复，不能称为任意进程态或 IPython 堆恢复。P1 attachment 重建仅用于存活 worker。
- 全量 benchmark 与论文复现未获本轮授权；本轮只做各应用一项固定小验证。

## 已完成与后续边界

1. `make promotion-check ASTERION_PROMOTION_NPM_CACHE=$HOME/.npm` 已通过：25 条隔离发行命令、provider 操作 0。P4 后续仅改变应用 live.py 与测试，30 项定向测试及一次真实双进程运行通过。
2. 本轮 Pi/uv 进程已退出。四项私有证据保留在 `.asterion-private/prime-p{3,4,5,6}-live/` 对应目录，供必要的本地核对；公开输出只含收据与摘要。
3. 若后续要评估长期稳定率、P5 真实修复、P6 真实回滚、P4 磁盘过渡故障恢复或更广域任务能力，应单独定义范围和有限预算。本轮未进行 benchmark。
