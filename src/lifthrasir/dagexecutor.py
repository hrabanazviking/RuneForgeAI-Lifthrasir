"""Replicater DAG executor and parallel hypothesis tests (LIF-0701).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core code in
``src/lifthrasir/`` beside the Mimir/Replicater companions (event
bus, event store, hypotheses, model provider).  The Replicater's
bounded subagent work -- hypothesis tests run as a dependency graph
-- is core code in the same sense, so it lives here, not in ``lab/``.
Like LIF-0601, this slice deliberately does NOT touch the package
``__init__`` export list: the banking seat unions export lists, and
``from lifthrasir import dagexecutor`` works either way.  Desired
exports are flagged in CAMPAIGN_STATE.md.

What this slice builds:

- Typed nodes.  A ``DagNode`` is one of three kinds: ``callable``
  (an in-process fixture/test function), ``hypothesis-test`` (a
  callable bound to a banked LIF-0305 hypothesis record, validated
  with ``validate_hypothesis`` before anything runs), and
  ``provider`` (a LIF-0601 ``ModelRequest`` executed through the
  failure-isolating ``run_request`` facade).  Fixture workloads
  only: this module imports no process, network or HTTP
  machinery, performs no real model call by itself, and mutates
  no host state.
- Dependency-ordered scheduling.  The graph is validated before
  any node runs: duplicate ids, unknown dependencies, cycles,
  and bound violations are all refused with named errors.  Nodes
  run in dependency waves; independent nodes in a wave run in
  parallel on a bounded thread pool.
- Per-node bounds.  Every node carries a timeout and a resource
  cost; the executor carries a worker cap and a total resource
  budget.  All bounds have hard ceilings (``MAX_*``) that neither
  a node nor an executor configuration may exceed.
- Failure isolation.  A node that raises, returns a
  non-serialisable value, times out, or whose provider fails is
  recorded ``failed`` / ``timed-out``; its dependents are recorded
  ``skipped`` with the blocking dependency named -- never silently
  cancelled, never run on corrupt inputs.  Siblings are unaffected
  and always run to completion.
- Deterministic result assembly.  ``DagReport.results`` is sorted
  by node id regardless of completion order, and ``report.digest``
  is a SHA-256 over the graph structure and the outcomes only
  (durations are reported per node but excluded from the digest),
  so identical graphs with identical node behaviour produce
  identical digests across runs.

Evidence shaping: ``DagReport.evidence_records()`` emits one
record per hypothesis-test node in the LIF-0305 style: an
``ev-...`` evidence id (derived deterministically from the node
and hypothesis ids), the hypothesis id it bears on, and whether
the outcome counts as evidence for (succeeded), evidence against
(failed / timed-out), or neither (skipped).  The executor never
promotes an evidence-ladder rung: a succeeded test is recorded as
an outcome, not as a ``supported`` status -- status changes stay
with the hypothesis ledger's own rules.

Python threads cannot be force-killed: a timed-out callable keeps
running in the background until it returns, its result is
discarded, and the executor does not wait for it at shutdown.
That is a recorded limitation, not a silent behaviour.

Evidence-status honesty: proven at fixture level only by this
slice's tests (in-process doubles and the LIF-0601 mock provider).
No real model, host service, or live system was involved.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .hypotheses import validate_hypothesis
from .modelprovider import ModelRequest, run_request

DAG_SCHEMA = "lifthrasir.dagexecutor.v0.1"
DAG_SCHEMA_VERSION = "0.1"
EVIDENCE_SCHEMA = "lifthrasir.dagevidence.v0.1"

KIND_CALLABLE = "callable"
KIND_HYPOTHESIS = "hypothesis-test"
KIND_PROVIDER = "provider"
NODE_KINDS = (KIND_CALLABLE, KIND_HYPOTHESIS, KIND_PROVIDER)

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed-out"
STATUS_SKIPPED = "skipped"
STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_TIMED_OUT,
            STATUS_SKIPPED)

MAX_NODES = 64
MAX_WORKERS = 8
MAX_TIMEOUT_S = 60.0
MAX_RESOURCE_UNITS = 64
DEFAULT_TIMEOUT_S = 5.0

_NODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class DagError(Exception):
    """Base class for all named DAG-executor refusals."""


class MalformedDagError(DagError):
    """Raised when a node or graph breaks a structural rule."""


class DuplicateNodeError(DagError):
    """Raised when two nodes share one node id."""


class UnknownDependencyError(DagError):
    """Raised when a dependency names no node in the graph."""


class CycleError(DagError):
    """Raised when the dependency graph contains a cycle."""


class UnboundedDagError(DagError):
    """Raised when a bound (nodes, workers, timeout, resources)
    exceeds its hard ceiling."""


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class DagNode:
    """One typed node in a hypothesis-test graph.

    ``fn`` (callable / hypothesis-test kinds) is invoked as
    ``fn(payload, deps)`` where ``deps`` maps each dependency's
    node id to its succeeded value.  It must return a
    JSON-serialisable value.  ``request`` (provider kind) is a
    ``ModelRequest`` executed via the LIF-0601 facade.
    ``hypothesis`` (hypothesis-test kind) is a LIF-0305 record
    dict, validated before the run.
    """

    node_id: str
    kind: str
    depends_on: Tuple[str, ...] = ()
    timeout_s: float = DEFAULT_TIMEOUT_S
    resource_units: int = 1
    hypothesis_id: Optional[str] = None
    payload: Any = None
    fn: Optional[Callable[..., Any]] = field(default=None, repr=False)
    hypothesis: Optional[Dict[str, Any]] = field(default=None, repr=False)
    request: Optional[ModelRequest] = field(default=None, repr=False)


def callable_node(node_id: str, fn: Callable[..., Any], **kw: Any) -> DagNode:
    return DagNode(node_id=node_id, kind=KIND_CALLABLE, fn=fn, **kw)


def hypothesis_node(node_id: str, record: Dict[str, Any],
                    fn: Callable[..., Any], **kw: Any) -> DagNode:
    hid = record.get("hypothesis_id") if isinstance(record, dict) else None
    return DagNode(node_id=node_id, kind=KIND_HYPOTHESIS, fn=fn,
                   hypothesis=record, hypothesis_id=hid, **kw)


def provider_node(node_id: str, request: ModelRequest, **kw: Any) -> DagNode:
    return DagNode(node_id=node_id, kind=KIND_PROVIDER, request=request, **kw)


@dataclass(frozen=True)
class NodeResult:
    node_id: str
    kind: str
    status: str
    value: Any = None
    error: Optional[str] = None
    skipped_due_to: Tuple[str, ...] = ()
    hypothesis_id: Optional[str] = None
    duration_s: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id, "kind": self.kind,
            "status": self.status, "value": self.value,
            "error": self.error,
            "skipped_due_to": list(self.skipped_due_to),
            "hypothesis_id": self.hypothesis_id,
        }


@dataclass(frozen=True)
class DagReport:
    schema: str
    results: Tuple[NodeResult, ...]
    digest: str
    graph_digest: str

    @property
    def ok(self) -> bool:
        return all(r.status == STATUS_SUCCEEDED for r in self.results)

    def counts(self) -> Dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for r in self.results:
            out[r.status] += 1
        return out

    def result(self, node_id: str) -> NodeResult:
        for r in self.results:
            if r.node_id == node_id:
                return r
        raise KeyError(node_id)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema, "digest": self.digest,
            "graph_digest": self.graph_digest,
            "counts": self.counts(),
            "results": [r.as_dict() for r in self.results],
        }

    def evidence_records(self) -> List[Dict[str, Any]]:
        """One LIF-0305-style evidence record per hypothesis node.

        Succeeded -> bears ``for`` the hypothesis, failed and
        timed-out -> ``against``, skipped -> ``neither`` (the test
        never ran, so it is evidence of nothing).  The evidence id
        is deterministic: ``ev-`` + the first 16 hex chars of the
        SHA-256 over node id + hypothesis id + graph digest.
        """
        out: List[Dict[str, Any]] = []
        for r in self.results:
            if r.kind != KIND_HYPOTHESIS or not r.hypothesis_id:
                continue
            seed = _canonical([r.node_id, r.hypothesis_id,
                               self.graph_digest])
            bearing = ("for" if r.status == STATUS_SUCCEEDED else
                       "against" if r.status in (STATUS_FAILED,
                                                 STATUS_TIMED_OUT)
                       else "neither")
            out.append({
                "schema": EVIDENCE_SCHEMA,
                "evidence_id": "ev-" + _sha256(seed)[:16],
                "hypothesis_id": r.hypothesis_id,
                "node_id": r.node_id,
                "outcome": r.status,
                "bearing": bearing,
                "error": r.error,
            })
        return out


def _check_node(node: Any) -> DagNode:
    if not isinstance(node, DagNode):
        raise MalformedDagError(
            f"graph entries must be DagNode, got {type(node).__name__}")
    if not isinstance(node.node_id, str) or not _NODE_RE.match(node.node_id):
        raise MalformedDagError(
            f"node_id {node.node_id!r} is not well-formed ([a-z0-9-])")
    if node.kind not in NODE_KINDS:
        raise MalformedDagError(
            f"node {node.node_id}: kind {node.kind!r} not in {NODE_KINDS}")
    deps = node.depends_on
    if not isinstance(deps, tuple) or not all(
            isinstance(d, str) for d in deps):
        raise MalformedDagError(
            f"node {node.node_id}: depends_on must be a tuple of ids")
    if len(set(deps)) != len(deps):
        raise MalformedDagError(
            f"node {node.node_id}: duplicate dependencies {deps}")
    if node.node_id in deps:
        raise CycleError(f"node {node.node_id} depends on itself")
    if isinstance(node.timeout_s, bool) or not isinstance(
            node.timeout_s, (int, float)) or node.timeout_s <= 0:
        raise MalformedDagError(
            f"node {node.node_id}: timeout_s must be a positive number")
    if node.timeout_s > MAX_TIMEOUT_S:
        raise UnboundedDagError(
            f"node {node.node_id}: timeout_s {node.timeout_s} exceeds "
            f"ceiling {MAX_TIMEOUT_S}")
    if isinstance(node.resource_units, bool) or not isinstance(
            node.resource_units, int) or node.resource_units < 1:
        raise MalformedDagError(
            f"node {node.node_id}: resource_units must be an int >= 1")
    if node.resource_units > MAX_RESOURCE_UNITS:
        raise UnboundedDagError(
            f"node {node.node_id}: resource_units {node.resource_units} "
            f"exceeds ceiling {MAX_RESOURCE_UNITS}")
    if node.kind in (KIND_CALLABLE, KIND_HYPOTHESIS) \
            and not callable(node.fn):
        raise MalformedDagError(
            f"node {node.node_id}: kind {node.kind} needs a callable fn")
    if node.kind == KIND_HYPOTHESIS:
        if not isinstance(node.hypothesis, dict):
            raise MalformedDagError(
                f"node {node.node_id}: hypothesis-test needs a record")
        record = validate_hypothesis(node.hypothesis)
        if node.hypothesis_id != record["hypothesis_id"]:
            raise MalformedDagError(
                f"node {node.node_id}: hypothesis_id does not match "
                f"its record")
    if node.kind == KIND_PROVIDER and not isinstance(
            node.request, ModelRequest):
        raise MalformedDagError(
            f"node {node.node_id}: provider kind needs a ModelRequest")
    try:
        json.dumps(node.payload)
    except (TypeError, ValueError):
        raise MalformedDagError(
            f"node {node.node_id}: payload is not JSON-serialisable"
        ) from None
    return node


def validate_dag(nodes: Any) -> Tuple[DagNode, ...]:
    """Validate a graph; return nodes in deterministic topo order.

    Refuses (named errors) empty or oversize graphs, duplicate
    ids, unknown dependencies, and cycles -- before anything runs.
    """
    if not isinstance(nodes, (list, tuple)) or not nodes:
        raise MalformedDagError("a DAG needs at least one node")
    if len(nodes) > MAX_NODES:
        raise UnboundedDagError(
            f"{len(nodes)} nodes exceeds ceiling {MAX_NODES}")
    checked = [_check_node(n) for n in nodes]
    seen = set()
    for n in checked:
        if n.node_id in seen:
            raise DuplicateNodeError(f"duplicate node id {n.node_id!r}")
        seen.add(n.node_id)
    for n in checked:
        for d in n.depends_on:
            if d not in seen:
                raise UnknownDependencyError(
                    f"node {n.node_id} depends on unknown node {d!r}")
    order: List[DagNode] = []
    placed = set()
    remaining = sorted(checked, key=lambda n: n.node_id)
    while remaining:
        ready = [n for n in remaining
                 if all(d in placed for d in n.depends_on)]
        if not ready:
            raise CycleError(
                "dependency cycle among: "
                + ", ".join(n.node_id for n in remaining))
        for n in ready:
            order.append(n)
            placed.add(n.node_id)
            remaining.remove(n)
    return tuple(order)


def graph_digest(nodes: Tuple[DagNode, ...]) -> str:
    """SHA-256 over graph structure only (no callables, no times)."""
    shape = [{
        "node_id": n.node_id, "kind": n.kind,
        "depends_on": sorted(n.depends_on),
        "timeout_s": n.timeout_s, "resource_units": n.resource_units,
        "hypothesis_id": n.hypothesis_id,
    } for n in sorted(nodes, key=lambda n: n.node_id)]
    return _sha256(_canonical(shape))


class DagExecutor:
    """Bounded parallel executor for validated DAGs."""

    def __init__(self, max_workers: int = 4,
                 resource_budget: int = MAX_RESOURCE_UNITS) -> None:
        if isinstance(max_workers, bool) or not isinstance(
                max_workers, int) or max_workers < 1:
            raise MalformedDagError("max_workers must be an int >= 1")
        if max_workers > MAX_WORKERS:
            raise UnboundedDagError(
                f"max_workers {max_workers} exceeds ceiling {MAX_WORKERS}")
        if isinstance(resource_budget, bool) or not isinstance(
                resource_budget, int) or resource_budget < 1:
            raise MalformedDagError("resource_budget must be an int >= 1")
        if resource_budget > MAX_RESOURCE_UNITS:
            raise UnboundedDagError(
                f"resource_budget {resource_budget} exceeds ceiling "
                f"{MAX_RESOURCE_UNITS}")
        self.max_workers = max_workers
        self.resource_budget = resource_budget

    def run(self, nodes: Any, provider: Any = None) -> DagReport:
        ordered = validate_dag(nodes)
        for n in ordered:
            if n.resource_units > self.resource_budget:
                raise UnboundedDagError(
                    f"node {n.node_id} needs {n.resource_units} resource "
                    f"units, budget is {self.resource_budget}")
        g_digest = graph_digest(ordered)
        results: Dict[str, NodeResult] = {}
        pending = list(ordered)
        gate = threading.Semaphore(self.resource_budget)
        pool = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            while pending:
                ready, blocked = [], []
                for n in pending:
                    if not all(d in results for d in n.depends_on):
                        continue
                    bad = tuple(d for d in n.depends_on
                                if results[d].status != STATUS_SUCCEEDED)
                    if bad:
                        blocked.append((n, bad))
                    else:
                        ready.append(n)
                for n, bad in blocked:
                    results[n.node_id] = NodeResult(
                        node_id=n.node_id, kind=n.kind,
                        status=STATUS_SKIPPED, skipped_due_to=bad,
                        hypothesis_id=n.hypothesis_id,
                        error="dependency did not succeed: "
                              + ", ".join(bad))
                    pending.remove(n)
                if not ready:
                    continue
                futures = {}
                for n in ready:
                    deps = {d: results[d].value for d in n.depends_on}
                    futures[n.node_id] = (
                        n, time.monotonic(),
                        pool.submit(self._invoke, n, deps, provider, gate))
                    pending.remove(n)
                for node_id, (n, started, fut) in futures.items():
                    try:
                        value = fut.result(timeout=n.timeout_s)
                        results[node_id] = NodeResult(
                            node_id=node_id, kind=n.kind,
                            status=STATUS_SUCCEEDED, value=value,
                            hypothesis_id=n.hypothesis_id,
                            duration_s=round(time.monotonic() - started, 6))
                    except FutureTimeoutError:
                        results[node_id] = NodeResult(
                            node_id=node_id, kind=n.kind,
                            status=STATUS_TIMED_OUT,
                            hypothesis_id=n.hypothesis_id,
                            duration_s=round(time.monotonic() - started, 6),
                            error=f"node exceeded timeout_s={n.timeout_s}")
                    except Exception as exc:  # failure isolation boundary
                        results[node_id] = NodeResult(
                            node_id=node_id, kind=n.kind,
                            status=STATUS_FAILED,
                            hypothesis_id=n.hypothesis_id,
                            duration_s=round(time.monotonic() - started, 6),
                            error=f"{type(exc).__name__}: {exc}")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        assembled = tuple(results[n.node_id] for n in
                          sorted(ordered, key=lambda n: n.node_id))
        digest = _sha256(_canonical({
            "graph": g_digest,
            "results": [r.as_dict() for r in assembled],
        }))
        return DagReport(schema=DAG_SCHEMA, results=assembled,
                         digest=digest, graph_digest=g_digest)

    @staticmethod
    def _invoke(node: DagNode, deps: Dict[str, Any], provider: Any,
                gate: threading.Semaphore) -> Any:
        # Acquire exactly the node's declared resource units from
        # the shared budget; released whatever the outcome.
        for _ in range(node.resource_units):
            gate.acquire()
        try:
            if node.kind == KIND_PROVIDER:
                if provider is None:
                    raise DagError(
                        f"node {node.node_id}: no provider supplied")
                result = run_request(provider, node.request)
                if result.outcome != "completed":
                    why = (result.error or result.abstain_reason
                           or "no reason recorded")
                    raise DagError(
                        f"provider outcome {result.outcome}: {why}")
                return {"outcome": result.outcome, "text": result.text,
                        "structured": result.structured}
            value = node.fn(node.payload, deps)  # type: ignore[misc]
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                raise DagError(
                    f"node {node.node_id} returned a "
                    f"non-JSON-serialisable value") from None
            return value
        finally:
            for _ in range(node.resource_units):
                gate.release()


def run_dag(nodes: Any, provider: Any = None, max_workers: int = 4,
            resource_budget: int = MAX_RESOURCE_UNITS) -> DagReport:
    """Validate and run a graph on a fresh bounded executor."""
    return DagExecutor(max_workers=max_workers,
                       resource_budget=resource_budget).run(
                           nodes, provider=provider)
