"""
Basic correctness tests. Uses only the standard library's unittest so the
suite runs with zero extra dependencies:

    python3 -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from abuse_ring_sentinel.config import DetectorConfig, EvaluationConfig, GeneratorConfig
from abuse_ring_sentinel.data_generator import generate_dataset
from abuse_ring_sentinel.evaluator import evaluate
from abuse_ring_sentinel.graph_builder import build_graph
from abuse_ring_sentinel.ring_detector import detect_rings


class TestDataGenerator(unittest.TestCase):
    def test_max_group_size_exceeds_largest_adversarial_cluster(self):
        """
        Regression test for a real bug: DetectorConfig.max_group_size
        (graph_builder's cutoff for "this is infrastructure, not a
        ring") and GeneratorConfig.borderline_lookalike_size_range's
        upper bound were not kept in sync. When the borderline cluster's
        randomly-drawn size exceeded the cap, the entire cluster silently
        got zero edges instead of being tested — a single dev-seed run
        didn't happen to draw a large-enough size to expose this; an
        unrelated change to the RNG draw sequence did. This test makes
        the invariant explicit so it can't silently break again.
        """
        det_cfg = DetectorConfig()
        gen_cfg = GeneratorConfig()
        self.assertGreater(
            det_cfg.max_group_size, gen_cfg.borderline_lookalike_size_range[1],
            "max_group_size must exceed the largest adversarial cluster the "
            "generator can produce, or that cluster silently gets zero edges."
        )


    def test_reproducible_with_seed(self):
        a1, o1, gt1 = generate_dataset(GeneratorConfig(seed=7))
        a2, o2, gt2 = generate_dataset(GeneratorConfig(seed=7))
        self.assertTrue(a1.equals(a2))
        self.assertTrue(o1.equals(o2))
        self.assertEqual(gt1, gt2)

    def test_ring_members_share_at_least_one_hard_attribute(self):
        accounts_df, _, gt = generate_dataset(GeneratorConfig(seed=1, ring_attribute_noise=0.0))
        for ring_id, members in gt["rings"].items():
            sub = accounts_df[accounts_df["account_id"].isin(members)]
            # With zero noise every member shares the ring's device value.
            self.assertEqual(sub["device_fingerprint"].nunique(), 1)


class TestGraphBuilder(unittest.TestCase):
    def test_no_edges_between_fully_independent_accounts(self):
        cfg = GeneratorConfig(seed=2, n_rings=0, n_lookalike_clusters=0,
                               n_borderline_lookalike_clusters=0, n_velocity_rings=0,
                               n_background_accounts=50, background_collision_rate=0.0)
        accounts_df, _, _ = generate_dataset(cfg)
        g = build_graph(accounts_df)
        self.assertEqual(g.number_of_edges(), 0)

    def test_ring_forms_a_dense_component(self):
        accounts_df, _, gt = generate_dataset(GeneratorConfig(seed=3))
        g = build_graph(accounts_df)
        ring_members = next(iter(gt["rings"].values()))
        sub = g.subgraph(ring_members)
        # A planted ring should be (near) fully connected among itself.
        self.assertGreater(nx_density := __import__("networkx").density(sub), 0.5)


class TestEndToEnd(unittest.TestCase):
    def test_perfect_recall_zero_false_positives_on_default_config(self):
        accounts_df, orders_df, gt = generate_dataset(GeneratorConfig())
        g = build_graph(accounts_df)
        clusters = detect_rings(g, accounts_df, orders_df)
        report = evaluate(clusters, gt)
        self.assertEqual(report.recall, 1.0)
        self.assertEqual(report.precision, 1.0)
        self.assertEqual(report.n_wrongly_flagged_accounts, 0)

    def test_dampening_prevents_the_adversarial_false_positive(self):
        """
        Checks across several seeds (not just the default one) that
        dampening is load-bearing — i.e. that on at least one seed, the
        raw scorer alone would flag a weak-evidence cluster the
        dampening rule then correctly suppresses. A single-seed version
        of this test is fragile: an unrelated change to the RNG draw
        sequence (e.g. how many random calls address generation makes)
        shifts which seeds happen to land the adversarial cluster's score
        just above vs. just below the threshold, without the underlying
        behavior changing at all. Checking across seeds is the same fix
        this project already applied to the dampening rule itself.
        """
        seeds = [42, 1, 2, 3, 4, 5, 7, 17]
        any_suppressed = False
        for seed in seeds:
            accounts_df, orders_df, gt = generate_dataset(GeneratorConfig(seed=seed))
            g = build_graph(accounts_df)
            with_damp = detect_rings(g, accounts_df, orders_df, apply_dampening=True)
            without_damp = detect_rings(g, accounts_df, orders_df, apply_dampening=False)
            if sum(c.flagged for c in with_damp) < sum(c.flagged for c in without_damp):
                any_suppressed = True
                break
        self.assertTrue(any_suppressed,
                         f"Dampening should suppress at least one flag the raw scorer allows "
                         f"on at least one of seeds {seeds}.")

    def test_dampening_is_robust_to_sampling_noise_across_seeds(self):
        """
        Regression test for a real bug: an earlier version of the
        dampening rule compared the raw observed return rate to a fixed
        ceiling. A legitimate cluster whose TRUE return rate sits right
        at that ceiling crosses it by chance about half the time,
        producing false positives on roughly a third of random seeds.
        The fix uses a confidence-interval lower bound instead of the
        point estimate (see ring_detector._apply_policy).

        This asserts a FAILURE RATE, not zero failures on a fixed seed
        list — a 95%-confidence test has an inherent ~5% false-rejection
        rate BY DESIGN (see README Section 4a), so on any small fixed
        set of seeds, occasionally one will land in that band even with
        the fix correctly in place. Asserting exactly 0/N failures on a
        small N was itself a bug in an earlier version of this test — it
        had roughly a 1-in-4 chance of failing on 5 seeds even when the
        fix was working correctly. A large seed sample with a generous
        threshold (well above the ~5% expected rate, far below the old
        rule's ~50%+ rate) is the statistically honest version of this
        check.
        """
        from abuse_ring_sentinel.robustness import run_multi_seed, summarize
        seeds = list(range(1, 31))
        rows = run_multi_seed(seeds, GeneratorConfig(), DetectorConfig(), EvaluationConfig())
        summary = summarize(rows)
        failure_rate = summary["runs_with_false_positives"] / len(seeds)
        self.assertLess(failure_rate, 0.20,
                         f"Expected well under 20% of {len(seeds)} seeds to show false "
                         f"positives (theoretical rate ~5%); got {failure_rate:.0%} "
                         f"(failing seeds: {summary['failing_seeds']}). This threshold is "
                         f"generous specifically so it only fires on a real regression, "
                         f"not routine sampling variance.")

    def test_velocity_signal_catches_address_only_ring_that_evades_other_signals(self):
        """
        Regression test for a documented, deliberate gap: a coordinated
        ring that shares ONLY a delivery address, with return rate and
        order timing kept statistically indistinguishable from an
        innocent look-alike cluster, is invisible to every signal except
        account-creation velocity (a burst of brand-new accounts hitting
        one address). Without the velocity signal this ring scores well
        below the flag threshold (~35-38/100) and is missed entirely.
        With it, the same ring is flagged, and classic-ring recall and
        precision are unaffected — the fix is additive.
        """
        from dataclasses import replace as _replace
        accounts_df, orders_df, gt = generate_dataset(GeneratorConfig())
        g = build_graph(accounts_df)

        cfg_off = _replace(DetectorConfig(), velocity_score_bonus=0.0, velocity_age_ceiling_days=-1.0)
        clusters_off = detect_rings(g, accounts_df, orders_df, cfg_off)
        report_off = evaluate(clusters_off, gt)
        self.assertEqual(report_off.velocity_recall, 0.0,
                          "Sanity check: velocity rings should be undetectable with the signal disabled.")

        clusters_on = detect_rings(g, accounts_df, orders_df, DetectorConfig())
        report_on = evaluate(clusters_on, gt)
        self.assertEqual(report_on.velocity_recall, 1.0,
                          "Velocity signal should catch every planted velocity ring.")
        self.assertEqual(report_on.classic_recall, 1.0,
                          "Velocity signal should not affect classic-ring recall.")
        self.assertEqual(report_on.precision, 1.0,
                          "Velocity signal should not introduce false positives.")


class TestBenchmark(unittest.TestCase):
    def test_scaled_config_preserves_ring_size_ranges(self):
        """
        benchmark.scaled_config() must scale POPULATION COUNTS (more
        rings, more background accounts) without changing individual
        ring SIZE ranges — a ring shouldn't get bigger just because the
        platform has more users. This is the assumption the whole scale
        benchmark's recall/precision numbers depend on being true.
        """
        from abuse_ring_sentinel.benchmark import scaled_config
        base = GeneratorConfig()
        scaled = scaled_config(14_000)  # 10x the baseline background size
        self.assertEqual(scaled.ring_size_range, base.ring_size_range)
        self.assertEqual(scaled.velocity_ring_size_range, base.velocity_ring_size_range)
        self.assertGreater(scaled.n_rings, base.n_rings)

    def test_run_benchmark_reports_consistent_counts(self):
        """Small, fast run (no real timing claims) — just checks the
        benchmark harness itself produces internally consistent output
        (recall in [0,1], accounts match what was requested)."""
        from abuse_ring_sentinel.benchmark import run_benchmark
        result = run_benchmark(n_background=200)
        self.assertGreaterEqual(result["n_accounts"], 200)
        self.assertGreaterEqual(result["recall"], 0.0)
        self.assertLessEqual(result["recall"], 1.0)
        self.assertGreater(result["total_seconds"], 0.0)


class TestDistributionShift(unittest.TestCase):
    def test_baseline_shift_matches_unshifted_default_config(self):
        """The 'baseline (unshifted)' entry in SHIFTS must apply zero
        overrides — i.e. it's a true control, not an accidental shift.
        If this drifts, the whole table's "9/10 shifts hold" framing in
        the README would be comparing against a moving baseline."""
        from abuse_ring_sentinel.distribution_shift import SHIFTS
        self.assertEqual(SHIFTS["baseline (unshifted)"], {})

    def test_all_shift_overrides_are_valid_generator_config_fields(self):
        """Every key in every SHIFTS entry must be a real GeneratorConfig
        field — a typo'd key would silently be ignored by dataclasses.replace
        in some Python versions or error in others; this catches it either way."""
        from abuse_ring_sentinel.distribution_shift import SHIFTS
        valid_fields = set(GeneratorConfig.__dataclass_fields__.keys())
        for shift_name, overrides in SHIFTS.items():
            for key in overrides:
                self.assertIn(key, valid_fields,
                               f"'{key}' in shift '{shift_name}' is not a real GeneratorConfig field.")

    def test_run_distribution_shifts_returns_a_row_per_shift(self):
        from abuse_ring_sentinel.distribution_shift import SHIFTS, run_distribution_shifts
        rows = run_distribution_shifts(seed=1)
        self.assertEqual(len(rows), len(SHIFTS))
        for row in rows:
            self.assertGreaterEqual(row["recall"], 0.0)
            self.assertLessEqual(row["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
