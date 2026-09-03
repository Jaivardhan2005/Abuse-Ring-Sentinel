"""
Central configuration for Abuse-Ring Sentinel.

Every tunable knob lives here so the pipeline is reproducible and the
README's "how to reproduce these numbers" claim is actually true.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GeneratorConfig:
    # seed=42 is the DEV seed: every threshold and weight in
    # DetectorConfig below was chosen by looking at results on this seed.
    # Reported headline metrics should come from a *different* seed the
    # detector was never tuned against — see HELD_OUT_SEED and
    # main.py's held-out evaluation run.
    seed: int = 42

    n_background_accounts: int = 1400
    n_rings: int = 8
    ring_size_range: tuple[int, int] = (5, 16)
    n_lookalike_clusters: int = 4
    lookalike_size_range: tuple[int, int] = (6, 20)

    # One deliberately adversarial legitimate cluster: a large office that
    # shares a delivery address AND happens to have a mild, real return
    # spike (a seasonal sale, a bad batch of a product) — big enough and
    # active enough that a size/behavior-sensitive scorer alone would
    # flag it. This is the case the dampening rule exists to catch, and
    # we report honestly on whether it does.
    n_borderline_lookalike_clusters: int = 1
    borderline_lookalike_size_range: tuple[int, int] = (30, 42)
    borderline_return_rate_mean: float = 0.25
    borderline_timing_burst_mean_days: int = 4  # orders cluster within this window

    # Velocity rings: coordinated abuse accounts that share ONLY a
    # delivery address — no device/payout/phone reuse — and whose
    # behavior (return rate, order timing) is deliberately kept
    # statistically normal, indistinguishable from the address-only
    # look-alike clusters above on every signal Sections 1-6 use. The
    # only tell is non-behavioral: every member's account was created
    # within a short window shortly before use (real customers who
    # innocently share a hostel/office address accumulate at random over
    # months; a burst of brand-new accounts hitting one address in days
    # is a distinct pattern). This is the case flagged as an unsolved gap
    # in the project's own limitations section — see ring_detector.py's
    # velocity signal for the fix.
    n_velocity_rings: int = 2
    velocity_ring_size_range: tuple[int, int] = (6, 14)
    velocity_account_age_max_days: int = 10       # every member created within this many days...
    velocity_account_age_spread_days: int = 5     # ...and clustered within this tight a window

    # Probability a ring member's shared attribute is "noised out" (uses a
    # unique value instead of the shared one) — real rings are never
    # perfectly clean, and a detector that only works on perfectly clean
    # rings is not credible.
    ring_attribute_noise: float = 0.15

    # Probability that two unrelated background accounts accidentally
    # collide on a single weak attribute (e.g. two strangers on the same
    # ISP IP, or a coincidental address collision). Realistic background
    # noise the detector must not over-react to.
    background_collision_rate: float = 0.02

    # Days of observation window used to synthesize order timing.
    observation_days: int = 60


@dataclass(frozen=True)
class DetectorConfig:
    # Attribute types and how much evidence each contributes to an edge.
    # Device + payout account are hard to share by accident; address and
    # IP are weaker/more incidental.
    attribute_weights: dict = field(
        default_factory=lambda: {
            "device_fingerprint": 3.0,
            "payout_account": 3.0,
            "phone_number": 2.0,
            "ip_address": 1.0,
            "delivery_address": 1.0,
        }
    )

    # Minimum combined edge weight to keep an edge at all (prunes one-off
    # coincidental collisions before clustering even starts).
    min_edge_weight: float = 1.0

    # Community detection resolution for networkx's Louvain implementation.
    louvain_resolution: float = 1.1

    # A cluster needs at least this many members to be considered at all.
    min_cluster_size: int = 3

    # Suspicion score (0-100) at/above which a cluster is flagged as a ring.
    suspicion_threshold: float = 55.0

    # Weights of the four suspicion-score components. Must be
    # interpretable on their own — see ring_detector._score_cluster.
    score_weight_hard_ratio: float = 0.15
    score_weight_size: float = 0.45
    score_weight_edge_strength: float = 0.20
    score_weight_behavior: float = 0.20

    # --- Dampening rule ---
    weak_sharing_avg_weight_ceiling: float = 1.5
    normal_return_rate_ceiling: float = 0.25
    normal_timing_burst_ceiling: float = 0.35
    # A single observed return rate is a noisy statistic on a finite
    # sample of orders — a cluster whose TRUE rate sits right at the
    # ceiling will cross it by chance roughly half the time. Instead of
    # gating on the raw point estimate, the detector gates on the LOWER
    # bound of a one-sided confidence interval (Wald approximation) so
    # sampling noise around a genuinely-normal rate doesn't flip the
    # decision (see ring_detector._apply_policy). z=1.645 ~= one-sided
    # 95% confidence.
    return_rate_ci_z: float = 1.645

    # Groups sharing a single attribute larger than this are treated as
    # infrastructure (a NAT gateway, a courier hub) rather than a ring
    # and get no edges at all (see graph_builder.py). MUST stay above the
    # largest deliberately-adversarial cluster the generator can produce
    # (GeneratorConfig.borderline_lookalike_size_range's upper bound,
    # currently 42) — this cap silently zeroed out that entire cluster's
    # edges in an earlier version where the two values weren't kept in
    # sync, which is exactly the kind of bug that doesn't show up in a
    # single dev-seed run and only surfaces when something (a new seed,
    # a scale test) happens to draw a size past the cap. See
    # tests/test_pipeline.py::test_max_group_size_exceeds_largest_adversarial_cluster.
    max_group_size: int = 60

    # --- Velocity signal ---
    # Detection-side thresholds for the account-creation-velocity pattern
    # (see GeneratorConfig.n_velocity_rings). Deliberately a bit looser
    # than the generator's own values (10 days / 5-day spread) so the
    # detector isn't just pattern-matching the exact generator constants.
    velocity_age_ceiling_days: float = 21.0        # cluster's mean account age must be under this
    velocity_age_spread_ceiling_days: float = 10.0  # and its age spread (max-min) under this
    # Suspicion-score points added when the velocity pattern is present
    # (on top of the normal 0-100 score) — enough on its own to clear the
    # suspicion_threshold for a cluster that would otherwise score in the
    # 20s-40s range (address-only evidence, normal behavior).
    velocity_score_bonus: float = 35.0


@dataclass(frozen=True)
class EvaluationConfig:
    # Overlap (intersection / planted-ring-size) required for a detected
    # cluster to "count" as having found a given planted ring.
    match_overlap_threshold: float = 0.6
    # Assumed lifetime value (INR) lost per legitimate customer wrongly
    # flagged/banned. Stated explicitly rather than buried in code.
    cost_per_false_positive_inr: float = 1800.0


GEN_CFG = GeneratorConfig()
DET_CFG = DetectorConfig()
EVAL_CFG = EvaluationConfig()

# The held-out seed: a population the detector's thresholds/weights were
# NEVER looked at while being tuned. Every number in DetectorConfig above
# was picked against GEN_CFG (seed=42) alone; HELD_OUT_SEED exists so the
# reported headline metrics aren't just "did it memorize the dev set".
HELD_OUT_SEED = 2026
