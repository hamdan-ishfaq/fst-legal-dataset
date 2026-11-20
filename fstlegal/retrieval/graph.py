"""The corpus knowledge graph (Decision D-003).

Nodes are judgments, statute units, acts, judges, keywords, outcomes and
external cases. Every edge comes from a source field in ``corpus.db``.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import networkx as nx

from .store import Corpus


def node_type(node: str) -> str:
    if node.startswith("J-"):
        return "judgment"
    if node.startswith("EXT:"):
        return "external_case"
    if node.startswith("JUDGE:"):
        return "judge"
    if node.startswith("KW:"):
        return "keyword"
    if node.startswith("OUTCOME:"):
        return "outcome"
    return "statute_unit" if ":" in node else "act"


class CorpusGraph:
    def __init__(self, corpus: Corpus):
        self.g = nx.MultiDiGraph()
        for src, rel, dst in corpus.edges():
            self.g.add_edge(src, dst, key=rel, rel=rel)
        for node in self.g.nodes:
            self.g.nodes[node]["type"] = node_type(node)
        self.units_with_text = corpus.unit_ids()

    def _out(self, node: str, rel: str) -> list[str]:
        if node not in self.g:
            return []
        return [d for _, d, r in self.g.out_edges(node, keys=True) if r == rel]

    def _in(self, node: str, rel: str) -> list[str]:
        if node not in self.g:
            return []
        return [s for s, _, r in self.g.in_edges(node, keys=True) if r == rel]

    def provisions_applied(self, judgment_id: str) -> list[str]:
        return self._out(judgment_id, "APPLIES")

    def precedents_cited(self, judgment_id: str) -> list[str]:
        return self._out(judgment_id, "CITES")

    def judgments_applying(self, unit_id: str) -> list[str]:
        return self._in(unit_id, "APPLIES")

    def judgments_citing(self, case_id: str) -> list[str]:
        return self._in(case_id, "CITES")

    def outcome(self, judgment_id: str) -> str | None:
        found = self._out(judgment_id, "HAS_OUTCOME")
        return found[0].removeprefix("OUTCOME:") if found else None

    def related_judgments(self, judgment_id: str, exclude: set[str] | None = None
                          ) -> list[tuple[str, float]]:
        """Judgments that share provisions or precedents with this one. A shared
        provision counts less when many judgments apply it, as with section 4
        of the Service Tribunals Act, which almost every appeal cites."""
        exclude = (exclude or set()) | {judgment_id}
        scores: defaultdict[str, float] = defaultdict(float)
        for unit in self.provisions_applied(judgment_id):
            others = [j for j in self.judgments_applying(unit) if j not in exclude]
            for other in others:
                scores[other] += 1 / len(self.judgments_applying(unit))
        for case in self.precedents_cited(judgment_id):
            for other in self.judgments_citing(case):
                if other not in exclude:
                    scores[other] += 1 / len(self.judgments_citing(case))
        return sorted(scores.items(), key=lambda x: -x[1])

    def provisions_from_judgments(self, judgments: list[tuple[str, float]],
                                  exclude_judgments: set[str] | None = None
                                  ) -> list[tuple[str, float]]:
        """Score statute units by how strongly the given (judgment, weight)
        list applies them. Only units whose text is in the corpus are returned."""
        exclude_judgments = exclude_judgments or set()
        scores: defaultdict[str, float] = defaultdict(float)
        for judgment_id, weight in judgments:
            if judgment_id in exclude_judgments:
                continue
            for unit in self.provisions_applied(judgment_id):
                if unit in self.units_with_text:
                    scores[unit] += weight
        return sorted(scores.items(), key=lambda x: -x[1])

    def stats(self) -> dict[str, int]:
        types = Counter(nx.get_node_attributes(self.g, "type").values())
        rels = Counter(r for _, _, r in self.g.edges(keys=True))
        return {**{f"nodes.{t}": n for t, n in types.items()},
                **{f"edges.{r}": n for r, n in rels.items()}}
