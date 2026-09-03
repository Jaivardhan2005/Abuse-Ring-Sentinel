"""
Builds the shared-attribute graph: nodes = accounts, edges = accounts that
share one or more identifying attributes. Edge weight is evidence-weighted
(sharing a device or payout account counts far more than sharing an
address), and every edge records *which* attributes were shared so the
detector — and eventually the analyst — can explain "why" in plain English.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx
import pandas as pd

from .config import DetectorConfig

SHARED_ATTRIBUTES = [
    "device_fingerprint",
    "payout_account",
    "phone_number",
    "ip_address",
    "delivery_address",
]


def build_graph(accounts_df: pd.DataFrame, cfg: DetectorConfig = DetectorConfig()) -> nx.Graph:
    """
    O(n) per attribute: group accounts by attribute value, connect every
    pair within a group (skipping groups so large they're clearly a
    platform-wide artifact, e.g. a shared corporate NAT IP with thousands
    of unrelated users — not evidence of a ring, just an ISP).
    """
    g = nx.Graph()
    g.add_nodes_from(accounts_df["account_id"])

    pair_evidence: dict[tuple[str, str], list[str]] = defaultdict(list)

    for attr in SHARED_ATTRIBUTES:
        groups = accounts_df.groupby(attr)["account_id"].apply(list)
        for value, members in groups.items():
            if len(members) < 2 or len(members) > cfg.max_group_size:
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = sorted((members[i], members[j]))
                    pair_evidence[(a, b)].append(attr)

    for (a, b), attrs in pair_evidence.items():
        weight = sum(cfg.attribute_weights[attr] for attr in attrs)
        if weight < cfg.min_edge_weight:
            continue
        g.add_edge(a, b, weight=weight, shared_attributes=attrs)

    return g


if __name__ == "__main__":
    from .data_generator import generate_dataset

    accounts_df, _, _ = generate_dataset()
    graph = build_graph(accounts_df)
    print(f"Nodes: {graph.number_of_nodes()}  Edges: {graph.number_of_edges()}")
    isolates = nx.number_of_isolates(graph)
    print(f"Isolated (no shared attributes with anyone): {isolates}")
