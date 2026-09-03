"""
Finds candidate rings in the shared-attribute graph and scores them.

Pipeline per connected component:
  1. If the component is small/dense enough, treat it as one cluster.
  2. If it's large and diffuse (rare, but can happen when an infra edge
     slips through), refine with Louvain community detection so we don't
     lump unrelated sub-groups into one mega-cluster.
  3. Score every resulting cluster 0-100 using edge strength, size, and
     behavioral signal (return-rate spike, order-timing burstiness).
  4. Apply the dampening rule: clusters whose only evidence is one weak
     attribute (address) AND whose behavior looks ordinary are NOT flagged
     as rings, even if they're large — that's the hostel/office case.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import networkx as nx
import numpy as np
import pandas as pd

from .config import DetectorConfig
from .graph_builder import SHARED_ATTRIBUTES


@dataclass
class ClusterResult:
    cluster_id: str
    members: list[str]
    avg_edge_weight: float
    attribute_breakdown: dict[str, int]   # attr -> # of edges evidencing it
    return_rate: float
    timing_burst_score: float             # 0-1, higher = more synchronized
    n_orders: int                          # sample size behind return_rate
    velocity_flag: bool                    # True if account-creation-burst pattern detected
    velocity_info: str                     # human-readable detail behind velocity_flag
    suspicion_score: float
    flagged: bool
    dampened: bool
    reason: str = ""


def _behavioral_signals(orders_by_account: dict[str, pd.DataFrame], members: list[str],
                         observation_days: int = 60) -> tuple[float, float, int]:
    """
    orders_by_account must be a dict built ONCE via
    {aid: g for aid, g in orders_df.groupby("account_id", sort=False)} —
    not a shared indexed DataFrame. An earlier version used
    orders_indexed.loc[orders_indexed.index.intersection(members)],
    which looked like an improvement over .isin() but profiling at 150k+
    accounts showed Index.intersection() still costs proportional to the
    FULL index size internally (pandas.core.indexes.base._inner_indexer
    dominated at ~26s of a ~42s run) — not the small cluster being
    looked up. A plain dict gives true O(1) per-account lookup, so this
    function's cost is proportional to cluster size only, regardless of
    how many total orders or clusters exist.
    """
    frames = [orders_by_account[m] for m in members if m in orders_by_account]
    if not frames:
        return 0.0, 0.0, 0
    sub = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)
    return_rate = float(sub["is_return"].mean())
    n_orders = int(len(sub))

    # Timing burstiness: bucket orders into day-windows and measure how
    # concentrated they are (normalized Herfindahl-style index) vs. a
    # uniform spread. 0 = perfectly spread out, 1 = all on one day.
    counts = sub["order_day"].value_counts()
    total = counts.sum()
    if total == 0:
        return return_rate, 0.0, n_orders
    shares = counts / total
    hhi = float((shares ** 2).sum())
    uniform_hhi = 1.0 / observation_days
    burst_score = float(np.clip((hhi - uniform_hhi) / (1 - uniform_hhi), 0, 1))
    return return_rate, burst_score, n_orders


def _velocity_signal(accounts_df: pd.DataFrame, members: list[str],
                      cfg: DetectorConfig) -> tuple[bool, str]:
    """
    Detects the "burst of brand-new accounts hitting one address" pattern
    — the one signal an address-only cluster can carry even when its
    return rate and order timing look completely ordinary. Two
    conditions, both required:
      1. The cluster's accounts are, on average, recently created
         (mean account_age_days under velocity_age_ceiling_days).
      2. Those creation times are tightly clustered together (max-min
         spread under velocity_age_spread_ceiling_days) — ruling out a
         hostel/office population that simply accumulated members at
         random over months, some of whom happen to be new.
    """
    ages = accounts_df.loc[accounts_df["account_id"].isin(members), "account_age_days"]
    if ages.empty:
        return False, ""
    mean_age = float(ages.mean())
    spread = float(ages.max() - ages.min())
    flagged = mean_age <= cfg.velocity_age_ceiling_days and spread <= cfg.velocity_age_spread_ceiling_days
    info = (f"Accounts created in a {spread:.0f}-day window, averaging {mean_age:.1f} days old "
            f"— consistent with a burst of new signups, not an organically accumulated population.")
    return flagged, info if flagged else ""


def _score_cluster(avg_weight: float, size: int, return_rate: float, burst_score: float,
                    breakdown: dict[str, int], cfg: DetectorConfig, velocity_flag: bool = False) -> float:
    # Evidence strength: how much of the shared-attribute weight comes
    # from HARD identifiers (device/payout/phone) vs weak ones (IP/address).
    hard_edges = breakdown["device_fingerprint"] + breakdown["payout_account"] + breakdown["phone_number"]
    weak_edges = breakdown["ip_address"] + breakdown["delivery_address"]
    total_edges = max(hard_edges + weak_edges, 1)
    hard_ratio = hard_edges / total_edges

    size_score = float(np.clip(np.log2(size + 1) / np.log2(20), 0, 1))          # saturates ~20 members
    weight_score = float(np.clip(avg_weight / 6.0, 0, 1))                        # 6.0 ~= device+payout+phone
    behavior_score = float(np.clip(0.6 * return_rate / 0.5 + 0.4 * burst_score, 0, 1))

    # NOTE: size is intentionally the heaviest single component. A big
    # cluster of accounts touching each other at all is inherently more
    # interesting than a small one — which is exactly why a pure
    # size/behavior scorer over-fires on large legitimate clusters (a big
    # office, a hostel) and why the dampening rule below is load-bearing,
    # not decorative: run detect_rings() with dampening disabled to see it.
    score = 100 * (
        cfg.score_weight_hard_ratio * hard_ratio
        + cfg.score_weight_size * size_score
        + cfg.score_weight_edge_strength * weight_score
        + cfg.score_weight_behavior * behavior_score
    )
    # Velocity bonus: an address-only cluster of freshly-created accounts
    # is a distinct hard signal from everything above (which is why it's
    # additive, not folded into behavior_score) — a normal return rate
    # and flat order timing shouldn't be able to cancel it out.
    if velocity_flag:
        score += cfg.velocity_score_bonus
    return round(min(score, 100.0), 1)


def _explain(breakdown: dict[str, int], return_rate: float, size: int, velocity_flag: bool = False) -> str:
    shared = [a.replace("_", " ") for a, c in breakdown.items() if c > 0]
    shared_str = " and ".join(shared) if len(shared) <= 2 else ", ".join(shared[:-1]) + f", and {shared[-1]}"
    base = (f"{size} accounts share {shared_str}, with a "
            f"{return_rate:.0%} return rate across their orders.")
    if velocity_flag:
        base += " Nearly all of these accounts were created in a short burst shortly before use."
    return base


def _apply_policy(cluster_id: str, members: list[str], avg_weight: float, breakdown: dict[str, int],
                   return_rate: float, burst_score: float, n_orders: int, velocity_flag: bool,
                   velocity_info: str, score: float,
                   cfg: DetectorConfig, apply_dampening: bool) -> ClusterResult:
    """
    Turns raw cluster stats + suspicion score into a flag/dampen decision.
    Pulled out on its own so a threshold sweep (see evaluator.threshold_sweep)
    can re-run just this cheap step across many thresholds without
    re-clustering or re-scoring the whole graph.
    """
    flagged = score >= cfg.suspicion_threshold
    dampened = False

    # The velocity signal is deliberately treated as an override: it's
    # the one pattern an address-only cluster can carry even when return
    # rate and order timing look completely normal, so it must not be
    # erased by the "behavior looks normal" dampening check below.
    if apply_dampening and flagged and avg_weight <= cfg.weak_sharing_avg_weight_ceiling and not velocity_flag:
        # Statistical framing: treat "this cluster is legitimate" as the
        # null hypothesis. Only refuse to dampen (i.e. let a weak-evidence
        # flag stand) if we have real statistical evidence against that —
        # the LOWER bound of a one-sided CI on the true return rate still
        # exceeding the ceiling. A raw point estimate that drifts just
        # above the ceiling by sampling noise should NOT be enough to
        # flip a legitimate cluster into a false positive.
        if n_orders > 0:
            se = (return_rate * (1 - return_rate) / n_orders) ** 0.5
            return_rate_lower = max(0.0, return_rate - cfg.return_rate_ci_z * se)
        else:
            return_rate_lower = return_rate
        looks_normal = (return_rate_lower <= cfg.normal_return_rate_ceiling and
                         burst_score <= cfg.normal_timing_burst_ceiling)
        hard_evidence = breakdown["device_fingerprint"] + breakdown["payout_account"] + breakdown["phone_number"]
        if looks_normal and hard_evidence == 0:
            flagged = False
            dampened = True

    reason = _explain(breakdown, return_rate, len(members), velocity_flag)
    if dampened:
        reason += (" Flag suppressed: sharing is limited to a weak attribute "
                   "(likely a shared address such as a hostel/office) and "
                   "behavior is within normal bounds.")
    elif velocity_flag and flagged:
        reason += " " + velocity_info

    return ClusterResult(
        cluster_id=cluster_id,
        members=members,
        avg_edge_weight=round(avg_weight, 2),
        attribute_breakdown=breakdown,
        return_rate=round(return_rate, 3),
        timing_burst_score=round(burst_score, 3),
        n_orders=n_orders,
        velocity_flag=velocity_flag,
        velocity_info=velocity_info,
        suspicion_score=score,
        flagged=flagged,
        dampened=dampened,
        reason=reason,
    )


def detect_rings(g: nx.Graph, accounts_df: pd.DataFrame, orders_df: pd.DataFrame,
                  cfg: DetectorConfig = DetectorConfig(),
                  observation_days: int = 60,
                  apply_dampening: bool = True) -> list[ClusterResult]:
    results: list[ClusterResult] = []
    cluster_counter = 0

    components = [c for c in nx.connected_components(g) if len(c) >= cfg.min_cluster_size]

    # Built ONCE, not per cluster — see _behavioral_signals docstring for
    # why a plain dict (not a shared indexed DataFrame) is what makes
    # this actually O(cluster_size) per lookup.
    orders_by_account = {aid: grp for aid, grp in orders_df.groupby("account_id", sort=False)}

    for comp in components:
        subgraph = g.subgraph(comp)
        density = nx.density(subgraph)
        # Refine large, diffuse components with Louvain so unrelated
        # sub-clusters that happen to chain together aren't merged.
        if len(comp) > 25 and density < 0.3:
            communities = nx.community.louvain_communities(
                subgraph, weight="weight", resolution=cfg.louvain_resolution, seed=42
            )
        else:
            communities = [set(comp)]

        for members_set in communities:
            members = sorted(members_set)
            if len(members) < cfg.min_cluster_size:
                continue
            cluster_counter += 1
            cluster_id = f"cluster_{cluster_counter:03d}"

            # One subgraph build serves both avg edge weight and the
            # per-attribute breakdown, instead of two separate ones.
            member_subgraph = g.subgraph(members)
            edge_data = [d for _, _, d in member_subgraph.edges(data=True)]
            avg_weight = float(np.mean([d["weight"] for d in edge_data])) if edge_data else 0.0
            breakdown = {attr: 0 for attr in SHARED_ATTRIBUTES}
            for d in edge_data:
                for attr in d.get("shared_attributes", []):
                    breakdown[attr] += 1

            return_rate, burst_score, n_orders = _behavioral_signals(orders_by_account, members, observation_days)
            velocity_flag, velocity_info = _velocity_signal(accounts_df, members, cfg)
            score = _score_cluster(avg_weight, len(members), return_rate, burst_score, breakdown, cfg, velocity_flag)

            results.append(_apply_policy(cluster_id, members, avg_weight, breakdown,
                                          return_rate, burst_score, n_orders, velocity_flag, velocity_info,
                                          score, cfg, apply_dampening))

    results.sort(key=lambda r: r.suspicion_score, reverse=True)
    return results


def rescored_at_threshold(clusters: list[ClusterResult], threshold: float,
                           cfg: DetectorConfig, apply_dampening: bool = True) -> list[ClusterResult]:
    """
    Re-applies the flag/dampen policy at a different suspicion_threshold
    without re-clustering or re-scoring — this is what makes a full
    precision/recall sweep across thresholds cheap (see evaluator.py).
    Note: suspicion_score already has any velocity bonus baked in from
    the original detect_rings() call, so it's passed through unchanged.
    """
    swept_cfg = replace(cfg, suspicion_threshold=threshold)
    return [
        _apply_policy(c.cluster_id, c.members, c.avg_edge_weight, c.attribute_breakdown,
                       c.return_rate, c.timing_burst_score, c.n_orders, c.velocity_flag, c.velocity_info,
                       c.suspicion_score, swept_cfg, apply_dampening)
        for c in clusters
    ]


if __name__ == "__main__":
    from .data_generator import generate_dataset
    from .graph_builder import build_graph

    accounts_df, orders_df, gt = generate_dataset()
    g = build_graph(accounts_df)
    clusters = detect_rings(g, accounts_df, orders_df)

    print(f"Clusters found: {len(clusters)}  Flagged as rings: {sum(c.flagged for c in clusters)}  "
          f"Dampened: {sum(c.dampened for c in clusters)}")
    for c in clusters[:5]:
        print(f"  [{c.cluster_id}] score={c.suspicion_score} flagged={c.flagged} n={len(c.members)} :: {c.reason}")
