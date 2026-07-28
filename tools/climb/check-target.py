"""climb check-target — 确定性判定用户设的探索目标是否达成 (climb.md §4.1).

═══ FRAMEWORK 脚本 (climb.md §15.2) — cp 自 shared-templates, 几乎不用改 ═══
项目自定的只有: 当前最高分从哪读 (默认 runs.csv local/online_score 最大值,
session-state.sota 作 fallback) — 若项目字段名不同, 改 read_current_best().
═══════════════════════════════════════════════════════════════════════

读: session-target.md 的机器可读 TARGET 块 + runs.csv 当前最高分
出: stdout JSON {has_target, met, metric, current, target, gap, pct, reason}

调用点 (确定性, 非软要求):
  - cycle.sh _sync_state 末: cycle 完检查, met → emit PAUSE 信号
  - apply-lb-score.sh 末: LB 落检查, met → emit PAUSE 信号

判据 (climb.md §4.1): ground-truth 真分越阈才算达成 (预测达标不算).
DETERMINISTIC: 无 now()/random — 同状态多次跑同结果.

target 块格式 (session-target.md, 空/缺 = best-effort 无限攀爬):
    <!-- TARGET-BEGIN (machine-readable, check-target.py reads) -->
    target_metric: local        # local | online (读 runs.csv 对应列最大值)
    target_value: 80            # 数字阈值; 缺/留空 = best-effort, 不自停
    <!-- TARGET-END -->
"""
from __future__ import annotations
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_MD = ROOT / "docs/status/climb/session-target.md"
RUNS_CSV = ROOT / "docs/status/climb/runs.csv"
SESSION_STATE = ROOT / "docs/status/climb/session-state.json"


def parse_target() -> dict:
    """Parse machine-readable TARGET block. Returns {} if no target (best-effort)."""
    if not TARGET_MD.exists():
        return {}
    text = TARGET_MD.read_text()
    m = re.search(r"TARGET-BEGIN(.*?)TARGET-END", text, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    metric = re.search(r"target_metric:\s*(\w+)", block)
    value = re.search(r"target_value:\s*([\d.]+)", block)
    if not value:  # value 缺/空 = best-effort
        return {}
    return {
        "metric": (metric.group(1) if metric else "local").strip(),
        "value": float(value.group(1)),
    }


def read_current_best(metric: str) -> float | None:
    """当前最高分: runs.csv 的 <metric>_score 最大值, session-state.sota 作 fallback.

    项目自定点: 若 runs.csv 列名 / session-state 结构不同, 改这里。
    """
    col = f"{metric}_score"  # local_score | online_score
    best = None
    if RUNS_CSV.exists():
        for r in csv.DictReader(open(RUNS_CSV)):
            v = r.get(col)
            if v is None or v == "":
                continue
            try:
                fv = float(v)
                if best is None or fv > best:
                    best = fv
            except (ValueError, TypeError):
                pass
    if best is not None:
        return best
    # fallback: session-state.sota.<metric> (可能是数字或带文字的字符串)
    if SESSION_STATE.exists():
        sota = json.load(open(SESSION_STATE)).get("sota", {})
        raw = sota.get(metric)
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            m = re.search(r"[\d.]+", raw)
            if m:
                return float(m.group())
    return None


def main():
    target = parse_target()
    if not target:
        print(json.dumps({
            "has_target": False, "met": False,
            "reason": "best-effort mode (no target set) — 无限攀爬, 不自停",
        }, ensure_ascii=False))
        return

    metric, tval = target["metric"], target["value"]
    current = read_current_best(metric)
    if current is None:
        print(json.dumps({
            "has_target": True, "met": False, "metric": metric, "target": tval,
            "current": None, "reason": f"no {metric}_score data yet to compare",
        }, ensure_ascii=False))
        return

    met = current >= tval  # max 方向 (score_direction 默认 max)
    gap = round(tval - current, 4)
    pct = round(100 * current / tval, 1) if tval else None
    result = {
        "has_target": True,
        "met": met,
        "metric": metric,
        "current": current,
        "target": tval,
        "gap": gap,
        "pct": pct,
        "reason": (
            f"🎯 TARGET MET: {metric} {current} >= {tval} → §4.1 Hard Pause "
            f"(写 handoff 汇报成果, 暂停等用户讨论下一档)"
            if met else
            f"在途: {metric} {current}/{tval} ({pct}%, 还差 {gap}) → 继续攀爬"
        ),
    }
    print(json.dumps(result, ensure_ascii=False))
    # exit code: 0=未达成继续, 10=达成应暂停 (调用方据此 emit PAUSE)
    sys.exit(10 if met else 0)


if __name__ == "__main__":
    main()
