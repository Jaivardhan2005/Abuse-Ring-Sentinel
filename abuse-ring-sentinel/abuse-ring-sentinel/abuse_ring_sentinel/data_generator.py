"""
Synthetic account/order data generator.

Produces a population of accounts where the *ground truth* is known:
  - "ring"       : coordinated abuse accounts, sharing multiple hard
                   identifiers (device, payout account, phone), with
                   elevated return rates and bursty synchronized ordering.
  - "lookalike"  : legitimate accounts that innocently share ONE weak
                   identifier (a delivery address — think hostel/office),
                   but have distinct devices, payout accounts, phones,
                   and ordinary behavior. This is the trap case a naive
                   "shared address = suspicious" rule would fail.
  - "background" : ordinary independent accounts, with a small realistic
                   rate of accidental single-attribute collisions.

No external dependencies (faker unavailable offline) — name/address
synthesis is done with small local lexicons + numpy's RNG, seeded for
full reproducibility.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import GeneratorConfig

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Rohan", "Ananya", "Diya", "Saanvi", "Aadhya", "Kiara", "Myra",
    "Priya", "Neha", "Riya", "Isha", "Karan", "Varun", "Nikhil", "Siddharth",
    "Pooja", "Simran", "Tanvi", "Meera", "Yash", "Dev",
]
LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Malhotra", "Kapoor", "Nair", "Iyer", "Reddy",
    "Chatterjee", "Bose", "Mehta", "Joshi", "Rao", "Pillai", "Singh", "Kumar",
    "Patel", "Agarwal", "Bhatt", "Chauhan",
]
CITIES = [
    ("Mumbai", "400001"), ("Bengaluru", "560001"), ("Delhi", "110001"),
    ("Pune", "411001"), ("Hyderabad", "500001"), ("Chennai", "600001"),
    ("Kolkata", "700001"), ("Ahmedabad", "380001"), ("Jaipur", "302001"),
    ("Ludhiana", "141001"),
]
STREET_WORDS = ["MG Road", "Park Street", "Ring Road", "Station Road", "Civil Lines",
                "Sector 12", "Model Town", "Green Avenue", "Lake View", "Hill Road"]
DEVICE_OS = ["Android-13", "Android-14", "iOS-17", "iOS-18", "Windows-11", "macOS-15"]


def _rand_name(rng: np.random.Generator) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _rand_address(rng: np.random.Generator) -> str:
    """
    Address cardinality must stay far above the largest population this
    generator is ever run at, or random background accounts start
    accidentally colliding with a planted cluster's shared address purely
    by chance (this was a real bug found via benchmark.py at 10k+ scale:
    the original ~100k-combination address space produced hundreds of
    accidental collisions, silently contaminating ground-truth clusters
    with unrelated accounts). House number + block + a randomized pincode
    suffix pushes the combination space past 10^13, keeping expected
    collisions negligible even at population sizes in the low millions.
    """
    city, pin_prefix = CITIES[rng.integers(0, len(CITIES))]
    house = rng.integers(1, 999_999)
    block = rng.integers(1, 999)
    street = rng.choice(STREET_WORDS)
    pin_suffix = rng.integers(0, 999)
    pin = f"{pin_prefix[:3]}{pin_suffix:03d}"
    return f"House {house}, Block {block}, {street}, {city} - {pin}"


def _rand_phone(rng: np.random.Generator) -> str:
    return f"+91-{rng.integers(70000, 99999)}{rng.integers(10000, 99999)}"


def _rand_device(rng: np.random.Generator) -> str:
    # 12-digit suffix, not 8 — see _rand_payout for why this matters at scale.
    return f"DEV-{rng.choice(DEVICE_OS)}-{rng.integers(10**11, 10**12 - 1)}"


def _rand_payout(rng: np.random.Generator) -> str:
    """
    UPI ID cardinality must comfortably exceed population size, same
    principle as _rand_address. The original 7-digit UPI numeric range
    (~9 million combinations) was found — via benchmark.py at 100k+
    scale, then confirmed by directly inspecting the colliding row pair
    — to occasionally produce an exact match between an unrelated
    background account and a genuine ring/velocity-ring member, silently
    merging them into the same graph component and contaminating that
    cluster's ground truth. Widened to a 10-digit range (real UPI IDs are
    commonly phone-number-length anyway), matching BANKACC's pool size.
    """
    kind = rng.choice(["UPI", "BANK"])
    if kind == "UPI":
        return f"{rng.integers(10**9, 10**10 - 1)}@upi"
    return f"BANKACC-{rng.integers(10**9, 10**10 - 1)}"


def _rand_ip(rng: np.random.Generator) -> str:
    return f"{rng.integers(1, 223)}.{rng.integers(0, 255)}.{rng.integers(0, 255)}.{rng.integers(1, 254)}"


def _new_account_row(acc_id: str, rng: np.random.Generator, group: str, group_id: str | None) -> dict:
    return {
        "account_id": acc_id,
        "name": _rand_name(rng),
        "delivery_address": _rand_address(rng),
        "phone_number": _rand_phone(rng),
        "device_fingerprint": _rand_device(rng),
        "payout_account": _rand_payout(rng),
        "ip_address": _rand_ip(rng),
        "account_age_days": int(rng.integers(1, 900)),
        "ground_truth_group": group,   # "ring" | "lookalike" | "background"
        "ground_truth_id": group_id,   # e.g. "ring_03" / "lookalike_01" / None
    }


def generate_dataset(cfg: GeneratorConfig = GeneratorConfig()) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns (accounts_df, orders_df, ground_truth) where ground_truth is a
    dict describing exactly which accounts belong to which planted ring or
    look-alike cluster, for use by the evaluator.
    """
    rng = np.random.default_rng(cfg.seed)
    accounts: list[dict] = []
    ground_truth = {"rings": {}, "lookalikes": {}, "velocity_rings": {}}
    next_id = 1

    def alloc_id() -> str:
        nonlocal next_id
        aid = f"ACC{next_id:05d}"
        next_id += 1
        return aid

    # 1) Background accounts — ordinary, independent people.
    for _ in range(cfg.n_background_accounts):
        aid = alloc_id()
        accounts.append(_new_account_row(aid, rng, "background", None))

    # Sprinkle a *few* accidental single-attribute collisions between
    # background accounts (two strangers on the same NAT'd IP, a
    # coincidental delivery address reuse from a past tenant, etc). This
    # is what a naive "any shared attribute = suspicious" rule chokes on.
    bg_accounts = [a for a in accounts if a["ground_truth_group"] == "background"]
    n_collisions = int(len(bg_accounts) * cfg.background_collision_rate)
    for _ in range(n_collisions):
        a, b = rng.choice(bg_accounts, size=2, replace=False)
        attr = rng.choice(["ip_address", "delivery_address"])
        b[attr] = a[attr]

    # 2) Planted abuse rings — coordinated accounts sharing HARD identifiers.
    for r in range(cfg.n_rings):
        ring_id = f"ring_{r + 1:02d}"
        size = int(rng.integers(cfg.ring_size_range[0], cfg.ring_size_range[1] + 1))
        shared_device = _rand_device(rng)
        shared_payout = _rand_payout(rng)
        shared_phone = _rand_phone(rng)
        member_ids = []
        for _ in range(size):
            aid = alloc_id()
            row = _new_account_row(aid, rng, "ring", ring_id)
            # Each member shares 2-3 hard identifiers with the ring, with
            # some noise so it isn't a trivially perfect clique.
            if rng.random() > cfg.ring_attribute_noise:
                row["device_fingerprint"] = shared_device
            if rng.random() > cfg.ring_attribute_noise:
                row["payout_account"] = shared_payout
            if rng.random() > cfg.ring_attribute_noise * 1.5:
                row["phone_number"] = shared_phone
            accounts.append(row)
            member_ids.append(aid)
        ground_truth["rings"][ring_id] = member_ids

    # 3) Innocent look-alikes — legit shared-address clusters (hostel/office)
    #    with otherwise INDEPENDENT identifiers and normal behavior.
    for c in range(cfg.n_lookalike_clusters):
        cluster_id = f"lookalike_{c + 1:02d}"
        size = int(rng.integers(cfg.lookalike_size_range[0], cfg.lookalike_size_range[1] + 1))
        shared_address = _rand_address(rng)
        member_ids = []
        for _ in range(size):
            aid = alloc_id()
            row = _new_account_row(aid, rng, "lookalike", cluster_id)
            row["delivery_address"] = shared_address  # the ONLY shared thing
            accounts.append(row)
            member_ids.append(aid)
        ground_truth["lookalikes"][cluster_id] = member_ids

    # 4) The adversarial borderline case: one large, otherwise-legitimate
    #    cluster sharing only an address, but with a genuine mild return
    #    spike (think: an office during a bad sale week) — big and active
    #    enough that a naive scorer would flag it as a ring.
    for c in range(cfg.n_borderline_lookalike_clusters):
        cluster_id = f"borderline_{c + 1:02d}"
        size = int(rng.integers(cfg.borderline_lookalike_size_range[0],
                                 cfg.borderline_lookalike_size_range[1] + 1))
        shared_address = _rand_address(rng)
        member_ids = []
        for _ in range(size):
            aid = alloc_id()
            row = _new_account_row(aid, rng, "borderline_lookalike", cluster_id)
            row["delivery_address"] = shared_address
            accounts.append(row)
            member_ids.append(aid)
        ground_truth["lookalikes"][cluster_id] = member_ids

    # 5) Velocity rings: coordinated abuse via a burst of brand-new
    #    accounts hitting one shared address — no hard-identifier reuse,
    #    behavior kept statistically normal. This is the pattern that
    #    evades every signal used above; see config.py for the rationale.
    for r in range(cfg.n_velocity_rings):
        ring_id = f"velocity_{r + 1:02d}"
        size = int(rng.integers(cfg.velocity_ring_size_range[0], cfg.velocity_ring_size_range[1] + 1))
        shared_address = _rand_address(rng)
        # All members created within a short, tight window shortly before
        # "now" (age measured backward from today, so small age = recent).
        window_start_age = int(rng.integers(1, cfg.velocity_account_age_max_days -
                                             cfg.velocity_account_age_spread_days + 1))
        member_ids = []
        for _ in range(size):
            aid = alloc_id()
            row = _new_account_row(aid, rng, "velocity_ring", ring_id)
            row["delivery_address"] = shared_address
            row["account_age_days"] = int(window_start_age +
                                           rng.integers(0, cfg.velocity_account_age_spread_days + 1))
            accounts.append(row)
            member_ids.append(aid)
        ground_truth["velocity_rings"][ring_id] = member_ids

    accounts_df = pd.DataFrame(accounts)

    # --- Orders / behavioral signal synthesis ---
    orders = []
    order_id = 1
    # Assign each borderline cluster a shared ~10-day "sale window" so its
    # elevated return rate is a genuine, mildly-bursty event — not a
    # tight coordinated burst like a ring, but not perfectly flat either.
    borderline_windows = {
        cid: int(rng.integers(0, cfg.observation_days - cfg.borderline_timing_burst_mean_days))
        for cid in ground_truth["lookalikes"] if cid.startswith("borderline")
    }

    # itertuples(), not iterrows() — iterrows() constructs a new pandas
    # Series per row (type coercion overhead included), which cProfile
    # showed dominating generate_dataset's total cost at 100k+ accounts.
    # itertuples() returns lightweight namedtuples instead. Only the
    # columns actually used in this loop are selected, so the per-row
    # tuple stays small regardless of how many other columns accounts_df
    # carries.
    needed_cols = accounts_df[["account_id", "ground_truth_group", "ground_truth_id"]]
    for acc in needed_cols.itertuples(index=False):
        n_orders = int(rng.poisson(4)) + 1
        group = acc.ground_truth_group
        is_ring = group == "ring"
        is_borderline = group == "borderline_lookalike"

        if is_ring:
            return_rate = float(np.clip(rng.normal(0.45, 0.1), 0, 1))
        elif is_borderline:
            return_rate = float(np.clip(rng.normal(cfg.borderline_return_rate_mean, 0.02), 0, 1))
        else:
            return_rate = float(np.clip(rng.normal(0.08, 0.1), 0, 1))

        if is_ring:
            # Coordinated farming: a tight 4-day burst.
            burst_day = rng.integers(0, cfg.observation_days - 5)
            order_days = np.clip(burst_day + rng.integers(0, 4, size=n_orders), 0, cfg.observation_days - 1)
        elif is_borderline:
            # A genuine but mild sale-week effect: spread across ~10 days.
            window_start = borderline_windows[acc.ground_truth_id]
            order_days = np.clip(
                window_start + rng.integers(0, cfg.borderline_timing_burst_mean_days, size=n_orders),
                0, cfg.observation_days - 1,
            )
        else:
            order_days = rng.integers(0, cfg.observation_days, size=n_orders)
        for d in order_days:
            orders.append({
                "order_id": f"ORD{order_id:06d}",
                "account_id": acc.account_id,
                "order_day": int(d),
                "amount_inr": round(float(rng.gamma(2.0, 450)), 2),
                "is_return": bool(rng.random() < return_rate),
            })
            order_id += 1

    orders_df = pd.DataFrame(orders)
    return accounts_df, orders_df, ground_truth


if __name__ == "__main__":
    accounts_df, orders_df, gt = generate_dataset()
    print(accounts_df["ground_truth_group"].value_counts())
    print(f"Accounts: {len(accounts_df)}  Orders: {len(orders_df)}")
    print(f"Planted rings: {len(gt['rings'])}  Planted look-alike clusters: {len(gt['lookalikes'])}")
