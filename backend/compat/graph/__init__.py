"""Stage 2 — dependency graph.

A typed, version-aware directed multigraph over canonical mod ids. Provides:

* provider indexing (a mod satisfies its own id, everything in ``provides`` and
  the ids of everything it embeds via jar-in-jar);
* dependency resolution with real version-range checks;
* Tarjan strongly-connected-components for cycle detection;
* intelligent cycle breaking (drop the lowest-priority edge, never a REQUIRES);
* topological ordering of the condensed DAG;
* transitive "must-keep" closure over REQUIRES edges.

Implemented without third-party graph libraries to avoid new dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from ..identity import canonical_id_for, normalize_mod_id
from ..knowledge import KnowledgeBase, get_default_kb
from ..models import CanonicalMod, Dependency, EdgeType


class _Priority(IntEnum):
    SUGGESTS = 1
    OPTIONAL = 2
    REQUIRES = 3


_EDGE_PRIORITY = {
    EdgeType.SUGGESTS: _Priority.SUGGESTS,
    EdgeType.OPTIONAL: _Priority.OPTIONAL,
    EdgeType.REQUIRES: _Priority.REQUIRES,
}


@dataclass
class ResolvedEdge:
    src: str
    dep: Dependency
    target_key: str
    status: str                # "satisfied" | "missing" | "wrong_version" | "optional_missing"
    provider: str | None = None


@dataclass
class DependencyGraph:
    mods: dict[str, CanonicalMod] = field(default_factory=dict)
    providers: dict[str, set[str]] = field(default_factory=dict)  # provided_key -> {canonical_id}
    edges: list[tuple[str, Dependency]] = field(default_factory=list)
    kb: KnowledgeBase | None = None

    # ------------------------------------------------------------- provider
    def _key(self, mod_id: str) -> str:
        return canonical_id_for(mod_id, self.kb)

    def provider_of(self, target_id: str) -> set[str]:
        keys = {self._key(target_id), normalize_mod_id(target_id).replace("_", "-")}
        out: set[str] = set()
        for k in keys:
            out |= self.providers.get(k, set())
        return out

    # ------------------------------------------------------------- resolve
    def resolve(self) -> list[ResolvedEdge]:
        resolved: list[ResolvedEdge] = []
        for src, dep in self.edges:
            if dep.type not in (EdgeType.REQUIRES, EdgeType.OPTIONAL):
                continue
            key = self._key(dep.target_id)
            providers = self.provider_of(dep.target_id)
            if not providers:
                status = "optional_missing" if dep.type == EdgeType.OPTIONAL else "missing"
                resolved.append(ResolvedEdge(src, dep, key, status))
                continue
            # a provider exists — check version if we can
            chosen = sorted(providers)[0]
            status = "satisfied"
            provider_mod = self.mods.get(chosen)
            if (dep.range is not None and provider_mod is not None
                    and provider_mod.version is not None):
                ok = dep.range.contains(provider_mod.version)
                if ok is False:
                    # only downgrade to wrong_version for mandatory deps
                    status = "wrong_version" if dep.type == EdgeType.REQUIRES else "satisfied"
            resolved.append(ResolvedEdge(src, dep, key, status, provider=chosen))
        return resolved

    def missing_required(self) -> list[ResolvedEdge]:
        return [e for e in self.resolve() if e.status in ("missing", "wrong_version")]

    # --------------------------------------------------------------- graph
    def _required_adjacency(self) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = {cid: set() for cid in self.mods}
        for src, dep in self.edges:
            if dep.type != EdgeType.REQUIRES:
                continue
            for prov in self.provider_of(dep.target_id):
                if prov in self.mods and prov != src:
                    adj.setdefault(src, set()).add(prov)
        return adj

    def required_closure(self) -> set[str]:
        """Every canonical id that is (transitively) required by some mod."""
        adj = self._required_adjacency()
        closure: set[str] = set()
        for start in list(adj):
            stack = list(adj.get(start, ()))
            while stack:
                node = stack.pop()
                if node in closure:
                    continue
                closure.add(node)
                stack.extend(adj.get(node, ()))
        return closure

    def strongly_connected_components(self) -> list[list[str]]:
        """Tarjan's SCC algorithm over REQUIRES edges (iterative)."""
        adj = self._required_adjacency()
        index_counter = [0]
        stack: list[str] = []
        on_stack: set[str] = set()
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        result: list[list[str]] = []

        def strongconnect(v: str):
            work = [(v, iter(adj.get(v, ())))]
            indices[v] = lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)
            while work:
                node, it = work[-1]
                advanced = False
                for w in it:
                    if w not in indices:
                        indices[w] = lowlink[w] = index_counter[0]
                        index_counter[0] += 1
                        stack.append(w)
                        on_stack.add(w)
                        work.append((w, iter(adj.get(w, ()))))
                        advanced = True
                        break
                    elif w in on_stack:
                        lowlink[node] = min(lowlink[node], indices[w])
                if advanced:
                    continue
                if lowlink[node] == indices[node]:
                    comp: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    result.append(comp)
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])

        for v in list(adj):
            if v not in indices:
                strongconnect(v)
        return result

    def cycles(self) -> list[list[str]]:
        return [c for c in self.strongly_connected_components() if len(c) > 1]

    def break_cycles(self) -> list[tuple[str, str]]:
        """Report the lowest-priority edges that would break each cycle.

        We never *delete* mods — mutual REQUIRES cycles are legal in Minecraft
        (two mods that hard-depend on each other). This only surfaces the edge a
        resolver could relax if ordering is needed.
        """
        broken: list[tuple[str, str]] = []
        for comp in self.cycles():
            comp_set = set(comp)
            candidates = [
                (src, dep) for src, dep in self.edges
                if src in comp_set
                and dep.type in _EDGE_PRIORITY
                and self.provider_of(dep.target_id) & comp_set
            ]
            if not candidates:
                continue
            src, dep = min(candidates, key=lambda sd: _EDGE_PRIORITY[sd[1].type])
            broken.append((src, dep.target_id))
        return broken

    def topological_order(self) -> list[str]:
        """Kahn topological sort of the condensed DAG (deterministic)."""
        adj = self._required_adjacency()
        # condense SCCs
        comp_of: dict[str, int] = {}
        comps = self.strongly_connected_components()
        for i, comp in enumerate(comps):
            for n in comp:
                comp_of[n] = i
        cadj: dict[int, set[int]] = {i: set() for i in range(len(comps))}
        indeg: dict[int, int] = {i: 0 for i in range(len(comps))}
        for src, nbrs in adj.items():
            for dst in nbrs:
                cs, cd = comp_of[src], comp_of[dst]
                if cs != cd and cd not in cadj[cs]:
                    cadj[cs].add(cd)
                    indeg[cd] += 1
        queue = sorted(i for i in cadj if indeg[i] == 0)
        order: list[str] = []
        while queue:
            i = queue.pop(0)
            order.extend(sorted(comps[i]))
            new = []
            for j in sorted(cadj[i]):
                indeg[j] -= 1
                if indeg[j] == 0:
                    new.append(j)
            queue = sorted(queue + new)
        # append any nodes not covered (safety)
        for cid in self.mods:
            if cid not in order:
                order.append(cid)
        return order


def build_graph(mods: list[CanonicalMod], kb: KnowledgeBase | None = None) -> DependencyGraph:
    kb = kb or get_default_kb()
    graph = DependencyGraph(kb=kb)

    for mod in mods:
        graph.mods[mod.canonical_id] = mod

    def _add_provider(key: str, cid: str):
        k = canonical_id_for(key, kb)
        graph.providers.setdefault(k, set()).add(cid)
        alt = normalize_mod_id(key).replace("_", "-")
        graph.providers.setdefault(alt, set()).add(cid)

    for mod in mods:
        _add_provider(mod.canonical_id, mod.canonical_id)
        for mid in mod.mod_ids:
            _add_provider(mid, mod.canonical_id)
        for pid in mod.provides:
            _add_provider(pid, mod.canonical_id)
        for emb in mod.embedded:
            for mid in list(emb.mod_ids) + list(emb.provides):
                _add_provider(mid, mod.canonical_id)  # embedded ids are provided by host
        for dep in mod.dependencies:
            graph.edges.append((mod.canonical_id, dep))

    return graph


__all__ = ["DependencyGraph", "ResolvedEdge", "build_graph"]
