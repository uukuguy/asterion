# ARC Run Story About Copy Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand both run-story footer introductions with concise technical context while preserving the approved poster hierarchy.

**Architecture:** Keep the content static and provider-free inside the packaged HTML asset. Add one second paragraph to each existing card, retain the current two-column component, and regenerate the content-addressed web render so the fixed catalog exposes the new version.

**Tech Stack:** Static HTML/CSS, Python `unittest`, Asterion `arc-story` renderer and loopback artifact server.

## Global Constraints

- Each About card contains two short paragraphs totaling approximately 120–160 Chinese characters.
- Preserve the current card titles, eyebrow colors, position, and two-column desktop layout.
- Do not change playback, evidence, analysis, or report data.
- Keep language technical and restrained; do not use promotional claims.

---

### Task 1: Expand and publish the About cards

**Files:**
- Modify: `src/asterion/applications/prime/p7/run_story/assets/index.html`
- Modify: `src/asterion/applications/prime/p7/run_story/assets/styles.css`
- Modify: `tests/test_prime_arc_agi_3_run_story.py`

**Interfaces:**
- Consumes: `render_web(bundle_root: Path, analysis_id: str, *, theme_version: str = "poster-v1") -> RenderResult`
- Produces: a new content-addressed render containing the expanded packaged HTML asset.

- [ ] **Step 1: Add a failing content-boundary assertion**

Extend `test_render_is_deterministic_and_bound_to_data` with assertions for the new second paragraphs and technical terms:

```python
self.assertIn("关卡目标、对象含义和动力学规则不会直接给出", html)
self.assertIn("解题事实、事后分析与网页渲染分别版本化", html)
self.assertIn("ONLINE EXPERIMENTS", html)
self.assertIn("CONTROLLED EXECUTION", html)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_render_is_deterministic_and_bound_to_data
```

Expected: FAIL because the current HTML does not contain the expanded copy.

- [ ] **Step 3: Replace both About card bodies**

Use two `<p>` elements per card with this approved copy:

```html
<p>ARC-AGI-3 将抽象推理置于可交互环境中。智能体只获得当前画面、可用动作与执行反馈；关卡目标、对象含义和动力学规则不会直接给出，必须从状态变化中自行归纳。</p>
<p>每一步都会改变后续可观察状态，试错因此带有成本。智能体需要保留工作记忆，区分因果变化与动画噪声，提出可证伪假设并规划下一次实验，最终以环境返回的完成状态和可重放轨迹确认结果。</p>
```

```html
<p>Asterion 是可组合的通用智能体应用框架。它把应用装配、能力包、运行时、宿主服务和受控执行分成清晰边界，使同一套应用逻辑能够连接不同模型与智能体运行时，而不把凭据或执行权限交给模型。</p>
<p>Asterion Prime 在此基础上组合 Pi、语言模型、持久 IPython 与 ARC Broker，记录动作、画面、usage 和终态证据。解题事实、事后分析与网页渲染分别版本化，因此报告可验证、可重建，也可在样式更新后重新生成。</p>
```

Replace the terms with:

```html
<div class="terms"><b>HIDDEN OBJECTIVE</b> · STATEFUL WORLD · ONLINE EXPERIMENTS · BOUNDED ACTIONS</div>
<div class="terms"><b>COMPOSABLE CAPABILITIES</b> · RUNTIME ADAPTERS · CONTROLLED EXECUTION · VERIFIABLE ARTIFACTS</div>
```

- [ ] **Step 4: Add paragraph rhythm without changing layout**

Replace the single paragraph rule with:

```css
.about p{margin:0;color:#91a3b7;font-size:13px;line-height:1.6}
.about p+p{margin-top:9px}
```

- [ ] **Step 5: Run focused verification**

Run:

```bash
uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story
node --check src/asterion/applications/prime/p7/run_story/assets/app.js
```

Expected: 9 tests pass and Node exits 0.

- [ ] **Step 6: Regenerate the accepted real render**

Run:

```bash
uv run asterion arc-story render ls20-9607627b p7-live-20260909065351 --analysis analysis-eaebabce55daf73d3eda
```

Expected: exit 0 with a new `render_id`; `catalog.json` retains the prior render and includes the new one.

- [ ] **Step 7: Verify the fixed catalog route and commit**

Run:

```bash
curl -fsSI http://127.0.0.1:8765/ | rg "HTTP/1.0 200|Content-Security-Policy"
```

Expected: HTTP 200 and the restrictive CSP header.

Commit:

```bash
git add src/asterion/applications/prime/p7/run_story/assets/index.html src/asterion/applications/prime/p7/run_story/assets/styles.css tests/test_prime_arc_agi_3_run_story.py docs/status/JOURNAL.md
git commit -m "feat: expand ARC story technical context"
```
