"""
Runs the full pipeline across many random seeds and aggregates results.

A single seed's precision/recall is a data point, not a claim. This
module exists so the README can honestly say "recall was 100% across N
independent populations, precision averaged X%, and here is the one
specific way it fails" instead of reporting one lucky run.
"""
from __future__ import annotations

from dataclasses import replace

import networkx as nx

from .config import DetectorConfig, EvaluationConfig, GeneratorConfig
from .data_generator import generate_dataset
from .evaluator import evaluate
from .graph_builder import build_graph
from .ring_detector import detect_rings


def run_multi_seed(seeds: list[int], gen_cfg: GeneratorConfig, det_cfg: DetectorConfig,
                    eval_cfg: EvaluationConfig) -> list[dict]:
    rows = []
    for seed in seeds:
        cfg = replace(gen_cfg, seed=seed)
        accounts_df, orders_df, gt = generate_dataset(cfg)
        g = build_graph(accounts_df, det_cfg)
        clusters = detect_rings(g, accounts_df, orders_df, det_cfg, cfg.observation_days)
        report = evaluate(clusters, gt, eval_cfg)
        rows.append({
            "seed": seed,
            "recall": report.recall,
            "classic_recall": report.classic_recall,
            "velocity_recall": report.velocity_recall,
            "precision": report.precision,
            "n_wrongly_flagged_accounts": report.n_wrongly_flagged_accounts,
            "false_positive_cost_inr": report.false_positive_cost_inr,
            "false_positive_clusters": report.false_positive_clusters,
            "dampening_saves": len(report.dampening_saves),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    precisions = [r["precision"] for r in rows if r["precision"] is not None]
    clean_runs = sum(1 for r in rows if r["n_wrongly_flagged_accounts"] == 0)
    failing = [r for r in rows if r["n_wrongly_flagged_accounts"] > 0]
    return {
        "n_seeds": n,
        "mean_recall": round(sum(r["recall"] for r in rows) / n, 3),
        "min_recall": round(min(r["recall"] for r in rows), 3),
        "mean_precision": round(sum(precisions) / len(precisions), 3) if precisions else None,
        "min_precision": round(min(precisions), 3) if precisions else None,
        "clean_runs": clean_runs,
        "runs_with_false_positives": n - clean_runs,
        "failing_seeds": [r["seed"] for r in failing],
    }


def _dampen_point_estimate(return_rate: float, burst_score: float, hard_evidence: int,
                            cfg: DetectorConfig) -> bool:
    """The ORIGINAL (buggy) dampening test: compares the raw observed
    return rate directly to the ceiling. Reproduced here, isolated from
    the real detector, purely so the bug described in the README/
    project explainer can be replayed and quantified — the live
    detector in ring_detector.py never uses this path."""
    looks_normal = return_rate <= cfg.normal_return_rate_ceiling and burst_score <= cfg.normal_timing_burst_ceiling
    return looks_normal and hard_evidence == 0


def _dampen_ci_lower_bound(return_rate: float, burst_score: float, n_orders: int,
                            hard_evidence: int, cfg: DetectorConfig) -> bool:
    """The FIXED dampening test, mirroring ring_detector._apply_policy —
    reproduced here (rather than imported) so this module can compute
    both rules from the same raw cluster stats in one pass."""
    if n_orders > 0:
        se = (return_rate * (1 - return_rate) / n_orders) ** 0.5
        return_rate_lower = max(0.0, return_rate - cfg.return_rate_ci_z * se)
    else:
        return_rate_lower = return_rate
    looks_normal = return_rate_lower <= cfg.normal_return_rate_ceiling and burst_score <= cfg.normal_timing_burst_ceiling
    return looks_normal and hard_evidence == 0


def replay_dampening_fix(seeds: list[int], gen_cfg: GeneratorConfig, det_cfg: DetectorConfig,
                          eval_cfg: EvaluationConfig) -> dict:
    """
    Replays the Section-4/6 dampening bug across many seeds, comparing
    the old point-estimate rule against the fixed CI-lower-bound rule on
    identical underlying cluster data (same graph, same scores — only
    the dampening decision differs). This is what turns "we found and
    fixed a bug" into a measured, reproducible claim instead of an
    anecdote about 3 seeds.
    """
    old_fp_accounts_total = 0
    new_fp_accounts_total = 0
    old_clean_runs = 0
    new_clean_runs = 0
    per_seed = []

    for seed in seeds:
        cfg = replace(gen_cfg, seed=seed)
        accounts_df, orders_df, gt = generate_dataset(cfg)
        g = build_graph(accounts_df, det_cfg)
        # Raw candidates: scored and flagged, but with dampening OFF, so
        # both rules below can be applied to the same underlying data.
        raw_clusters = detect_rings(g, accounts_df, orders_df, det_cfg, cfg.observation_days,
                                     apply_dampening=False)

        legit_ids = {aid for m in gt["lookalikes"].values() for aid in m}
        old_fp_accounts = 0
        new_fp_accounts = 0
        for c in raw_clusters:
            if not (c.flagged and c.avg_edge_weight <= det_cfg.weak_sharing_avg_weight_ceiling):
                continue
            hard_evidence = (c.attribute_breakdown["device_fingerprint"]
                              + c.attribute_breakdown["payout_account"]
                              + c.attribute_breakdown["phone_number"])
            would_dampen_old = _dampen_point_estimate(c.return_rate, c.timing_burst_score, hard_evidence, det_cfg)
            would_dampen_new = _dampen_ci_lower_bound(c.return_rate, c.timing_burst_score, c.n_orders,
                                                       hard_evidence, det_cfg)
            legit_overlap = len(set(c.members) & legit_ids)
            if not would_dampen_old:
                old_fp_accounts += legit_overlap
            if not would_dampen_new:
                new_fp_accounts += legit_overlap

        old_fp_accounts_total += old_fp_accounts
        new_fp_accounts_total += new_fp_accounts
        old_clean_runs += (old_fp_accounts == 0)
        new_clean_runs += (new_fp_accounts == 0)
        per_seed.append({"seed": seed, "old_rule_fp_accounts": old_fp_accounts, "new_rule_fp_accounts": new_fp_accounts})

    n = len(seeds)
    return {
        "n_seeds": n,
        "old_rule_clean_runs": old_clean_runs,
        "new_rule_clean_runs": new_clean_runs,
        "old_rule_false_positive_rate": round(1 - old_clean_runs / n, 3),
        "new_rule_false_positive_rate": round(1 - new_clean_runs / n, 3),
        "old_rule_total_fp_accounts": old_fp_accounts_total,
        "new_rule_total_fp_accounts": new_fp_accounts_total,
        "per_seed": per_seed,
    }


if __name__ == "__main__":
    from .config import DET_CFG, EVAL_CFG, GEN_CFG

    seeds = [42, 7, 123, 999, 2026, 31, 88, 555, 2024, 17]
    rows = run_multi_seed(seeds, GEN_CFG, DET_CFG, EVAL_CFG)
    for r in rows:
        print(r)
    print()
    print(summarize(rows))

    print()
    print("--- dampening rule replay (old point-estimate vs. new CI-based) ---")
    replay_seeds = list(range(1, 41))
    replay = replay_dampening_fix(replay_seeds, GEN_CFG, DET_CFG, EVAL_CFG)
    print(f"old rule: {replay['old_rule_clean_runs']}/{replay['n_seeds']} clean "
          f"({replay['old_rule_false_positive_rate']:.0%} FP rate)")
    print(f"new rule: {replay['new_rule_clean_runs']}/{replay['n_seeds']} clean "
          f"({replay['new_rule_false_positive_rate']:.0%} FP rate)")
