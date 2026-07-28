"""climb decision-gate — decide PUSH / SKIP per climb skill §5 best-effort rule.

Input:
    --hypothesis-id H-NNN
    --local-eval-json path  (output of eval-local.sh, JSON with total + per_task + f_surv)
    [--train-cost-h X.X]    (defaults: read from manifest if exists)

Output:
    stdout JSON: {decision, reason, predicted_online, ci, sota_threshold, action_next}

§5 rule order:
    1. first-of-paradigm (n_samples == 0)  → PUSH (calibration data essential)
    2. disaster_pattern (any task f_surv < 0.5, or total < 10) → SKIP (paradigm bug)
    3. predict_online >= best_online      → PUSH (potential breakthrough)
    4. train_cost_h < 2                    → PUSH (cheap calibration check)
    5. else                                → SKIP (advance pool, don't pause)
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS_CSV = ROOT / "docs/status/climb/runs.csv"
CALIB_JSON = ROOT / "docs/status/climb/calibration.json"

HYPOS_YAML = ROOT / "docs/status/climb/hypotheses.yaml"


def load_calib():
    return json.load(open(CALIB_JSON)) if CALIB_JSON.exists() else {"paradigms": {}}


def load_runs():
    return list(csv.DictReader(open(RUNS_CSV))) if RUNS_CSV.exists() else []


def find_hypothesis_paradigm(hyp_id):
    """Look up paradigm from hypotheses.yaml."""
    if not HYPOS_YAML.exists():
        return None
    hypos = json.loads(HYPOS_YAML.read_text())
    for h in hypos.get("hypotheses", []):
        if h.get("id") == hyp_id:
            return h.get("parent_paradigm")
    return None


def get_best_online(runs):
    best = 0.0
    best_id = None
    for r in runs:
        try:
            s = float(r.get("online_score") or 0)
            if s > best:
                best, best_id = s, r.get("run_id")
        except (ValueError, TypeError):
            pass
    return best, best_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hypothesis-id", required=True)
    ap.add_argument("--local-eval-json", required=True)
    ap.add_argument("--train-cost-h", type=float, default=None)
    ap.add_argument("--paradigm", default=None, help="override (else from hypothesis)")
    args = ap.parse_args()

    # Load local eval
    eval_data = json.load(open(args.local_eval_json))
    local_total = eval_data.get("total")
    f_surv = eval_data.get("f_surv", {})

    # Resolve paradigm
    paradigm = args.paradigm or find_hypothesis_paradigm(args.hypothesis_id)
    if not paradigm:
        print(f"[gate] ERROR: cannot resolve paradigm for {args.hypothesis_id}", file=sys.stderr)
        sys.exit(1)

    calib = load_calib()
    runs = load_runs()
    paradigm_info = calib.get("paradigms", {}).get(paradigm, {})
    n_samples = paradigm_info.get("n_samples", 0)
    mean_gap = paradigm_info.get("mean_gap")
    std_gap = paradigm_info.get("std_gap")
    best_online, sota_id = get_best_online(runs)

    # Predict online
    predicted = None
    ci = None
    if local_total is not None and mean_gap is not None:
        predicted = float(local_total) + float(mean_gap)
        if std_gap:
            ci = [predicted - float(std_gap), predicted + float(std_gap)]
        else:
            ci = [predicted - 5, predicted + 5]  # default CI when single sample

    # §5 rule application
    decision, reason = None, None

    # Rule 1: first-of-paradigm
    if n_samples == 0:
        decision, reason = "PUSH", f"first-of-paradigm ({paradigm}), calibration data essential"
    # Rule 2: disaster pattern
    # ⚠️ 项目自定: 下面阈值 (total < 10, f_surv < 0.5) 是 Fusion-Control 评分量级 (总分 ~50).
    #    新项目按自己主指标改: 如 Macro-F1 项目用 total < 0.3; f_surv 概念不适用则删第二条.
    #    disaster = "明显 paradigm bug 不值得 push 浪费 LB", 不是"没破 SOTA" (那是 Rule 5 SKIP).
    elif local_total is not None and float(local_total) < 1:
        decision, reason = "SKIP", f"disaster: task gate {local_total:.2f} < 1"
    elif f_surv and min((float(v) for v in f_surv.values() if v is not None), default=1.0) < 0.5:
        bad = [k for k, v in f_surv.items() if v is not None and float(v) < 0.5]
        decision, reason = "SKIP", f"disaster: tasks {bad} f_surv < 0.5"
    # Rule 3: breakthrough prediction
    elif predicted is not None and predicted > best_online:
        decision, reason = "PUSH", (
            f"predicted online {predicted:.2f} > SOTA {best_online:.2f} ({sota_id}), "
            f"potential breakthrough"
        )
    # Rule 4: cheap check
    elif args.train_cost_h is not None and args.train_cost_h < 2:
        pred_str = f"{predicted:.2f}" if predicted is not None else "N/A"
        decision, reason = "PUSH", (
            f"cheap calibration check (cost {args.train_cost_h:.1f}h < 2h), "
            f"predicted {pred_str}"
        )
    # Rule 5: default skip
    else:
        decision = "SKIP"
        if predicted is not None:
            reason = (
                f"predicted {predicted:.2f} <= SOTA {best_online:.2f} "
                f"({(predicted - best_online):+.2f} gap), expensive (cost {args.train_cost_h}h), advance pool"
            )
        else:
            reason = f"no calibration data for paradigm yet, expensive (cost {args.train_cost_h}h), advance pool"

    result = {
        "decision": decision,
        "reason": reason,
        "predicted_online": predicted,
        "ci": ci,
        "sota_threshold": best_online,
        "sota_id": sota_id,
        "paradigm": paradigm,
        "n_calibration_samples": n_samples,
        "local_total": local_total,
        "action_next": (
            "execute push.sh + add pending-lb entry" if decision == "PUSH"
            else "advance hypothesis pool, mark skip-by-decision"
        ),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
