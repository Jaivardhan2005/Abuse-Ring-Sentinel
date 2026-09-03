# Abuse-Ring Sentinel
### Graph-based coordinated fraud-ring detection — Razorpay AI Buildathon, Track 02 ("AI Risk Manager")

Individual fraudulent transactions look clean in isolation. Fraud **rings**
only become visible when you look at how accounts are *connected* to each
other. Abuse-Ring Sentinel finds coordinated abuse rings — not lone bad
actors — by turning accounts and their shared identifiers into a graph,
clustering it, scoring each cluster's suspicion level, and reporting
honestly measured precision/recall/false-positive-cost numbers across
held-out data, not a single cherry-picked demo case.

**Track 02 alignment, explicitly:** the track brief asks for "a working
detector... with measured precision and recall on a held-out test set,"
"honest metrics including false-positive cost," and is strictly
defense-only. Sections 3-4 below are built around exactly that bar, not
just a demo — including a real bug this evaluation process found, fixed,
and re-measured (Section 4), and a previously-documented detection gap
that's now closed and quantified (Section 2, item 5).

---

## 1. The problem

Most fraud/return-abuse detectors score **one transaction at a time**: is
this amount weird, is this location weird, is this timing weird. That
catches lone bad actors but misses **organized abuse** — a small group of
people running dozens of "different" accounts that secretly share a
device, a delivery address, a UPI handle, or a bank account to farm promo
credits, fake returns, or chargebacks.

The hard part isn't finding shared attributes — it's not overreacting to
them. A hostel or an office building will legitimately produce dozens of
accounts sharing one delivery address. A detector that treats "shared
address" as guilt will bury investigators in false positives and annoy
real customers. Sentinel is built around that tension explicitly.

## 2. What it does

1. **Generates** a synthetic account/order population with a *known*
   ground truth: planted coordinated rings, planted innocent look-alike
   clusters (a hostel), and one deliberately adversarial case — a large,
   legitimate office cluster with a genuine mild return spike, sized and
   active enough that a naive detector would flag it.
2. **Builds a graph**: nodes are accounts, edges connect accounts that
   share a device fingerprint, payout account (UPI/bank), phone number,
   IP address, or delivery address — weighted by how strong that evidence
   is (a shared device is worth far more than a shared address).
3. **Detects rings**: connected-components + Louvain community detection
   on dense, diffuse components; each cluster gets a 0-100 suspicion
   score from evidence strength, size, edge weight, and behavioral signal
   (return-rate spikes, synchronized order timing).
4. **Dampens false alarms statistically, not just heuristically**: a
   cluster whose only evidence is a weak attribute (address) gets its
   flag suppressed unless there's real statistical evidence — a
   confidence-interval test, not a raw point estimate — that its behavior
   is abnormal. Section 4 explains why the point-estimate version of this
   rule was a real bug.
5. **Catches address-only rings that hide behind normal behavior**: a
   coordinated ring can share only a delivery address and deliberately
   keep its return rate and order timing statistically indistinguishable
   from an innocent look-alike cluster. The one thing it can't easily
   fake is *when* its accounts were created — a burst of brand-new
   accounts hitting one address in a matter of days, versus a legitimate
   population (a hostel, an office) that accumulates members at random
   over months. A dedicated velocity signal checks exactly this pattern,
   and overrides the dampening rule above so it can't be suppressed as
   "looks normal." This closes a gap the project's own limitations
   section originally flagged as unsolved — see Section 3 for the numbers.
6. **Evaluates itself three ways**: a single dev-seed run, a held-out
   seed never used to tune anything, and a 15-seed robustness sweep — plus
   a full precision/recall-vs-threshold curve, not one operating point.
7. **Visualizes** the whole network as an interactive investigation
   console (`outputs/dashboard.html`) — click any case file to see the
   network light up and read the plain-English reason it was (or wasn't)
   flagged. A six-part evidence appendix (Exhibits A-F) surfaces the
   naive-baseline comparison, held-out/robustness results, the dampening
   bug fix, the distribution-shift test, the scale benchmark, and the
   full precision/recall-vs-threshold curve directly in the tool — three
   of these as actual charts (a line chart, two bar charts), not just
   numbers in a table.

## 3. Results

**Dev seed (42) — used while building the detector:**

| Metric | Sentinel | Naive baseline* |
|---|---|---|
| Classic rings found | **8 / 8 (100%)** | 0 / 8 (0%) |
| Velocity rings found | **2 / 2 (100%)** | 0 / 2 (0%) |
| Precision | **100%** | — (flags 6 groups, none are real rings) |
| Legit accounts wrongly flagged | **0** | 81 |
| False-positive cost avoided | **Rs 0 lost** | Rs 145,800 (at Rs 1,800/account assumed LTV) |

\* *Naive baseline: "cluster by shared delivery address, flag any group of
8+". This is the first thing most teams reach for — and it fails in
**every** direction: it misses every classic ring (they don't share
addresses), misses every velocity ring (address-sharing alone isn't
enough — see below), and flags every large legitimate address cluster
(hostels, offices) as abuse.*

**Velocity signal, isolated** (same dev seed, signal switched off vs. on
— everything else identical):

| | Velocity-ring recall | Classic-ring recall | Precision |
|---|---|---|---|
| Signal off | **0%** (0/2) | 100% | 100% |
| Signal on | **100%** (2/2) | 100% | 100% |

Both planted velocity rings score 33.5 and 37.8 out of 100 without the
signal — well under the 55.0 flag threshold, so they're missed entirely,
not just under-scored. With the signal, they score 68.5 and 72.8 and are
flagged cleanly. Classic-ring recall and precision are unchanged either
way — this is a strictly additive fix, not a tradeoff. Reproduce with
`tests/test_pipeline.py::test_velocity_signal_catches_address_only_ring_that_evades_other_signals`.

**Held-out seed (2026) — never looked at while choosing any threshold or
weight in `config.py`:**

| Metric | Value |
|---|---|
| Recall | **100%** (classic + velocity combined) |
| Precision | **100%** |
| False-positive cost | **Rs 0** |

**15-seed robustness sweep** (independent synthetic populations, same
fixed config, no per-seed tuning): **14/15 seeds fully clean** — 100% mean
recall, 99.4% mean precision. The one non-clean seed (17) shows 90.9%
precision — this is the expected residual failure rate of a 95%-confidence
statistical test (Section 4a), not a new bug; see the 40-seed replay below
for the calibrated rate this should land near.

**Precision/recall vs. suspicion threshold** (dev seed, `outputs/threshold_sweep.json`):
recall and precision are both 100% for every threshold from 20 through 65;
recall degrades gracefully above that (90% at threshold 70, 70% at 75, 60%
at 80, 20% at 85, 0% at 90) as the bar gets too high for the weaker rings
and velocity rings to clear — precision stays at 100% throughout the
entire sweep, meaning every threshold miss is a false negative, never a
false positive. The wide flat plateau at 100%/100% — not a knife-edge
single point — is what makes 55.0 a safe default rather than a lucky pick.
Reproduce with `python3 -m abuse_ring_sentinel.evaluator` or inspect the
JSON directly.

## 4. Two real bugs/gaps this evaluation process found (and fixed)

### 4a. The dampening rule's sampling-noise bug

The first version of the dampening rule compared a cluster's **observed**
return rate directly to a fixed "looks normal" ceiling (25%). The
deliberately-adversarial borderline cluster in the generator has a
*true* return rate of 25% — right at that ceiling by design, to stress-test
the rule. Running only the dev seed, that looked fine (100%/100%). Running
a 10-seed sweep exposed the problem: on 3 of 10 seeds, sampling noise
pushed the *observed* rate a few points above 25% purely by chance, the
rule refused to dampen, and a legitimate 33-40 person cluster got wrongly
flagged (precision dropped to 88.9%, ~Rs 70K in false-positive cost).

**The fix** (`ring_detector.py::_apply_policy`): treat "this cluster is
legitimate" as a null hypothesis, and only refuse to dampen when there's
real statistical evidence against it — the *lower bound* of a one-sided
confidence interval on the return rate, not the raw point estimate. A
cluster whose true rate is legitimately at the ceiling now stays
correctly dampened regardless of which way sampling noise happened to
push it that day; a cluster whose true rate is genuinely high (rings run
~45%) still clears the bar easily.

**Measured, not just anecdotal:** `robustness.py::replay_dampening_fix`
reruns both the old point-estimate rule and the new confidence-interval
rule against identical underlying cluster data across 40 independent
seeds. Result:

| | False-positive rate | Clean seeds |
|---|---|---|
| Old rule (point estimate) | **57.5%** | 17/40 |
| New rule (CI lower bound) | **5.0%** | 38/40 |

That 5% isn't an arbitrary residual — it lines up almost exactly with the
expected false-rejection rate of a one-sided 95% confidence interval by
construction (`return_rate_ci_z = 1.645` in `config.py`), which is the
kind of clean number you want to see when a statistical fix is actually
doing what it claims. `tests/test_pipeline.py::test_dampening_is_robust_to_sampling_noise_across_seeds`
locks the fixed behavior in as a regression test. Reproduce the full
replay with `python3 -m abuse_ring_sentinel.robustness`.

### 4b. The velocity-ring detection gap

Documented in Section 2/3 above and originally called out as an unsolved
limitation: an address-only ring with deliberately normal behavior was
completely invisible to every signal in the first version of the
detector (scores in the mid-30s against a 55.0 threshold — not a
near-miss, a clean miss). The account-creation-velocity signal
(Section 2, item 5) closes this specific gap, measured at 0% → 100%
recall with no cost to classic-ring recall or precision.

Both of these are the actual failure cases + fixes this project surfaced
through its own testing, not synthetic near-misses constructed after the
fact.

## 5. Scale & performance — measured, not assumed

Everything above ran on ~1,600 accounts in under a second. That's fine
for evaluation but tells you nothing about whether this holds up at real
scale, so it was benchmarked directly (`abuse_ring_sentinel/benchmark.py`,
single-CPU sandbox — see the honest ceiling noted below).

| Accounts | Orders | Total time | Peak memory | Recall | Precision |
|---|---|---|---|---|---|
| 1,592 | 7,976 | 0.34s | 91MB | 100% | 100% |
| 11,349 | 56,561 | 2.91s | 150MB | 100% | 100% |
| 113,734 | 568,454 | 40.75s | 403MB | 100% | 99.6% |
| 170,717 | 853,318 | 77.96s | 1,109MB | 100% | 99.5% |

**Three real bugs found by actually running this at scale, not by
inspection:**

1. **Address-space collision.** The original synthetic address generator
   (10 cities x 10 streets x 999 house numbers, ~100k combinations) had
   expected accidental collisions in the *thousands* at 100k+ accounts —
   confirmed by direct birthday-paradox math, not estimation. A random
   background account could land on the exact same address as a planted
   cluster purely by chance, silently contaminating that cluster's ground
   truth. Fixed by widening the address space past 10^13 combinations
   (`data_generator.py::_rand_address`).
2. **The same class of bug in a different field.** After fixing addresses,
   100k-scale runs still showed a residual ~1% precision drop. Diagnosed
   by directly inspecting a contaminated cluster's rows: a background
   account and a genuine ring member had drawn the *identical* UPI payout
   handle (`9874452@upi`) — the original 7-digit UPI ID pool (~9 million
   combinations) was too small at scale. Widened to match `BANKACC`'s
   10-digit pool. This is the same underlying lesson as the address bug,
   found independently because it lived in a different function.
3. **A latent bug the above exposed.** Fixing the address generator
   shifted the shared RNG's draw sequence, which happened to expose that
   `graph_builder.py`'s infrastructure-detection cap (40) was *smaller*
   than the generator's largest adversarial cluster (42) — meaning that
   cluster could silently get zero edges and never be tested at all, on
   certain seeds, without any error. Fixed by raising the cap and adding
   `tests/test_pipeline.py::test_max_group_size_exceeds_largest_adversarial_cluster`
   so the two values can't silently drift apart again.

**Two real performance bugs, found by profiling (`cProfile`), not
guessing:**

1. `_attribute_breakdown` re-scanned **every edge in the entire graph**
   for **every single cluster** — O(n_clusters x total_edges). At 100k
   accounts this alone cost ~91 seconds. Fixed by scoping it to
   `g.subgraph(members)`, proportional to cluster size instead of graph
   size.
2. `_behavioral_signals` re-filtered **the entire orders table** for
   every cluster. A first attempt (a sorted-index `.intersection()` call)
   looked like a fix but profiling showed it still cost proportional to
   the *full* index internally. The actual fix: group orders into a
   plain `dict[account_id -> DataFrame]` once, giving true O(1)
   per-account lookup.

Combined, these two cut `detect_rings`'s share of a 100k-account run from
roughly 91s to roughly 11-24s (varies by run) — not by design, but as a
direct, measured consequence of profiling instead of assuming.

**The honest ceiling:** this sandbox has 1 CPU and ~3.9GB RAM. Runs above
~200k accounts didn't complete within this environment's execution time
limits during testing. Data generation (pure-Python row-by-row order
synthesis) is now the largest remaining cost at scale, and `detect_rings`
still shows a somewhat super-linear growth curve (170,700 accounts took
1.9x longer than 113,700 accounts would predict linearly) that wasn't
fully root-caused before time ran out — see Section 9 for what that
implies about production readiness.

## 6. Distribution-shift stress test — does tuning generalize?

Section 3's held-out and multi-seed results all use the *same*
population-generation distribution the detector was tuned against —
different random seeds, but the same ring-size ranges, the same noise
rates. That leaves open a real question: did tuning `DetectorConfig`'s
weights and thresholds overfit to that one specific shape of population?

`abuse_ring_sentinel/distribution_shift.py` answers this directly: it
generates populations that deliberately differ from the original in one
specific way each — smaller/larger rings, noisier rings, more background
noise, a wider velocity-ring age window, more lookalike clusters, a
shorter observation window — and evaluates the **same fixed
DetectorConfig**, never re-tuned per shift, against each.

| Shift | Recall | Precision |
|---|---|---|
| Baseline (unshifted) | 100% | 100% |
| Smaller rings (3-6 members) | 100% | 100% |
| Larger rings (18-30 members) | 100% | 100% |
| Noisier rings (35% attribute noise) | 100% | 100% |
| **Very noisy rings (50% attribute noise)** | **90.0%** | **90.0%** |
| More background collisions (8%) | 100% | 100% |
| Smaller velocity rings (3-5 members) | 100% | 100% |
| Wider velocity age window (18 days) | 100% | 100% |
| More lookalike clusters (12x) | 100% | 100% |
| Shorter observation window (21 days) | 100% | 100% |

9 of 10 shifts hold perfectly with zero re-tuning. The one that doesn't —
50% independent noise per hard attribute — was diagnosed, not just
observed: at that noise level, individual ring members share almost
nothing pairwise (one missed ring's 12 members had 9 distinct devices
among them), so the graph itself fragments before scoring ever gets
involved. That's a **connectivity limit, not a scoring bug**, and it
degrades gracefully (90%, not 0%) rather than catastrophically. Reproduce
with `python3 -m abuse_ring_sentinel.distribution_shift`.

## 7. Architecture

```
Data Generator (data_generator.py)
    synthetic accounts/orders + planted classic rings + planted
    velocity rings + planted look-alikes + one adversarial case
        |
        v
Graph Builder (graph_builder.py)
    nodes = accounts, edges = shared device / payout / phone / IP /
    address, evidence-weighted
        |
        v
Ring Detector (ring_detector.py)
    connected components + Louvain refinement, suspicion scoring,
    CI-based dampening rule, account-creation-velocity signal
        |
        +--> Evaluator (evaluator.py): precision/recall/FP cost
        |      (classic + velocity, separately and combined),
        |      threshold sweep
        +--> Naive baseline (baseline_detector.py): comparison point
        +--> Multi-seed robustness sweep + dampening-rule bug replay
        |      (robustness.py)
        |
        v
Report + Dashboard (report.py, visualize.py)
    JSON payload -> self-contained interactive D3 dashboard,
    no server needed
```

## 8. How to run it

```bash
pip install -r requirements.txt
python3 main.py
```

This runs all evaluations (dev seed, held-out seed, 15-seed robustness
sweep, 40-seed dampening-rule bug replay) end to end. Outputs land in
`outputs/`:
- `accounts.csv`, `orders.csv` - the dev-seed synthetic dataset
- `dashboard_data.json` - full graph + clusters + every evaluation result
- `dashboard.html` - **open this in a browser**: interactive investigation console
- `threshold_sweep.json` - precision/recall at every threshold from 20-90
- `metrics_summary.json` - every number in the tables above, machine-readable

Run `python3 -m unittest discover -s tests` for the 14-test suite,
including regression tests for both fixes in Section 4, the
`max_group_size` invariant from Section 5, and correctness checks on the
benchmark and distribution-shift harnesses themselves (a test suite that
only covers the detector and not the tools measuring it would have a
real gap of its own).

For the scale benchmark: `python3 -m abuse_ring_sentinel.benchmark
[account_counts...]` (e.g. `python3 -m abuse_ring_sentinel.benchmark
10000 100000`). For the distribution-shift sweep:
`python3 -m abuse_ring_sentinel.distribution_shift`.

Every number is regenerated from seeded RNGs (`config.py`), so nothing
here is a screenshot of a lucky run - rerun it and get the same result.

## 9. Limitations & what I'd do next

- **`detect_rings` still shows super-linear scaling past ~150k accounts**
  in this single-CPU sandbox, and the remaining cause wasn't fully
  root-caused before time ran out on this pass — Section 5 documents
  what was found and fixed, but there's more headroom here. A production
  deployment would need either further profiling or a move to
  incremental/streaming graph updates rather than a full recompute per
  batch.
- **The confidence-interval fix (Section 4a) uses a Wald approximation**,
  which is adequate at the sample sizes here (100+ orders per cluster)
  but would need a Wilson or Clopper-Pearson interval for smaller
  clusters where the normal approximation breaks down.
- **The velocity signal (Section 4b) uses two fixed thresholds** (mean
  account age, age spread) rather than a statistically-derived boundary
  the way the dampening rule now does. It's an improvement over having
  no signal at all, but a ring that spread its account creation over,
  say, 3 weeks instead of days would currently evade it — the next step
  would be the same confidence-interval treatment applied here.
- **Very high per-attribute noise (~50%+) fragments ring detection**
  (Section 6) — a small ring where members independently only have
  coin-flip odds of sharing any given hard identifier can fall below the
  graph connectivity needed to cluster at all. This is a real, understood
  boundary, not a hidden one.
- **Behavioral signal is currently limited to return rate, order timing,
  and account-creation velocity.** Real systems would add
  refund-to-payout-account correlation and device/OS spoofing signals -
  noted as bonus signal in the original plan and deliberately kept out of
  v1 to keep the core detector's logic auditable.
- **No real Razorpay API integration in this version** - synthetic data
  only, by design, so results are reproducible and the ground truth is
  known. Wiring in test-mode order data is a natural next step and
  doesn't change the graph/detection architecture.
- **The adversarial test cases (the borderline cluster, the velocity
  rings) were hand-designed by the same person who built the detector.**
  The held-out seed, multi-seed sweep, and distribution-shift test all
  push against this, but they don't fully replace an independent
  red-team pass by someone who didn't build the system.

## 10. Tech stack

Pure Python: `networkx` (graph + Louvain community detection), `pandas`/
`numpy` (data + scoring), zero-dependency synthetic data generation (no
`faker` - a small local name/address lexicon keeps the whole pipeline
runnable fully offline and deterministic). Strictly defense-only
throughout: this is a detector and investigation aid, nothing here
generates or automates an attack.

Visualization is a single self-contained HTML file using D3.js (loaded
from CDN) - no build step, no server, opens directly in a browser. The
dashboard follows a "Sentinel Forensic Intelligence" design system:
a deep Material-3-inspired dark mode built for the actual job a fraud
analyst does — reviewing a case, weighing evidence, reaching a verdict —
rather than a generic SaaS admin panel. Three type families do distinct
jobs: Inter for UI structure, JetBrains Mono for IDs and scores (so
columns of numbers actually align), and Playfair Display italic reserved
exclusively for the human-written case narrative, marking the one place
in the interface where the tone shifts from instrument readout to
analytical conclusion. Verdicts render as glowing bordered badges
("ring confirmed," "reviewed, cleared") color-coded by evidence type —
salmon-red for confirmed rings, violet for velocity-only evidence, gold
for cleared, green for benign — carried consistently across the case
list, the network graph, and the dossier panel, so the same color always
means the same thing everywhere on screen. The six Exhibits (Section
3-6's evidence, embedded directly in the tool) are framed as a case's
supporting appendix, because that's what they functionally are — three
render as actual charts (a precision/recall line chart against threshold,
and two bar-chart comparisons) rather than rows of numbers, so the shape
of the evidence — a wide plateau, one dip among ten bars, a 57.5%→5.0%
drop — is visible at a glance.

Every claim above should be independently checkable: clone the repo, run
`python3 main.py`, and every number in this document regenerates from a
seeded RNG in front of you.
