"""
Abuse-Ring Sentinel — end-to-end pipeline runner.

    python3 main.py

Generates synthetic data -> builds the shared-attribute graph -> detects
rings -> evaluates against ground truth -> writes CSVs, a JSON payload,
and a metrics summary into ./outputs/.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from abuse_ring_sentinel.baseline_detector import naive_address_flags
from abuse_ring_sentinel.config import DET_CFG, EVAL_CFG, GEN_CFG, HELD_OUT_SEED
from abuse_ring_sentinel.data_generator import generate_dataset
from abuse_ring_sentinel.distribution_shift import run_distribution_shifts
from abuse_ring_sentinel.evaluator import evaluate, sweep_thresholds
from abuse_ring_sentinel.graph_builder import build_graph
from abuse_ring_sentinel.report import build_payload, write_payload
from abuse_ring_sentinel.ring_detector import detect_rings
from abuse_ring_sentinel.robustness import replay_dampening_fix, run_multi_seed, summarize
from abuse_ring_sentinel.visualize import render_dashboard

OUT_DIR = Path(__file__).parent / "outputs"
ROBUSTNESS_SEEDS = [42, 7, 123, 999, 2026, 31, 88, 555, 2024, 17, 1, 2, 3, 4, 5]
BUG_REPLAY_SEEDS = list(range(1, 41))  # 40 independent seeds, distinct from ROBUSTNESS_SEEDS

# Measured separately via `python3 -m abuse_ring_sentinel.benchmark`, NOT
# re-run inside main() — a 150k-account run takes over a minute even
# after the performance fixes, which would make every `python3 main.py`
# invocation unreasonably slow. These are the real, cited numbers from
# that command on this machine; see README Section 5 for the full story
# (including the bugs profiling found) and rerun the benchmark yourself
# to reproduce them.
SCALE_BENCHMARK = {
    "measured_via": "python3 -m abuse_ring_sentinel.benchmark 1400 10000 100000 150000",
    "note": "Run separately from the main pipeline — see README Section 5.",
    "rows": [
        {"accounts": 1592, "orders": 7976, "total_seconds": 0.34, "peak_mb": 90.7, "recall": 1.0, "precision": 1.0},
        {"accounts": 11349, "orders": 56561, "total_seconds": 2.91, "peak_mb": 150.0, "recall": 1.0, "precision": 1.0},
        {"accounts": 113734, "orders": 568454, "total_seconds": 40.75, "peak_mb": 402.9, "recall": 1.0, "precision": 0.996},
        {"accounts": 170717, "orders": 853318, "total_seconds": 77.96, "peak_mb": 1109.0, "recall": 1.0, "precision": 0.995},
    ],
}


def main() -> None:
    t0 = time.time()
    OUT_DIR.mkdir(exist_ok=True)

    print("[1/10] Generating synthetic dataset (dev seed)...")
    accounts_df, orders_df, ground_truth = generate_dataset(GEN_CFG)
    accounts_df.to_csv(OUT_DIR / "accounts.csv", index=False)
    orders_df.to_csv(OUT_DIR / "orders.csv", index=False)
    print(f"      {len(accounts_df)} accounts, {len(orders_df)} orders, "
          f"{len(ground_truth['rings'])} planted classic rings, "
          f"{len(ground_truth['velocity_rings'])} planted velocity rings, "
          f"{len(ground_truth['lookalikes'])} planted legit clusters")

    print("[2/10] Building shared-attribute graph...")
    g = build_graph(accounts_df, DET_CFG)
    print(f"      {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

    print("[3/10] Detecting candidate rings...")
    clusters = detect_rings(g, accounts_df, orders_df, DET_CFG, GEN_CFG.observation_days)
    print(f"      {len(clusters)} clusters, {sum(c.flagged for c in clusters)} flagged, "
          f"{sum(c.dampened for c in clusters)} dampened, "
          f"{sum(c.velocity_flag for c in clusters)} velocity-flagged")

    print("[4/10] Evaluating against ground truth (dev seed)...")
    report = evaluate(clusters, ground_truth, EVAL_CFG)
    precision_str = f"{report.precision:.0%}" if report.precision is not None else "N/A (no flags)"
    velocity_recall_str = f"{report.velocity_recall:.0%}" if report.velocity_recall is not None else "N/A"
    print(f"      recall={report.recall:.0%} (classic={report.classic_recall:.0%}, "
          f"velocity={velocity_recall_str})  precision={precision_str}  "
          f"FP cost=Rs {report.false_positive_cost_inr:,.0f}")

    print("[5/10] Running naive baseline for comparison...")
    baseline_flags = naive_address_flags(accounts_df)
    ring_ids = {aid for m in ground_truth["rings"].values() for aid in m}
    legit_ids = {aid for m in ground_truth["lookalikes"].values() for aid in m}
    baseline_recall = sum(1 for f in baseline_flags if set(f["members"]) & ring_ids) / len(ground_truth["rings"])
    baseline_fp_accounts = sum(len(set(f["members"]) & legit_ids) for f in baseline_flags)
    print(f"      naive address-only baseline: recall={baseline_recall:.0%}, "
          f"{baseline_fp_accounts} legit accounts wrongly flagged")

    print(f"[6/10] Evaluating on held-out seed ({HELD_OUT_SEED}, never used to tune thresholds)...")
    from dataclasses import replace as _replace
    held_out_cfg = _replace(GEN_CFG, seed=HELD_OUT_SEED)
    ho_accounts_df, ho_orders_df, ho_gt = generate_dataset(held_out_cfg)
    ho_g = build_graph(ho_accounts_df, DET_CFG)
    ho_clusters = detect_rings(ho_g, ho_accounts_df, ho_orders_df, DET_CFG, held_out_cfg.observation_days)
    ho_report = evaluate(ho_clusters, ho_gt, EVAL_CFG)
    ho_precision_str = f"{ho_report.precision:.0%}" if ho_report.precision is not None else "N/A"
    print(f"      held-out recall={ho_report.recall:.0%}  precision={ho_precision_str}  "
          f"FP cost=Rs {ho_report.false_positive_cost_inr:,.0f}")

    print(f"[7/10] Running {len(ROBUSTNESS_SEEDS)}-seed robustness sweep...")
    robustness_rows = run_multi_seed(ROBUSTNESS_SEEDS, GEN_CFG, DET_CFG, EVAL_CFG)
    robustness_summary = summarize(robustness_rows)
    print(f"      {robustness_summary['clean_runs']}/{robustness_summary['n_seeds']} seeds fully clean, "
          f"mean precision={robustness_summary['mean_precision']:.0%}, "
          f"mean recall={robustness_summary['mean_recall']:.0%}")

    print(f"[8/10] Replaying the dampening-rule bug fix across {len(BUG_REPLAY_SEEDS)} seeds "
          f"(old point-estimate rule vs. fixed CI-based rule)...")
    bug_replay = replay_dampening_fix(BUG_REPLAY_SEEDS, GEN_CFG, DET_CFG, EVAL_CFG)
    print(f"      old rule: {bug_replay['old_rule_clean_runs']}/{bug_replay['n_seeds']} clean "
          f"({bug_replay['old_rule_false_positive_rate']:.0%} FP rate)")
    print(f"      new rule: {bug_replay['new_rule_clean_runs']}/{bug_replay['n_seeds']} clean "
          f"({bug_replay['new_rule_false_positive_rate']:.0%} FP rate)")

    print("[9/10] Running distribution-shift stress test (fixed config, 10 shifted populations)...")
    shift_rows = run_distribution_shifts(seed=GEN_CFG.seed, det_cfg=DET_CFG, eval_cfg=EVAL_CFG)
    n_perfect_shifts = sum(1 for r in shift_rows if r["recall"] == 1.0 and r["precision"] == 1.0)
    print(f"      {n_perfect_shifts}/{len(shift_rows)} shifts hold at 100%/100% with zero re-tuning")

    print("[10/10] Writing report payload, dashboard, sweep, and metrics summary...")
    payload = build_payload(accounts_df, g, clusters, report, ground_truth)
    payload["metrics"]["n_orders_analyzed"] = len(orders_df)
    payload["metrics"]["held_out_seed"] = HELD_OUT_SEED
    payload["metrics"]["held_out_recall"] = ho_report.recall
    payload["metrics"]["held_out_precision"] = ho_report.precision
    payload["metrics"]["held_out_fp_cost_inr"] = ho_report.false_positive_cost_inr
    payload["metrics"]["robustness"] = {"seeds": robustness_rows, "summary": robustness_summary}
    payload["metrics"]["bug_replay"] = bug_replay
    payload["metrics"]["distribution_shift"] = shift_rows
    payload["metrics"]["scale_benchmark"] = SCALE_BENCHMARK

    threshold_sweep = sweep_thresholds(clusters, ground_truth, EVAL_CFG, DET_CFG)
    with open(OUT_DIR / "threshold_sweep.json", "w", encoding="utf-8") as f:
        json.dump(threshold_sweep, f, indent=2, default=str)
    payload["metrics"]["threshold_sweep"] = threshold_sweep

    write_payload(payload, str(OUT_DIR / "dashboard_data.json"))

    dashboard_html = render_dashboard(payload)
    (OUT_DIR / "dashboard.html").write_text(dashboard_html, encoding="utf-8")

    summary = {
        "runtime_seconds": round(time.time() - t0, 2),
        **payload["metrics"],
    }
    with open(OUT_DIR / "metrics_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nDone in {summary['runtime_seconds']}s. Outputs in {OUT_DIR}/")


if __name__ == "__main__":
    main()
