# Pathlight 操作者手册 Implementation Plan

> **For agentic workers:** Execute this documentation plan inline in the existing `feature/pathlight-dci-recovery` worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一份与当前实现和真实 Bright A/B 状态一致的中文 Pathlight 操作者手册。

**Architecture:** 在 `docs/guides/` 建立唯一的操作者入口；设计稿保留架构依据，状态文档保留运行证据。手册只引用公开安全投影和占位绝对路径，DCI Bright 命令被明确标记为产品适配器，不反向定义通用框架接口。

**Tech Stack:** Markdown、Asterion CLI、`tools/check_docs.py`。

## Global Constraints

- 不写入 prompt、答案、case ID、provider payload、凭据或私有运行路径。
- 只读查询、Dashboard 和 Opik 离线交换必须说明是否调用模型或外部网络。
- Bright A/B 的事实固定为 80 Agent、0 Judge、$16、0 基础设施失败、`rejected (quality-threshold-missed)`。
- 开发默认免外层授权；严格生产开关为 `ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION=1`。

---

### Task 1: 编写并发布中文操作者手册

**Files:**
- Create: `docs/guides/pathlight-operator-guide.md`
- Modify: `docs/status/INDEX.md`
- Modify: `docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md`
- Modify: `docs/status/JOURNAL.md`

**Interfaces:**
- Consumes: `asterion pathlight` 的只读 CLI，`asterion-dci pathlight` 的 DCI 协调 CLI，已封存的 `workflow-evidence.json`、`pathlight-evaluations.json`、`pathlight-experiment.json`、`pathlight-diagnosis.json`、`pathlight-optimization.json`。
- Produces: 单一中文操作入口，并在状态索引注册；设计稿中的旧 A/B 命令状态改为指向该手册。

- [ ] **Step 1: 写入手册内容**

创建六段结构：开始前的证据文件清单；`trace`/`metrics`/`evaluate`/`diagnosis` 只读查询；Dashboard；DCI Bright 受控优化；Opik 离线交换；故障与安全边界。每段放入可复制命令，所有路径采用 `/absolute/path/...` 占位形式。

- [ ] **Step 2: 同步入口与状态**

在 `docs/status/INDEX.md` 的 Active 表添加 `pathlight-operator-guide.md` 行；在 Pathlight 设计稿的 Bright A/B 段落替换旧的“尚未执行、$8、必须授权文件”叙述，改为已完成的 80/0/$16/拒绝结论和手册链接。

- [ ] **Step 3: 验证文档**

运行：`make docs-check && git diff --check`

预期：文档检查列出全部本地链接且退出码为 0；无空白错误。

- [ ] **Step 4: 提交**

```bash
git add docs/guides/pathlight-operator-guide.md docs/status/INDEX.md \
  docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md docs/status/JOURNAL.md
git commit -m "docs: add Pathlight operator guide"
```

## 自检

- 设计的全部六段结构均由 Task 1 写入。
- 计划没有 TODO/TBD 或未定义接口。
- 手册的数字与已封存运行结果一致，且不把 DCI 命令写成通用框架职责。
