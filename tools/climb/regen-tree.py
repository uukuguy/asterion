"""climb regen-tree — generate docs/status/climb/research-tree.md from climb state.

═══ TEMPLATE (climb.md §15.4) — cp 到 tools/climb/regen-tree.py 后按需改 ═══
本脚本 ~90% 框架逻辑可直接用。**项目自定的只有 render_in_flight 的字段映射**:
session-state.json 的字段名各项目可不同 (FC 用 in_flight_train/next_action_on_resume,
AC 用 in_flight/next_action)。render_in_flight 已写成兼容两种命名 (a or b), 新项目若
用第三套字段名, 在 render_in_flight 里加 `ss.get('你的字段')` 即可。其余 (calibration/
push ladder/mermaid/hypothesis pool) 是框架通用渲染, 不用改。
═══════════════════════════════════════════════════════════════════════

Reads:  docs/status/climb/runs.csv + hypotheses.yaml + calibration.json
        + pending-lb.json + session-state.json
Writes: docs/status/climb/research-tree.md (Markdown + Mermaid + Hypothesis pool + in-flight)

⚠️ Output 必须 DETERMINISTIC (no datetime.now() / random) — post-commit auto-regen
hook 靠幂等性 (状态没变 regen 无 diff → 不无谓 amend). 用 run 数代时间戳.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
RUNS_CSV = ROOT / "docs/status/climb/runs.csv"
HYPOS_YAML = ROOT / "docs/status/climb/hypotheses.yaml"
CALIB_JSON = ROOT / "docs/status/climb/calibration.json"
PENDING_LB = ROOT / "docs/status/climb/pending-lb.json"
SESSION_STATE = ROOT / "docs/status/climb/session-state.json"
OUT_MD = ROOT / "docs/status/climb/research-tree.md"


def load_runs() -> list[dict]:
    if not RUNS_CSV.exists():
        return []
    rows = list(csv.DictReader(open(RUNS_CSV)))
    # 过滤注释行（run_id 以 # 开头）和空行
    return [r for r in rows if (r.get("run_id") or "").strip() and not r["run_id"].lstrip().startswith("#")]


def load_hypos() -> dict:
    if not HYPOS_YAML.exists() or yaml is None:
        return {"hypotheses": []}
    return yaml.safe_load(open(HYPOS_YAML))


def load_calib() -> dict:
    if not CALIB_JSON.exists():
        return {"paradigms": {}}
    return json.load(open(CALIB_JSON))


def load_pending() -> dict:
    if not PENDING_LB.exists():
        return {"pending": [], "landed_this_session": []}
    return json.load(open(PENDING_LB))


def fmt(s) -> str:
    if s is None or s == "" or s == "null":
        return "—"
    try:
        return f"{float(s):.2f}"
    except (ValueError, TypeError):
        return str(s)


def render_calibration(calib: dict) -> str:
    out = ["## Paradigm calibration matrix", ""]
    out.append("| paradigm | n | mean_gap | std | last_3 |")
    out.append("|---|---|---|---|---|")
    for name, p in calib.get("paradigms", {}).items():
        gaps = p.get("last_3_gaps") or []
        gaps_s = ", ".join(fmt(g) for g in gaps) if gaps else "—"
        out.append(
            f"| {name} | {p.get('n_samples', 0)} | "
            f"{fmt(p.get('mean_gap'))} | {fmt(p.get('std_gap'))} | [{gaps_s}] |"
        )
    return "\n".join(out) + "\n"


def render_push_ladder(runs: list[dict]) -> str:
    out = ["## Push ladder (chronological)", ""]
    out.append("| run_id | paradigm | parent | local | online | gap | verdict |")
    out.append("|---|---|---|---|---|---|---|")
    for r in sorted(runs, key=lambda r: r.get("pushed_at") or ""):
        verdict = r.get("verdict") or "pending"
        badge = ("🥇" if "SOTA" in verdict and "near" not in verdict else
                 "🟢" if "confirmed" in verdict else
                 "🔴" if "falsified" in verdict else "🟡")
        out.append(
            f"| {r.get('run_id', '?')} | {r.get('paradigm', '?')} | "
            f"{r.get('parent_run') or '—'} | {fmt(r.get('local_score'))} | "
            f"{fmt(r.get('online_score'))} | {fmt(r.get('gap'))} | "
            f"{badge} {verdict} |"
        )
    return "\n".join(out) + "\n"


def render_mermaid(runs: list[dict]) -> str:
    out = ["## Mermaid push DAG", "", "```mermaid", "graph LR"]
    out.append("    classDef sota fill:#4ade80,stroke:#15803d,color:#000")
    out.append("    classDef confirmed fill:#86efac,stroke:#16a34a,color:#000")
    out.append("    classDef falsified fill:#fca5a5,stroke:#b91c1c,color:#000")
    out.append("    classDef pending fill:#fde68a,stroke:#a16207,color:#000")

    sota_id = None
    sota_score = 0.0
    for r in runs:
        try:
            s = float(r.get("online_score") or 0)
            if s > sota_score:
                sota_score, sota_id = s, r.get("run_id")
        except (ValueError, TypeError):
            pass

    def nid(rid):
        return rid.replace(".", "_").replace("-", "_").replace("+", "_")

    for r in runs:
        rid = r.get("run_id", "?")
        node = nid(rid)
        online = fmt(r.get("online_score"))
        verdict = (r.get("verdict") or "pending").lower()
        out.append(f'    {node}["{rid}<br/>{online}"]')
        if rid == sota_id:
            out.append(f"    class {node} sota")
        elif "confirmed" in verdict:
            out.append(f"    class {node} confirmed")
        elif "falsified" in verdict:
            out.append(f"    class {node} falsified")
        elif "pending" in verdict:
            out.append(f"    class {node} pending")
    for r in runs:
        parent = r.get("parent_run")
        if parent and parent != "—":
            out.append(f"    {nid(parent)} --> {nid(r.get('run_id', '?'))}")
    out.append("```")
    return "\n".join(out) + "\n"


def render_hypothesis_pool(hypos: dict, pending: dict) -> str:
    out = ["## Hypothesis pool", ""]
    all_h = hypos.get("hypotheses", [])
    active = [h for h in all_h if h.get("status") in ("pending", "in-flight")]
    confirmed = [h for h in all_h if "confirmed" in str(h.get("status", ""))]
    falsified = [h for h in all_h if "falsified" in str(h.get("status", ""))]

    out.append(f"### Active ({len(active)}) — ranked by priority")
    for h in sorted(active, key=lambda h: -(h.get("ranking") or 0)):
        out.append(
            f"- **{h['id']}** (rank {h.get('ranking', 0):.2f}, cost {h.get('cost_h', '?')}h, "
            f"{h.get('status', 'pending')}): {h.get('description', '?')}"
        )
        if h.get("expected_lift"):
            out.append(f"  - lift: {h['expected_lift']}")
    out.append("")

    if pending.get("pending"):
        out.append(f"### Pending LB ({len(pending['pending'])})")
        for p in pending["pending"]:
            out.append(f"- {p.get('run_id')} (pushed {p.get('pushed_at')}, paradigm {p.get('paradigm')})")
        out.append("")

    if confirmed:
        out.append(f"### Confirmed ({len(confirmed)})")
        for h in confirmed:
            out.append(f"- {h['id']}: {h.get('description', '?')}")
        out.append("")

    if falsified:
        out.append(f"### Falsified ({len(falsified)}) — negative cache")
        for h in falsified:
            last = h.get("results", [{}])[-1] if h.get("results") else {}
            out.append(f"- {h['id']}: {h.get('description', '?')} — _{last.get('verdict', 'no data')}_")
    return "\n".join(out) + "\n"


def load_session_state() -> dict:
    if not SESSION_STATE.exists():
        return {}
    return json.load(open(SESSION_STATE))


def render_in_flight(ss: dict) -> str:
    """Render dynamic session state — makes research-tree the single file resume reads.

    DETERMINISTIC: only stored fields, no now() (preserves post-commit idempotency).
    Resume re-verifies any in-flight job liveness at runtime; this shows intent only.
    """
    if not ss:
        return ""
    out = ["## In-flight / session state (dynamic — resume reads this, then verifies liveness)", ""]
    out.append(f"- **phase**: {ss.get('phase', '?')}")
    if ss.get("best_online") is not None:
        out.append(f"- **best online**: {ss.get('best_online')}")
    out.append(f"- **last_cycle**: {ss.get('last_cycle', '?')}")
    out.append(f"- **next_hypothesis**: {ss.get('next_hypothesis', '?')}")

    inflt = ss.get("in_flight") or ss.get("in_flight_train")
    if inflt and isinstance(inflt, dict):
        out.append("")
        out.append("**In-flight job** (resume MUST verify liveness):")
        for k, v in inflt.items():
            out.append(f"- {k}: {v}")
    else:
        out.append("- **in-flight**: none")

    na = ss.get("next_action") or ss.get("next_action_on_resume")
    if na:
        out.append("")
        out.append(f"**Next action on resume**: {na}")
    fr = ss.get("falsified_routes") or ss.get("falsified_dont_ladder")
    if fr:
        fr_s = " / ".join(fr) if isinstance(fr, list) else fr
        out.append(f"\n**Don't ladder (falsified)**: {fr_s}")
    return "\n".join(out) + "\n"


def main():
    runs = load_runs()
    hypos = load_hypos()
    calib = load_calib()
    pending = load_pending()
    session_state = load_session_state()

    sota = max((r for r in runs if r.get("online_score")),
               key=lambda r: float(r.get("online_score") or 0), default=None)
    sota_line = (f"**SOTA**: {sota['run_id']} = {fmt(sota.get('online_score'))} "
                 f"(paradigm {sota.get('paradigm', '?')})") if sota else "**SOTA**: —"

    # DETERMINISTIC: 用 run 数代替 datetime.now() — 状态变了才变, 没变 regen 无 diff (幂等).
    # 否则每次 regen 时间戳都变 → post-commit auto-regen+amend 每次 commit 都无谓 amend.
    n_runs = len(runs)
    parts = [
        "# Research Tree — climb cycle observability",
        "",
        f"> Generated by `tools/climb/regen-tree.py` (deterministic — {n_runs} runs logged)",
        "> Do NOT edit — re-generated on every push / LB landed / cycle complete.",
        "",
        sota_line,
        "",
        render_in_flight(session_state),
        render_calibration(calib),
        render_push_ladder(runs),
        render_mermaid(runs),
        render_hypothesis_pool(hypos, pending),
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(parts))
    print(f"[regen-tree] wrote {OUT_MD} ({OUT_MD.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
