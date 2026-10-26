"""
api/services/graph_service.py
------------------------------
Builds and queries the transaction network graph for the admin console.

Public interface:
    build_graph(db, until_ts: datetime) -> nx.DiGraph
        Constructs a directed NetworkX graph of sender → receiver edges
        using ONLY transactions with created_at < until_ts (no leakage).
        Nodes are UPI IDs; edge attributes include amount and timestamp.

    neighbors(graph: nx.DiGraph, upi_id: str, hops: int = 2) -> GraphResult
        Returns the subgraph of nodes within `hops` steps of `upi_id`.
        GraphResult contains node list and edge list suitable for JSON
        serialisation (used by GET /admin/graph/{upi_id}).

    flagged_neighbor_count(graph, upi_id, confirmed_fraud_ids: set) -> int
        Returns the count of graph neighbours that have at least one
        CONFIRMED_FRAUD alert — used as the `receiver_flagged_neighbors`
        feature (DESIGN.md §2.4).

Performance note:
    For the demo scale (thousands of synthetic transactions), building the
    graph in memory per request is acceptable.  Cache with a short TTL if
    needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import networkx as nx
from sqlalchemy.orm import Session

from api.models.transaction import Transaction
from api.models.user import User


@dataclass
class GraphResult:
    nodes: list[dict]            # [{id, upi_id, label}, ...]
    edges: list[dict]            # [{source, target, amount, ts}, ...]


def build_graph(db: Session, until_ts: datetime | None = None) -> nx.DiGraph:
    """
    Build a directed NetworkX graph of UPI-ID → UPI-ID edges.

    Parameters
    ----------
    db       : Active SQLAlchemy session.
    until_ts : Upper bound on created_at (exclusive) for leakage safety.
               Pass None to include all transactions.
    """
    query = db.query(Transaction)
    if until_ts is not None:
        query = query.filter(Transaction.created_at < until_ts)

    txns = query.all()

    # Collect unique user IDs so we can batch-load UPI IDs.
    user_ids = {t.sender_id for t in txns} | {t.receiver_id for t in txns}
    users: dict[int, str] = {}
    if user_ids:
        rows = db.query(User.id, User.upi_id).filter(User.id.in_(user_ids)).all()
        users = {r.id: r.upi_id for r in rows}

    g = nx.DiGraph()
    for uid, upi in users.items():
        g.add_node(upi, user_id=uid)

    for t in txns:
        src = users.get(t.sender_id)
        dst = users.get(t.receiver_id)
        if src and dst:
            g.add_edge(
                src,
                dst,
                txn_id=t.id,
                amount=float(t.amount),
                ts=t.created_at.isoformat() if t.created_at else "",
                decision=t.decision or "",
            )

    return g


def neighbors(graph: nx.DiGraph, upi_id: str, hops: int = 2) -> GraphResult:
    """
    Return a GraphResult for the *hops*-hop neighbourhood of *upi_id*.
    Includes nodes reachable in either direction (undirected BFS).
    """
    if upi_id not in graph:
        return GraphResult(nodes=[], edges=[])

    # BFS on the undirected version to get the neighbourhood set.
    undirected = graph.to_undirected()
    reachable: set[str] = {upi_id}
    frontier = {upi_id}
    for _ in range(hops):
        next_frontier: set[str] = set()
        for node in frontier:
            next_frontier.update(undirected.neighbors(node))
        next_frontier -= reachable
        reachable.update(next_frontier)
        frontier = next_frontier

    subgraph = graph.subgraph(reachable)
    nodes = [{"id": n, "upi_id": n, "label": n} for n in subgraph.nodes]
    edges = [
        {
            "source": u,
            "target": v,
            **{k: val for k, val in data.items()},
        }
        for u, v, data in subgraph.edges(data=True)
    ]
    return GraphResult(nodes=nodes, edges=edges)


def flagged_neighbor_count(
    graph: nx.DiGraph,
    upi_id: str,
    confirmed_fraud_upi_ids: set[str],
) -> int:
    """
    Count graph neighbours of *upi_id* that appear in *confirmed_fraud_upi_ids*.
    Used as the ``receiver_flagged_neighbors`` feature.
    """
    if upi_id not in graph:
        return 0

    undirected = graph.to_undirected()
    neighbour_upi_ids = set(undirected.neighbors(upi_id))
    return len(neighbour_upi_ids & confirmed_fraud_upi_ids)
