"""
src/network_features.py
------------------------
Computes graph-based features derived from the transaction network.

All graph construction uses ONLY edges (transactions) with created_at
strictly before the current transaction timestamp (DESIGN.md §2.4).

Functions:
    build_transaction_graph(txns: pd.DataFrame) -> nx.DiGraph
        Constructs a directed graph: sender_upi → receiver_upi.
        Edge attributes: amount, created_at.
        `txns` must already be filtered to the correct time window by the caller.

    receiver_in_degree(graph: nx.DiGraph, receiver_upi: str) -> int
        Number of distinct senders that have paid this receiver.

    distinct_senders_24h(
        txns: pd.DataFrame, receiver_upi: str, current_ts: datetime
    ) -> int
        Count of unique sender UPI IDs who paid receiver_upi in the 24 hours
        before current_ts.

    receiver_flagged_neighbors(
        graph: nx.DiGraph, receiver_upi: str, flagged_ids: set[str]
    ) -> int
        Count of graph neighbours (depth ≤ 2) of receiver_upi that appear in
        flagged_ids (accounts with CONFIRMED_FRAUD alerts before now).

Feature definitions (DESIGN.md §2.4):
    receiver_in_degree        : in-degree of receiver node in past-only graph
    distinct_senders_24h      : unique senders to receiver in last 24 h
    receiver_flagged_neighbors: confirmed-fraud neighbours of receiver
"""
