"""
A deliberately naive baseline: "cluster accounts by shared delivery
address; flag any cluster above a size threshold." This is the kind of
single-signal heuristic teams reach for first. It exists purely so the
evaluation report can honestly quantify what the multi-signal graph +
dampening approach buys over the obvious first attempt — not to be a
strawman, but because a buildathon judge's first question is always
"why not just do the simple thing?".
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd


def naive_address_flags(accounts_df: pd.DataFrame, size_threshold: int = 8) -> list[dict]:
    groups: dict[str, list[str]] = defaultdict(list)
    for _, row in accounts_df.iterrows():
        groups[row["delivery_address"]].append(row["account_id"])

    flagged = []
    for address, members in groups.items():
        if len(members) >= size_threshold:
            flagged.append({"members": members, "address": address, "size": len(members)})
    return flagged


if __name__ == "__main__":
    from .data_generator import generate_dataset

    accounts_df, _, gt = generate_dataset()
    flags = naive_address_flags(accounts_df)
    legit_ids = {aid for m in gt["lookalikes"].values() for aid in m}
    ring_ids = {aid for m in gt["rings"].values() for aid in m}
    for f in flags:
        legit_hit = len(set(f["members"]) & legit_ids)
        ring_hit = len(set(f["members"]) & ring_ids)
        print(f"size={f['size']:3d}  legit_members={legit_hit:3d}  ring_members={ring_hit:3d}")
