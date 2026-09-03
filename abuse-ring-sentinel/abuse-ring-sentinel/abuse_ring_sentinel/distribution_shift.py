"""
Tests whether the detector generalizes beyond the exact population
distribution it was tuned against — not just different random seeds of
the SAME distribution (that's robustness.py's job), but genuinely
different distributions: smaller/larger rings, noisier rings, different
population mixes. DetectorConfig is never touched here — every shift
uses the same fixed thresholds/weights chosen against the original dev
distribution, which is the whole point: this measures whether tuning
overfit to one specific shape of population.
"""
from __future__ import annotations

from dataclasses import replace

from .config import DetectorConfig, EvaluationConfig, GeneratorConfig
from .data_generator import generate_dataset
from .evaluator import evaluate
from .graph_builder import build_graph
from .ring_detector import detect_rings

# Each shift changes ONE aspect of the population relative to the
# original dev distribution (GeneratorConfig defaults), so a recall/
# precision drop can be attributed to a specific cause rather than a
# vague "it got worse."
SHIFTS: dict[str, dict] = {
    "baseline (unshifted)": {},
    "smaller rings (3-6 members)": {"ring_size_range": (3, 6)},
    "larger rings (18-30 members)": {"ring_size_range": (18, 30)},
    "noisier rings (35% attribute noise)": {"ring_attribute_noise": 0.35},
    "very noisy rings (50% attribute noise)": {"ring_attribute_noise": 0.50},
    "more background collisions (8%)": {"background_collision_rate": 0.08},
    "smaller velocity rings (3-5 members)": {"velocity_ring_size_range": (3, 5)},
    "wider velocity age window (18 days)": {"velocity_account_age_max_days": 18,
                                             "velocity_account_age_spread_days": 12},
    "more lookalike clusters (12x)": {"n_lookalike_clusters": 12},
    "shorter observation window (21 days)": {"observation_days": 21},
}


def run_distribution_shifts(seed: int, det_cfg: DetectorConfig = DetectorConfig(),
                             eval_cfg: EvaluationConfig = EvaluationConfig()) -> list[dict]:
    rows = []
    for name, overrides in SHIFTS.items():
        gen_cfg = replace(GeneratorConfig(seed=seed), **overrides)
        accounts_df, orders_df, gt = generate_dataset(gen_cfg)
        g = build_graph(accounts_df, det_cfg)
        clusters = detect_rings(g, accounts_df, orders_df, det_cfg, gen_cfg.observation_days)
        report = evaluate(clusters, gt, eval_cfg)
        rows.append({
            "shift": name,
            "recall": report.recall,
            "classic_recall": report.classic_recall,
            "velocity_recall": report.velocity_recall,
            "precision": report.precision,
            "n_wrongly_flagged_accounts": report.n_wrongly_flagged_accounts,
        })
    return rows


if __name__ == "__main__":
    from .config import DET_CFG, EVAL_CFG

    rows = run_distribution_shifts(seed=42, det_cfg=DET_CFG, eval_cfg=EVAL_CFG)
    print(f"{'shift':<42} {'recall':>7} {'classic':>8} {'velocity':>9} {'precision':>10} {'wrong_fp':>9}")
    for r in rows:
        prec = f"{r['precision']:.3f}" if r["precision"] is not None else "N/A"
        vel = f"{r['velocity_recall']:.3f}" if r["velocity_recall"] is not None else "N/A"
        print(f"{r['shift']:<42} {r['recall']:>7.3f} {r['classic_recall']:>8.3f} {vel:>9} "
              f"{prec:>10} {r['n_wrongly_flagged_accounts']:>9}")
