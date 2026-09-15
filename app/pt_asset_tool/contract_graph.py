from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


FORMAT = 'PT_ASSET_CONTRACT_GRAPH_V1'


@dataclass
class ContractNode:
    node_id: str
    node_type: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContractEdge:
    source: str
    target: str
    relation: str
    evidence: str
    confidence: float
    required: bool | None = None
    status: str = 'EVIDENCE_ONLY'
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContractGraph:
    """Small deterministic graph used by client/server completeness audits.

    The graph deliberately stores *evidence* separately from *status*.  A
    reference-source relationship can prove that two concepts are related
    without proving that the same relationship is mandatory for the Summit
    runtime.  This keeps generation fail-closed until a writer/runtime rule is
    separately certified.
    """

    def __init__(self):
        self.nodes: dict[str, ContractNode] = {}
        self.edges: list[ContractEdge] = []
        self._edge_keys: set[tuple[Any, ...]] = set()

    def add_node(self, node: ContractNode) -> ContractNode:
        old = self.nodes.get(node.node_id)
        if old is None:
            self.nodes[node.node_id] = node
            return node
        if node.attributes:
            merged = dict(old.attributes)
            merged.update(node.attributes)
            old.attributes = merged
        if node.label and not old.label:
            old.label = node.label
        return old

    def ensure_node(self, node_id: str, node_type: str, label: str, **attributes: Any) -> ContractNode:
        return self.add_node(ContractNode(node_id, node_type, label, dict(attributes)))

    def add_edge(self, edge: ContractEdge) -> ContractEdge:
        key = (
            edge.source, edge.target, edge.relation, edge.evidence,
            round(float(edge.confidence), 6), edge.required, edge.status,
        )
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self.edges.append(edge)
        return edge

    def connect(
        self,
        source: str,
        target: str,
        relation: str,
        *,
        evidence: str,
        confidence: float,
        required: bool | None = None,
        status: str = 'EVIDENCE_ONLY',
        **attributes: Any,
    ) -> ContractEdge:
        return self.add_edge(ContractEdge(
            source=source,
            target=target,
            relation=relation,
            evidence=evidence,
            confidence=float(confidence),
            required=required,
            status=status,
            attributes=dict(attributes),
        ))

    def to_dict(self, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            'format': FORMAT,
            'metadata': dict(metadata or {}),
            'node_count': len(self.nodes),
            'edge_count': len(self.edges),
            'nodes': [self.nodes[k].to_dict() for k in sorted(self.nodes)],
            'edges': [e.to_dict() for e in sorted(
                self.edges,
                key=lambda x: (x.source, x.target, x.relation, x.evidence, x.status),
            )],
        }
