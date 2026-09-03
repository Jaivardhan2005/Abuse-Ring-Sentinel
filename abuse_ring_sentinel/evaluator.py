"""
Scores detector output against the known ground truth planted by the
generator. Reports recall, precision, false-positive cost, and — because
a demo with only cherry-picked wins isn't credible — a documented failure
case.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import EvaluationConfig
from .ring_detector import ClusterResult


@dataclass
class EvaluationReport:
    n_planted_rings: int
    n_planted_velocity_rings: int
    n_planted_legit_clusters: int
    rings_found: list[str]
    rings_missed: list[str]
    velocity_rings_found: list[str]
    velocity_rings_missed: list[str]
    true_positive_clusters: list[str]
    false_positive_clusters: list[str]
    recall: float
    classic_recall: float
    velocity_recall: float
    precision: float | None
    n_wrongly_flagged_accounts: int
    false_positive_cost_inr: float
    failure_case: str
    dampening_saves: list[dict] = field(default_factory=list)


def _match_ring(cluster: ClusterResult, ring_members: list[str], threshold: float) -> bool:
    overlap = len(set(cluster.members) & set(ring_members))
    return overlap / len(ring_members) >= threshold


def evaluate(clusters: list[ClusterResult], ground_truth: dict,
             cfg: EvaluationConfig = EvaluationConfig()) -> EvaluationReport:
    flagged = [c for c in clusters if c.flagged]
    velocity_rings = ground_truth.get("velocity_rings", {})

    # Classic (hard-identifier) rings and velocity (address+age-burst)
    # rings are both genuine planted abuse — combined for overall
    # recall/precision — but reported separately too, since "did the
    # velocity signal actually close the gap" is a claim worth checking
    # on its own, not just folded into one blended number.
    rings_found, rings_missed = [], []
    true_positive_clusters: list[str] = []
    for ring_id, members in ground_truth["rings"].items():
        match = next((c for c in flagged if _match_ring(c, members, cfg.match_overlap_threshold)), None)
        if match:
            rings_found.append(ring_id)
            true_positive_clusters.append(match.cluster_id)
        else:
            rings_missed.append(ring_id)

    velocity_rings_found, velocity_rings_missed = [], []
    for ring_id, members in velocity_rings.items():
        match = next((c for c in flagged if _match_ring(c, members, cfg.match_overlap_threshold)), None)
        if match:
            velocity_rings_found.append(ring_id)
            true_positive_clusters.append(match.cluster_id)
        else:
            velocity_rings_missed.append(ring_id)

    classic_recall = len(rings_found) / max(len(ground_truth["rings"]), 1)
    velocity_recall = (len(velocity_rings_found) / len(velocity_rings)) if velocity_rings else None
    total_planted = len(ground_truth["rings"]) + len(velocity_rings)
    total_found = len(rings_found) + len(velocity_rings_found)
    recall = total_found / max(total_planted, 1)

    # A flagged cluster is a false positive if it does NOT correspond to
    # any planted ring (classic or velocity) — i.e. it's a legitimate
    # look-alike we wrongly caught.
    false_positive_clusters = [c.cluster_id for c in flagged if c.cluster_id not in true_positive_clusters]
    precision = ((len(flagged) - len(false_positive_clusters)) / len(flagged)) if flagged else None

    legit_account_ids = {aid for members in ground_truth["lookalikes"].values() for aid in members}
    n_wrongly_flagged_accounts = sum(
        len(set(c.members) & legit_account_ids)
        for c in flagged if c.cluster_id in false_positive_clusters
    )
    fp_cost = n_wrongly_flagged_accounts * cfg.cost_per_false_positive_inr

    # Failure-case narrative: prefer a real miss/FP if one exists; else
    # report the closest near-miss so the writeup never claims a perfect,
    # untested system.
    if rings_missed or velocity_rings_missed:
        failure_case = f"Missed planted ring(s): classic={rings_missed}, velocity={velocity_rings_missed}."
    elif false_positive_clusters:
        failure_case = f"Wrongly flagged legitimate cluster(s): {false_positive_clusters}."
    else:
        near_misses = sorted(
            (c for c in clusters if not c.flagged and not c.dampened),
            key=lambda c: c.suspicion_score, reverse=True,
        )
        closest = near_misses[0] if near_misses else None
        if closest:
            failure_case = (
                f"No misses or false positives on this run, but {closest.cluster_id} "
                f"(score {closest.suspicion_score}, n={len(closest.members)}) sits closest "
                f"to the {cfg.match_overlap_threshold:.0%}-overlap flag threshold without "
                f"tripping it or the dampener — the honest margin of safety is thin here, "
                f"not zero."
            )
        else:
            failure_case = "No misses or false positives on this run."

    dampening_saves = [
        {
            "cluster_id": c.cluster_id,
            "size": len(c.members),
            "suspicion_score": c.suspicion_score,
            "reason": c.reason,
        }
        for c in clusters if c.dampened
    ]

    return EvaluationReport(
        n_planted_rings=len(ground_truth["rings"]),
        n_planted_velocity_rings=len(velocity_rings),
        n_planted_legit_clusters=len(ground_truth["lookalikes"]),
        rings_found=rings_found,
        rings_missed=rings_missed,
        velocity_rings_found=velocity_rings_found,
        velocity_rings_missed=velocity_rings_missed,
        true_positive_clusters=true_positive_clusters,
        false_positive_clusters=false_positive_clusters,
        recall=round(recall, 3),
        classic_recall=round(classic_recall, 3),
        velocity_recall=round(velocity_recall, 3) if velocity_recall is not None else None,
        precision=round(precision, 3) if precision is not None else None,
        n_wrongly_flagged_accounts=n_wrongly_flagged_accounts,
        false_positive_cost_inr=fp_cost,
        failure_case=failure_case,
        dampening_saves=dampening_saves,
    )


def sweep_thresholds(clusters: list[ClusterResult], ground_truth: dict, cfg,
                      det_cfg, thresholds: list[float] | None = None,
                      apply_dampening: bool = True) -> list[dict]:
    """
    Re-evaluates precision/recall/FP-cost at a range of suspicion
    thresholds, using the SAME clustered/scored data — only the
    flag/dampen decision changes. This is what "measured precision and
    recall" should look like: a curve showing the tradeoff, not one
    number picked in isolation. See ring_detector.rescored_at_threshold.
    """
    from .ring_detector import rescored_at_threshold

    if thresholds is None:
        thresholds = list(range(20, 91, 5))

    rows = []
    for t in thresholds:
        swept = rescored_at_threshold(clusters, float(t), det_cfg, apply_dampening)
        rep = evaluate(swept, ground_truth, cfg)
        rows.append({
            "threshold": t,
            "recall": rep.recall,
            "precision": rep.precision,
            "n_flagged": sum(c.flagged for c in swept),
            "n_wrongly_flagged_accounts": rep.n_wrongly_flagged_accounts,
            "false_positive_cost_inr": rep.false_positive_cost_inr,
        })
    return rows


if __name__ == "__main__":
    from .data_generator import generate_dataset
    from .graph_builder import build_graph
    from .ring_detector import detect_rings

    accounts_df, orders_df, gt = generate_dataset()
    g = build_graph(accounts_df)
    clusters = detect_rings(g, accounts_df, orders_df)
    report = evaluate(clusters, gt)
    precision_str = f"{report.precision:.0%}" if report.precision is not None else "N/A"
    print(f"Recall: {report.recall:.0%}  Precision: {precision_str}")
    print(f"FP cost: Rs {report.false_positive_cost_inr:,.0f}")
    print(f"Failure case: {report.failure_case}")
    print(f"Dampening saves: {report.dampening_saves}")
