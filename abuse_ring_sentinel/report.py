"""
Assembles a single JSON-serializable payload describing the whole run:
graph (nodes+edges), clusters, evaluation metrics, and baseline
comparison. This is the one artifact both the markdown report and the
HTML dashboard are built from, so the two can never disagree.
"""
from __future__ import annotations

import json

import networkx as nx
import pandas as pd

from .baseline_detector import naive_address_flags
from .evaluator import EvaluationReport
from .ring_detector import ClusterResult


def build_payload(accounts_df: pd.DataFrame, g: nx.Graph, clusters: list[ClusterResult],
                   report: EvaluationReport, ground_truth: dict) -> dict:
    account_lookup = accounts_df.set_index("account_id").to_dict(orient="index")

    member_to_cluster: dict[str, str] = {}
    for c in clusters:
        for m in c.members:
            member_to_cluster[m] = c.cluster_id

    nodes = []
    for acc_id, attrs in account_lookup.items():
        cluster_id = member_to_cluster.get(acc_id)
        cluster = next((c for c in clusters if c.cluster_id == cluster_id), None)
        if cluster is None:
            status = "unclustered"
        elif cluster.flagged and cluster.velocity_flag:
            status = "flagged_velocity"
        elif cluster.flagged:
            status = "flagged_ring"
        elif cluster.dampened:
            status = "dampened_saved"
        else:
            status = "clustered_benign"
        nodes.append({
            "id": acc_id,
            "name": attrs["name"],
            "cluster": cluster_id,
            "status": status,
            "ground_truth": attrs["ground_truth_group"],
            "suspicion_score": cluster.suspicion_score if cluster else 0.0,
        })

    # Only include nodes that have at least one edge (isolated singletons
    # would just be dead weight on a force graph with 1500+ accounts).
    non_isolated = {n for n in g.nodes() if g.degree(n) > 0}
    nodes = [n for n in nodes if n["id"] in non_isolated]

    links = [
        {"source": u, "target": v, "weight": d["weight"], "attributes": d["shared_attributes"]}
        for u, v, d in g.edges(data=True)
    ]

    cluster_summaries = [
        {
            "cluster_id": c.cluster_id,
            "size": len(c.members),
            "suspicion_score": c.suspicion_score,
            "flagged": c.flagged,
            "dampened": c.dampened,
            "velocity_flag": c.velocity_flag,
            "avg_edge_weight": c.avg_edge_weight,
            "return_rate": c.return_rate,
            "timing_burst_score": c.timing_burst_score,
            "attribute_breakdown": c.attribute_breakdown,
            "reason": c.reason,
        }
        for c in clusters
    ]

    baseline_flags = naive_address_flags(accounts_df)
    ring_ids = {aid for m in ground_truth["rings"].values() for aid in m}
    legit_ids = {aid for m in ground_truth["lookalikes"].values() for aid in m}
    baseline_summary = {
        "n_flagged_groups": len(baseline_flags),
        "rings_caught": sum(1 for f in baseline_flags if set(f["members"]) & ring_ids),
        "n_rings_total": len(ground_truth["rings"]),
        "legit_accounts_wrongly_flagged": sum(len(set(f["members"]) & legit_ids) for f in baseline_flags),
    }

    metrics = {
        "n_accounts": len(accounts_df),
        "n_orders_analyzed": None,  # filled by caller if desired
        "n_planted_rings": report.n_planted_rings,
        "n_planted_velocity_rings": report.n_planted_velocity_rings,
        "n_planted_legit_clusters": report.n_planted_legit_clusters,
        "recall": report.recall,
        "classic_recall": report.classic_recall,
        "velocity_recall": report.velocity_recall,
        "precision": report.precision,
        "rings_found": report.rings_found,
        "rings_missed": report.rings_missed,
        "velocity_rings_found": report.velocity_rings_found,
        "velocity_rings_missed": report.velocity_rings_missed,
        "false_positive_clusters": report.false_positive_clusters,
        "n_wrongly_flagged_accounts": report.n_wrongly_flagged_accounts,
        "false_positive_cost_inr": report.false_positive_cost_inr,
        "failure_case": report.failure_case,
        "dampening_saves": report.dampening_saves,
        "baseline_comparison": baseline_summary,
    }

    return {
        "nodes": nodes,
        "links": links,
        "clusters": cluster_summaries,
        "metrics": metrics,
    }


def write_payload(payload: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
