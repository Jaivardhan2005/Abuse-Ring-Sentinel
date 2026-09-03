"""
Measures actual wall-clock time and memory at increasing population
sizes, stage by stage, so scale claims in the README are measured, not
guessed. Run directly: python3 -m abuse_ring_sentinel.benchmark
"""
from __future__ import annotations

import gc
import resource
import time
from dataclasses import replace

from .config import DetectorConfig, EvaluationConfig, GeneratorConfig
from .data_generator import generate_dataset
from .evaluator import evaluate
from .graph_builder import build_graph
from .ring_detector import detect_rings


def scaled_config(n_background: int, seed: int = 42) -> GeneratorConfig:
    """
    Scales the planted-abuse population roughly proportionally to the
    background population (so recall/precision stay measurable at every
    scale) while keeping per-ring/per-cluster SIZE ranges fixed — a ring
    doesn't get bigger just because the platform has more users, but a
    platform with more users plausibly has more rings running at once.
    """
    scale = max(1, n_background // 1400)  # 1400 = the original dev-seed background size
    return GeneratorConfig(
        seed=seed,
        n_background_accounts=n_background,
        n_rings=8 * scale,
        n_lookalike_clusters=4 * scale,
        n_borderline_lookalike_clusters=1 * scale,
        n_velocity_rings=2 * scale,
    )


def _peak_rss_mb() -> float:
    # ru_maxrss is KB on Linux, bytes on macOS — this project's dev/CI
    # target is Linux, so KB is assumed here.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run_benchmark(n_background: int, det_cfg: DetectorConfig = DetectorConfig(),
                   eval_cfg: EvaluationConfig = EvaluationConfig()) -> dict:
    gc.collect()
    gen_cfg = scaled_config(n_background)

    t0 = time.perf_counter()
    accounts_df, orders_df, gt = generate_dataset(gen_cfg)
    t1 = time.perf_counter()

    g = build_graph(accounts_df, det_cfg)
    t2 = time.perf_counter()

    clusters = detect_rings(g, accounts_df, orders_df, det_cfg, gen_cfg.observation_days)
    t3 = time.perf_counter()

    report = evaluate(clusters, gt, eval_cfg)
    t4 = time.perf_counter()

    return {
        "n_accounts": len(accounts_df),
        "n_orders": len(orders_df),
        "n_planted_rings": len(gt["rings"]) + len(gt["velocity_rings"]),
        "graph_nodes": g.number_of_nodes(),
        "graph_edges": g.number_of_edges(),
        "gen_seconds": round(t1 - t0, 3),
        "graph_build_seconds": round(t2 - t1, 3),
        "detect_seconds": round(t3 - t2, 3),
        "evaluate_seconds": round(t4 - t3, 3),
        "total_seconds": round(t4 - t0, 3),
        "peak_rss_mb": round(_peak_rss_mb(), 1),
        "recall": report.recall,
        "precision": report.precision,
        "n_wrongly_flagged_accounts": report.n_wrongly_flagged_accounts,
    }


if __name__ == "__main__":
    import sys

    sizes = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [1400, 10_000, 100_000]
    rows = []
    for n in sizes:
        print(f"--- running n_background_accounts={n:,} ---", flush=True)
        row = run_benchmark(n)
        rows.append(row)
        print(row, flush=True)
        print(flush=True)

    print(f"{'accounts':>10} {'orders':>10} {'gen_s':>8} {'graph_s':>8} {'detect_s':>9} "
          f"{'total_s':>8} {'peak_mb':>9} {'recall':>7} {'precision':>10}")
    for r in rows:
        prec = f"{r['precision']:.3f}" if r['precision'] is not None else "N/A"
        print(f"{r['n_accounts']:>10,} {r['n_orders']:>10,} {r['gen_seconds']:>8.2f} "
              f"{r['graph_build_seconds']:>8.2f} {r['detect_seconds']:>9.2f} "
              f"{r['total_seconds']:>8.2f} {r['peak_rss_mb']:>9.1f} {r['recall']:>7.3f} {prec:>10}")
