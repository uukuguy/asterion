# BP35 当前版本九关冷实测

## 结果

2026-10-11，用户授权一次 BP35 完整过关实测。当前代码未修改，从独立空历史开始。目标九关，实际完成五关，L6未完成；**目标未达成**。没有自动重跑或续跑。

- run: `p7-live-20261011055641-cfeafd599f7790165a23af2d`
- 游戏: `bp35-0a0ad940`，seed0；模型 `openai-codex/gpt-6.1-sol`。
- 冻结源码基线 `ec0d2f3d`，636个文件哈希与运行后源码一致；期间提交仅涉及状态文档。
- 命令: `make asterion-prime-p7-solve GAME=bp35 LEVEL=9 ASTERION_PRIME_OPERATOR_ROOT=<isolated-trial>`。
- 既定限制: 3600秒、128模型回调、500工具回调、1302动作；guest外部3900秒上限。
- 已结算128次模型调用，输入5,410,401tokens、输出46,916tokens。累计输入包含重复上下文，不是唯一内容量或实际付款。
- guest预算起点至summary约1581.984秒（26分22秒），不是九关完成时间。

| 关卡 | 完成 | primitive actions | RESET |
|---|---|---:|---:|
| L1 | 是 | 20 | 0 |
| L2 | 是 | 47 | 1 |
| L3 | 是 | 40 | 0 |
| L4 | 是 | 62 | 1 |
| L5 | 是 | 45 | 1 |
| L6 | 否 | 41 | 1 |
| L7–L9 | 未到达 | 0 | 0 |

总255动作/4RESET；前五关完整前缀214动作。观察期间的累计动作可能已包含下一关探索，以上按首次关卡完成位置重新分段。

## 已验证事实

公开receipt为 `status=unsuccessful`、`completed_level_count=5`、`target_level=9`、`terminal_reason=active`；`replay_verified/sealed_trace/cleanup_complete=true`。退出0只表示生成了可用失败回执，不代表通关。

独立校验 `independent-evidence-audit.json` 为 `PASS_FOR_STATED_BOUNDARIES`：

- 386条trace，闭合哈希链与精确seal通过。
- 255个console动作与trace一致；255个action-journal事务均已提交、结果已知，before/after/scope和current一致。
- 使用既有 `load_exact_prefix` 进行新SDK重放，前五关214动作通过；replay SHA `a842647a99648a7a57868673c6f5d304f78af9de48146e09756d8f43b4b0750d`。
- 完整255动作失败记录仅做静态一致性校验，不宣称独立重放全部失败后缀。
- `deadline_expired=false`，未触及时间或动作上限；剩余动作1047。
- 临时trial `.env` 已删除；host Make PID已消失，guest unit `asterion-p7-880965ba860043669a4f3de38bcd5d4f.service` 为not-found/inactive、MainPID0、ControlGroup空；原用户console保留。

首次打包启动因隔离目录缺少guest launcher，在模型前失败；补齐既有launcher后启动唯一实际模型试验。没有改生产源码、阈值、prompt或应用stash。

## 当前判断

停止原因强烈指向完整入口的128模型回调上限：128条已结算usage、129次before-request度量，末个native事件为sequence1031 `turn_start`。`execution.py`在turn_start递增回调数，并在超过限制时拒绝 `MODEL_CALLBACK_LIMIT`。

原summary只保存 `ApplicationRunError/application_failure`，没有保留该细分原因码。因此回调耗尽是源码与事件支持的推断，不是原回执直接给出的原因。不能将本次中止解读为L6必然无法解出，也不能推断提高回调上限即可九关通过。

## 证据与未完成边界

私有证据目录 `.asterion-private/p7-full-bp35-20261011-135551/`：launch、source-manifest、measurements、public-receipt、independent-evidence-audit及trial原始研究/事务/trace/SDK记录。原始prompt、认证和模型输出不入公共Git。

既往ARC-AGI-3累计满分记录与本次固定版本、空历史冷实测是不同证据边界。当前九关冷完成能力没有本次PASS证据。后续应先核对完整评估预设的回调范围与失败原因保留；不得继承本次预算或自动开启第二次试验。
