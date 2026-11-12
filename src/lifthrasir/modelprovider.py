"""Model-provider protocol, mock model, optional local adapter (LIF-0601).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 4 fixes local inference as
"Replaceable provider protocol, Project A.E.S.I.R. adapter" with the
llama.cpp ecosystem or any compliant server as alternatives, and
ADR-0002 repeats it: "a replaceable model-provider protocol with a
Project A.E.S.I.R. adapter; no single model is required to start,
stop, inspect or recover the system."  Roadmap/02 (P6) names this
slice's surface exactly: "capability probe, inference with structured
output, cancellation, deadlines, model provenance, memory and
CPU/GPU quotas", "a deterministic mock adapter and a local inference
adapter", and the release gate "the system still repairs known
supported faults safely when no model can load."  AI adapters are
Python by ADR-0002 D2, and the Mimir/Replicater companions already
live in ``src/lifthrasir/``, so the protocol lives here too -- not in
``lab/``.  Like LIF-0303/LIF-0304/LIF-0306, this slice deliberately
does NOT touch the package ``__init__`` export list: the banking
seat unions export lists, and ``from lifthrasir import
modelprovider`` works either way.  Desired exports are flagged in
CAMPAIGN_STATE.md.

What this slice builds:

- ``ModelProvider``: the replaceable protocol (``typing.Protocol``):
  ``probe()`` returns ``ModelCapabilities``; ``generate(request,
  cancel_token)`` returns a validated ``ModelResult`` or raises a
  named ``ModelProviderError`` subclass.
- ``ModelRequest`` / ``ModelResult``: the versioned TaskEnvelope /
  ModelResult pair roadmap/02 asks for, in the LIF-0004 v0.1 dict
  style (``schema`` / ``schema_version`` envelope on the wire).
  Request fields follow research/10: task id, model id + exact
  revision, prompt-template version, trusted system constraints,
  untrusted context references, input/output token caps,
  temperature, deadline, output-schema target, cancellation token
  (passed out-of-band, never serialised).  Result fields: outcome,
  text and/or structured candidate, citations, uncertainty, token
  counts, latency, peak-memory report, performed-inference flag,
  abstention/error reason, and a provenance hash binding the result
  to the exact request bytes.
- ``MockModelProvider``: the DELIVERABLE-GRADE deterministic mock.
  Same request in, same result out (text, structured payload,
  citations, token counts, uncertainty); it cites only context
  references the request actually supplied; it abstains on the
  recorded ``[[abstain]]`` marker and fails on the recorded
  ``[[mock-fail]]`` marker so failure handling is testable without
  any real model.  No randomness, no wall-clock dependence in the
  payload (latency comes from an injectable clock), no network.
- ``LocalInferenceAdapter``: the OPTIONAL local adapter, at
  fixture/offline level.  It is disabled by default (opt-in provider
  settings, roadmap/02), holds NO transport of its own, and can only
  talk through a caller-injected ``transport`` callable.  This
  module imports no socket, HTTP or subprocess machinery at all, so
  the adapter cannot download a model, open a socket, or call a
  network service by itself.  Its endpoint is validated local-only
  at construction: a ``local://`` label or a loopback HTTP endpoint;
  anything else is refused as a forbidden cloud fallback
  (research/10: "No implicit cloud fallback").  Transport responses
  are validated deterministically: over-long output, invented
  citations (not among the request's context references), bad
  uncertainty, or a missing structured payload all refuse.
- ``run_request`` / ``run_with_fallback``: the failure-isolating
  facade every caller should use.  Provider failure, unavailability,
  cancellation and deadline expiry come back as ``ModelResult``
  outcomes, never as exceptions, so a dead model cannot block
  observation, undo, recovery or emergency stop (P6 exit: "model
  failure cannot affect recovery"; safety invariant 8).  Only a
  malformed request -- a caller bug, not a model event -- raises.
  Fallback tries ONLY the providers it is handed, in order; it never
  invents a cloud provider.

Evidence-status honesty: the protocol and the mock are proven at
fixture/lab level by this slice's tests.  The local adapter is
proven ONLY against injected fake transports returning recorded
responses; NO real inference is claimed -- no model was loaded, no
inference server was contacted, and no benchmark number exists.
Quotas (token caps, deadlines, cancellation) are enforced at this
protocol layer; OS-level memory/CPU quota enforcement is LIF-0603.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple, runtime_checkable

PROVIDER_SCHEMA = "lifthrasir.modelprovider.v0.1"
PROVIDER_SCHEMA_VERSION = "0.1"

OUTCOMES = ("completed", "abstained", "failed", "cancelled", "unavailable")
OUTPUT_SCHEMAS = ("json-object", "hypothesis-v0.1", "explanation-v0.1")

MAX_PROMPT_CHARS = 32768
MAX_OUTPUT_CHARS = 16384
MAX_CONTEXT_REFS = 64
MAX_INPUT_TOKENS = 131072
MAX_OUTPUT_TOKENS = 16384

ABSTAIN_MARKER = "[[abstain]]"
FAIL_MARKER = "[[mock-fail]]"

_TASK_RE = re.compile(r"^task-[a-z0-9][a-z0-9-]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


class ModelProviderError(Exception):
    """Base class for all named model-provider refusals."""


class MalformedRequestError(ModelProviderError):
    """Raised when a ModelRequest breaks a protocol field rule."""


class MalformedResultError(ModelProviderError):
    """Raised when a ModelResult dict breaks a protocol field rule."""


class UnsupportedCapabilityError(ModelProviderError):
    """Raised for an unknown provider or unsupported capability."""


class ProviderUnavailableError(ModelProviderError):
    """Raised when a provider is disabled or has no usable backend."""


class ProviderFailedError(ModelProviderError):
    """Raised when a provider backend fails during generation."""


class RequestCancelledError(ModelProviderError):
    """Raised when the caller's cancellation token is cancelled."""


class DeadlineExceededError(ModelProviderError):
    """Raised when generation exceeds the request deadline."""


class ResponseValidationError(ModelProviderError):
    """Raised when a backend response breaks the protocol contract."""


class CloudFallbackForbiddenError(ModelProviderError):
    """Raised when a non-local endpoint/provider would be a cloud fallback."""


def count_tokens(text: str) -> int:
    """Deterministic protocol token estimate: ceil(len/4), 0 for empty.

    This is a budgeting convention for the protocol layer, not a
    claim about any real model's tokenizer.
    """
    if not text:
        return 0
    return (len(text) + 3) // 4


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CancellationToken:
    """Cooperative cancellation: providers poll, callers cancel."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise RequestCancelledError("request cancelled by caller token")


def _check_str(value: Any, field_name: str, err: type) -> str:
    if not isinstance(value, str) or not value:
        raise err(f"{field_name} must be a non-empty string, got {value!r}")
    return value


def _check_token_cap(value: Any, field_name: str, ceiling: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedRequestError(
            f"{field_name} must be an int, got {type(value).__name__}")
    if value < 1 or value > ceiling:
        raise MalformedRequestError(
            f"{field_name} must be in 1..{ceiling}, got {value}")
    return value


def _check_ref_tuple(value: Any, field_name: str, err: type = MalformedRequestError) -> Tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise err(
            f"{field_name} must be a list of strings, got "
            f"{type(value).__name__}")
    out = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 256:
            raise MalformedRequestError(
                f"{field_name} entries must be non-empty strings of "
                f"at most 256 chars, got {item!r}")
        out.append(item)
    if len(out) > MAX_CONTEXT_REFS:
        raise err(
            f"{field_name} carries {len(out)} entries, cap is "
            f"{MAX_CONTEXT_REFS}")
    return tuple(out)


@dataclass(frozen=True)
class ModelRequest:
    """One bounded inference request (research/10 request fields)."""

    task_id: str
    prompt: str
    model_id: str = "mock-1"
    model_revision: str = "mock-rev-1"
    prompt_template_version: str = "tmpl-1"
    context_refs: Tuple[str, ...] = ()
    system_constraints: Tuple[str, ...] = ()
    max_input_tokens: int = 4096
    max_output_tokens: int = 1024
    temperature: float = 0.0
    deadline_s: float = 30.0
    output_schema: Optional[str] = None

    def __post_init__(self) -> None:
        _check_str(self.task_id, "task_id", MalformedRequestError)
        if not _TASK_RE.match(self.task_id):
            raise MalformedRequestError(
                f"task_id must match task-<slug>, got {self.task_id!r}")
        _check_str(self.prompt, "prompt", MalformedRequestError)
        if len(self.prompt) > MAX_PROMPT_CHARS:
            raise MalformedRequestError(
                f"prompt is {len(self.prompt)} chars, cap is "
                f"{MAX_PROMPT_CHARS}")
        _check_str(self.model_id, "model_id", MalformedRequestError)
        _check_str(self.model_revision, "model_revision",
                   MalformedRequestError)
        _check_str(self.prompt_template_version,
                   "prompt_template_version", MalformedRequestError)
        object.__setattr__(self, "context_refs",
                           _check_ref_tuple(self.context_refs,
                                            "context_refs"))
        object.__setattr__(self, "system_constraints",
                           _check_ref_tuple(self.system_constraints,
                                            "system_constraints"))
        _check_token_cap(self.max_input_tokens, "max_input_tokens",
                         MAX_INPUT_TOKENS)
        _check_token_cap(self.max_output_tokens, "max_output_tokens",
                         MAX_OUTPUT_TOKENS)
        if count_tokens(self.prompt) > self.max_input_tokens:
            raise MalformedRequestError(
                f"prompt needs {count_tokens(self.prompt)} input tokens, "
                f"over the declared max_input_tokens="
                f"{self.max_input_tokens}")
        if isinstance(self.temperature, bool) or not isinstance(
                self.temperature, (int, float)):
            raise MalformedRequestError(
                f"temperature must be a number, got "
                f"{type(self.temperature).__name__}")
        if not 0.0 <= float(self.temperature) <= 2.0:
            raise MalformedRequestError(
                f"temperature must be in 0..2, got {self.temperature}")
        if isinstance(self.deadline_s, bool) or not isinstance(
                self.deadline_s, (int, float)):
            raise MalformedRequestError("deadline_s must be a number")
        if not 0.0 < float(self.deadline_s) <= 3600.0:
            raise MalformedRequestError(
                f"deadline_s must be in (0, 3600], got {self.deadline_s}")
        if self.output_schema is not None and \
                self.output_schema not in OUTPUT_SCHEMAS:
            raise MalformedRequestError(
                f"output_schema must be one of {list(OUTPUT_SCHEMAS)} "
                f"or None, got {self.output_schema!r}")

    @property
    def input_tokens(self) -> int:
        return count_tokens(self.prompt)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": PROVIDER_SCHEMA,
            "schema_version": PROVIDER_SCHEMA_VERSION,
            "task_id": self.task_id,
            "prompt": self.prompt,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "prompt_template_version": self.prompt_template_version,
            "context_refs": list(self.context_refs),
            "system_constraints": list(self.system_constraints),
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "temperature": float(self.temperature),
            "deadline_s": float(self.deadline_s),
            "output_schema": self.output_schema,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelRequest":
        if not isinstance(data, Mapping):
            raise MalformedRequestError(
                f"request must be a mapping, got {type(data).__name__}")
        allowed = {"schema", "schema_version", "task_id", "prompt",
                   "model_id", "model_revision",
                   "prompt_template_version", "context_refs",
                   "system_constraints", "max_input_tokens",
                   "max_output_tokens", "temperature", "deadline_s",
                   "output_schema"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise MalformedRequestError(
                f"unknown request fields: {unknown}")
        if "schema" in data and data["schema"] != PROVIDER_SCHEMA:
            raise MalformedRequestError(
                f"schema must be {PROVIDER_SCHEMA!r}, got "
                f"{data['schema']!r}")
        if "schema_version" in data and \
                data["schema_version"] != PROVIDER_SCHEMA_VERSION:
            raise MalformedRequestError(
                f"schema_version must be {PROVIDER_SCHEMA_VERSION!r}, "
                f"got {data['schema_version']!r}")
        for required in ("task_id", "prompt"):
            if required not in data:
                raise MalformedRequestError(
                    f"request is missing required field {required!r}")
        kwargs = {k: data[k] for k in allowed - {"schema", "schema_version"}
                  if k in data}
        return cls(**kwargs)


def request_from_dict(data: Mapping[str, Any]) -> ModelRequest:
    return ModelRequest.from_dict(data)


@dataclass(frozen=True)
class ModelCapabilities:
    """What one provider honestly reports about itself (probe)."""

    provider_name: str
    model_id: str
    model_revision: str
    available: bool
    is_local: bool
    supports_structured_output: bool
    supports_cancellation: bool
    max_context_tokens: int
    artifact_hash: Optional[str] = None
    detail: str = ""

    def __post_init__(self) -> None:
        _check_str(self.provider_name, "provider_name", MalformedResultError)
        _check_str(self.model_id, "model_id", MalformedResultError)
        _check_str(self.model_revision, "model_revision", MalformedResultError)
        if self.artifact_hash is not None and not _HASH_RE.match(
                self.artifact_hash):
            raise MalformedResultError(
                f"artifact_hash must be a sha256 hex digest, got "
                f"{self.artifact_hash!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "available": self.available,
            "is_local": self.is_local,
            "supports_structured_output": self.supports_structured_output,
            "supports_cancellation": self.supports_cancellation,
            "max_context_tokens": self.max_context_tokens,
            "artifact_hash": self.artifact_hash,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ModelResult:
    """One provider outcome (research/10 response fields)."""

    task_id: str
    provider_name: str
    model_id: str
    model_revision: str
    outcome: str
    text: str = ""
    structured: Optional[Dict[str, Any]] = None
    citations: Tuple[str, ...] = ()
    uncertainty: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    memory_bytes_peak: Optional[int] = None
    abstain_reason: Optional[str] = None
    error: Optional[str] = None
    performed_inference: bool = False
    provenance_hash: str = ""

    def __post_init__(self) -> None:
        _check_str(self.task_id, "task_id", MalformedResultError)
        if not _TASK_RE.match(self.task_id):
            raise MalformedResultError(
                f"task_id must match task-<slug>, got {self.task_id!r}")
        _check_str(self.provider_name, "provider_name", MalformedResultError)
        _check_str(self.model_id, "model_id", MalformedResultError)
        _check_str(self.model_revision, "model_revision", MalformedResultError)
        if self.outcome not in OUTCOMES:
            raise MalformedResultError(
                f"outcome must be one of {list(OUTCOMES)}, got "
                f"{self.outcome!r}")
        if not isinstance(self.text, str):
            raise MalformedResultError("text must be a string")
        if len(self.text) > MAX_OUTPUT_CHARS:
            raise MalformedResultError(
                f"text is {len(self.text)} chars, cap is {MAX_OUTPUT_CHARS}")
        if self.structured is not None and not isinstance(
                self.structured, dict):
            raise MalformedResultError("structured must be a mapping or None")
        object.__setattr__(self, "citations",
                           _check_ref_tuple(self.citations, "citations", MalformedResultError))
        if self.uncertainty is not None:
            if isinstance(self.uncertainty, bool) or not isinstance(
                    self.uncertainty, (int, float)) or not \
                    0.0 <= float(self.uncertainty) <= 1.0:
                raise MalformedResultError(
                    f"uncertainty must be in 0..1 or None, got "
                    f"{self.uncertainty!r}")
        for name in ("input_tokens", "output_tokens", "latency_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value < 0:
                raise MalformedResultError(
                    f"{name} must be a non-negative int, got {value!r}")
        if self.memory_bytes_peak is not None and (
                isinstance(self.memory_bytes_peak, bool)
                or not isinstance(self.memory_bytes_peak, int)
                or self.memory_bytes_peak < 0):
            raise MalformedResultError(
                "memory_bytes_peak must be a non-negative int or None")
        if self.outcome == "completed" and not self.performed_inference:
            raise MalformedResultError(
                "a completed result must record performed_inference=True")
        if self.outcome == "abstained":
            if self.performed_inference:
                raise MalformedResultError(
                    "an abstained result performed no inference")
            if not self.abstain_reason:
                raise MalformedResultError(
                    "an abstained result must carry abstain_reason")
        if self.outcome in ("failed", "cancelled", "unavailable"):
            if self.performed_inference:
                raise MalformedResultError(
                    f"a {self.outcome} result performed no inference")
            if not self.error:
                raise MalformedResultError(
                    f"a {self.outcome} result must carry an error reason")
        if self.provenance_hash and not _HASH_RE.match(self.provenance_hash):
            raise MalformedResultError(
                f"provenance_hash must be a sha256 hex digest or empty, "
                f"got {self.provenance_hash!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": PROVIDER_SCHEMA,
            "schema_version": PROVIDER_SCHEMA_VERSION,
            "task_id": self.task_id,
            "provider_name": self.provider_name,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "outcome": self.outcome,
            "text": self.text,
            "structured": self.structured,
            "citations": list(self.citations),
            "uncertainty": self.uncertainty,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "memory_bytes_peak": self.memory_bytes_peak,
            "abstain_reason": self.abstain_reason,
            "error": self.error,
            "performed_inference": self.performed_inference,
            "provenance_hash": self.provenance_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelResult":
        if not isinstance(data, Mapping):
            raise MalformedResultError(
                f"result must be a mapping, got {type(data).__name__}")
        allowed = {"schema", "schema_version", "task_id", "provider_name",
                   "model_id", "model_revision", "outcome", "text",
                   "structured", "citations", "uncertainty",
                   "input_tokens", "output_tokens", "latency_ms",
                   "memory_bytes_peak", "abstain_reason", "error",
                   "performed_inference", "provenance_hash"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise MalformedResultError(f"unknown result fields: {unknown}")
        if "schema" in data and data["schema"] != PROVIDER_SCHEMA:
            raise MalformedResultError(
                f"schema must be {PROVIDER_SCHEMA!r}, got {data['schema']!r}")
        if "schema_version" in data and \
                data["schema_version"] != PROVIDER_SCHEMA_VERSION:
            raise MalformedResultError(
                f"schema_version must be {PROVIDER_SCHEMA_VERSION!r}, "
                f"got {data['schema_version']!r}")
        for required in ("task_id", "provider_name", "model_id",
                         "model_revision", "outcome"):
            if required not in data:
                raise MalformedResultError(
                    f"result is missing required field {required!r}")
        kwargs = {k: data[k] for k in allowed - {"schema", "schema_version"}
                  if k in data}
        return cls(**kwargs)


def result_from_dict(data: Mapping[str, Any]) -> ModelResult:
    return ModelResult.from_dict(data)


def _provenance(request: ModelRequest, provider_name: str, text: str) -> str:
    return _sha256(_canonical({
        "request": request.to_dict(), "provider": provider_name,
        "text": text}))


@runtime_checkable
class ModelProvider(Protocol):
    """The replaceable provider protocol: probe + generate."""

    name: str

    def probe(self) -> ModelCapabilities:
        ...

    def generate(self, request: ModelRequest,
                 cancel_token: Optional[CancellationToken] = None
                 ) -> ModelResult:
        ...


def _require_request(request: Any) -> ModelRequest:
    if not isinstance(request, ModelRequest):
        raise MalformedRequestError(
            f"generate() needs a ModelRequest, got "
            f"{type(request).__name__}")
    return request


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    limit = max(0, max_tokens * 4 - 3)
    if len(text) <= limit:
        return text
    return text[:limit]


class MockModelProvider:
    """Deterministic mock model: the deliverable-grade offline path.

    Behaviour is a pure function of the request: identical requests
    produce identical text, structured payload, citations, token
    counts and uncertainty.  The only non-payload measurement is
    latency, taken from the injectable clock.  Markers: a prompt
    containing ``[[abstain]]`` abstains; a prompt containing
    ``[[mock-fail]]`` raises ProviderFailedError so callers can
    prove their failure handling without any real model.
    """

    name = "mock"

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock

    def probe(self) -> ModelCapabilities:
        return ModelCapabilities(
            provider_name=self.name, model_id="mock-1",
            model_revision="mock-rev-1", available=True, is_local=True,
            supports_structured_output=True, supports_cancellation=True,
            max_context_tokens=MAX_INPUT_TOKENS,
            artifact_hash=_sha256(b"mock-1:mock-rev-1"),
            detail="deterministic mock; no model weights, no network")

    def generate(self, request: ModelRequest,
                 cancel_token: Optional[CancellationToken] = None
                 ) -> ModelResult:
        _require_request(request)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        start = self._clock()
        if FAIL_MARKER in request.prompt:
            raise ProviderFailedError(
                "mock failure injected by [[mock-fail]] marker")
        elapsed = self._clock() - start
        if elapsed > float(request.deadline_s):
            raise DeadlineExceededError(
                f"mock exceeded deadline_s={request.deadline_s}")
        latency_ms = int(round(elapsed * 1000))
        base = dict(task_id=request.task_id, provider_name=self.name,
                    model_id=request.model_id,
                    model_revision=request.model_revision,
                    input_tokens=request.input_tokens,
                    latency_ms=latency_ms)
        if ABSTAIN_MARKER in request.prompt:
            return ModelResult(
                **base, outcome="abstained", performed_inference=False,
                abstain_reason=(
                    "mock abstention requested by [[abstain]] marker"),
                provenance_hash=_provenance(request, self.name, ""))
        digest = _sha256(_canonical(request.to_dict()))
        uncertainty = (int(digest[0:4], 16) % 51) / 100.0
        if request.output_schema is not None:
            structured = {
                "task_id": request.task_id,
                "summary": ("mock structured response for "
                            + request.task_id),
                "citations": list(request.context_refs),
                "digest": digest[:16],
            }
            text = json.dumps(structured, sort_keys=True)
            text = _truncate_to_tokens(text, request.max_output_tokens)
            try:
                structured_out: Optional[Dict[str, Any]] = json.loads(text)
            except ValueError:
                structured_out = None
            return ModelResult(
                **base, outcome="completed", text=text,
                structured=structured_out,
                citations=tuple(request.context_refs),
                uncertainty=uncertainty,
                output_tokens=count_tokens(text),
                performed_inference=True,
                provenance_hash=_provenance(request, self.name, text))
        text = ("mock response for " + request.task_id + ": "
                + request.prompt.strip()[:200]
                + " [digest " + digest[:12] + "]")
        text = _truncate_to_tokens(text, request.max_output_tokens)
        return ModelResult(
            **base, outcome="completed", text=text,
            citations=tuple(request.context_refs),
            uncertainty=uncertainty,
            output_tokens=count_tokens(text), performed_inference=True,
            provenance_hash=_provenance(request, self.name, text))


def _validate_endpoint(endpoint: Any) -> str:
    if not isinstance(endpoint, str) or not endpoint:
        raise CloudFallbackForbiddenError(
            f"endpoint must be a non-empty local string, got {endpoint!r}")
    if endpoint.startswith("local://"):
        label = endpoint[len("local://"):]
        if not label or "/" in label or " " in label:
            raise CloudFallbackForbiddenError(
                f"local:// endpoint must be a bare label, got {endpoint!r}")
        return endpoint
    if endpoint.startswith(("http://", "https://")):
        rest = endpoint.split("://", 1)[1]
        hostport = rest.split("/", 1)[0]
        host = hostport.rsplit("@", 1)[-1]
        if host.startswith("["):
            host = host.split("]", 1)[0] + "]"
        else:
            host = host.split(":", 1)[0]
        if host in _LOOPBACK_HOSTS:
            return endpoint
        raise CloudFallbackForbiddenError(
            f"endpoint host {host!r} is not loopback; cloud fallback "
            f"is forbidden (research/10: no implicit cloud fallback)")
    raise CloudFallbackForbiddenError(
        f"endpoint {endpoint!r} is neither local:// nor loopback HTTP; "
        f"refused")


Transport = Callable[[Dict[str, Any]], Dict[str, Any]]


class LocalInferenceAdapter:
    """Optional local inference adapter (fixture/offline level).

    Disabled by default; even when enabled it can only reach a
    backend through the caller-injected ``transport`` callable.
    With no transport it reports itself unavailable.  It never
    downloads a model and never opens a network connection: this
    module contains no networking code at all.
    """

    name = "local"

    def __init__(self, endpoint: str = "local://aesir",
                 transport: Optional[Transport] = None,
                 enabled: bool = False,
                 clock: Callable[[], float] = time.monotonic,
                 model_id: str = "local-1",
                 model_revision: str = "local-rev-1") -> None:
        self._endpoint = _validate_endpoint(endpoint)
        if transport is not None and not callable(transport):
            raise ProviderUnavailableError("transport must be callable")
        self._transport = transport
        self._enabled = bool(enabled)
        self._clock = clock
        self._model_id = model_id
        self._model_revision = model_revision

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def probe(self) -> ModelCapabilities:
        if not self._enabled:
            detail = "disabled by default; opt-in required"
            available = False
        elif self._transport is None:
            detail = "enabled but no transport injected; unavailable"
            available = False
        else:
            detail = "enabled with injected transport (fixture level)"
            available = True
        return ModelCapabilities(
            provider_name=self.name, model_id=self._model_id,
            model_revision=self._model_revision, available=available,
            is_local=True, supports_structured_output=True,
            supports_cancellation=True,
            max_context_tokens=MAX_INPUT_TOKENS, artifact_hash=None,
            detail=detail)

    def generate(self, request: ModelRequest,
                 cancel_token: Optional[CancellationToken] = None
                 ) -> ModelResult:
        _require_request(request)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if not self._enabled:
            raise ProviderUnavailableError(
                "local adapter is disabled (opt-in provider setting)")
        if self._transport is None:
            raise ProviderUnavailableError(
                "local adapter has no injected transport")
        payload = {
            "schema": PROVIDER_SCHEMA,
            "schema_version": PROVIDER_SCHEMA_VERSION,
            "endpoint": self._endpoint,
            "task_id": request.task_id,
            "model_id": request.model_id,
            "model_revision": request.model_revision,
            "prompt": request.prompt,
            "context_refs": list(request.context_refs),
            "system_constraints": list(request.system_constraints),
            "max_output_tokens": request.max_output_tokens,
            "temperature": float(request.temperature),
            "deadline_s": float(request.deadline_s),
            "output_schema": request.output_schema,
        }
        start = self._clock()
        try:
            response = self._transport(payload)
        except ModelProviderError:
            raise
        except Exception as exc:  # transport is foreign code
            raise ProviderFailedError(
                f"local transport failed: {type(exc).__name__}") from None
        elapsed = self._clock() - start
        if elapsed > float(request.deadline_s):
            raise DeadlineExceededError(
                f"local adapter exceeded deadline_s={request.deadline_s}")
        latency_ms = int(round(elapsed * 1000))
        base = dict(task_id=request.task_id, provider_name=self.name,
                    model_id=request.model_id,
                    model_revision=request.model_revision,
                    input_tokens=request.input_tokens,
                    latency_ms=latency_ms)
        if not isinstance(response, Mapping):
            raise ResponseValidationError(
                f"transport response must be a mapping, got "
                f"{type(response).__name__}")
        if response.get("abstained") is True:
            reason = response.get("abstain_reason")
            if not isinstance(reason, str) or not reason:
                reason = "local model abstained (no reason given)"
            return ModelResult(
                **base, outcome="abstained", performed_inference=False,
                abstain_reason=reason,
                provenance_hash=_provenance(request, self.name, ""))
        text = response.get("text")
        if not isinstance(text, str) or not text:
            raise ResponseValidationError(
                "transport response must carry non-empty text")
        if len(text) > MAX_OUTPUT_CHARS or \
                count_tokens(text) > request.max_output_tokens:
            raise ResponseValidationError(
                "transport response exceeds the output cap; refused, "
                "not silently truncated")
        citations_raw = response.get("citations", [])
        if not isinstance(citations_raw, list) or any(
                not isinstance(c, str) for c in citations_raw):
            raise ResponseValidationError("citations must be a list of strings")
        invented = [c for c in citations_raw if c not in request.context_refs]
        if invented:
            raise ResponseValidationError(
                f"transport invented citations not in the request "
                f"context: {invented}")
        uncertainty = response.get("uncertainty")
        if uncertainty is not None and (
                isinstance(uncertainty, bool)
                or not isinstance(uncertainty, (int, float))
                or not 0.0 <= float(uncertainty) <= 1.0):
            raise ResponseValidationError(
                f"uncertainty must be in 0..1 or absent, got "
                f"{uncertainty!r}")
        structured = response.get("structured")
        if request.output_schema is not None:
            if not isinstance(structured, dict):
                raise ResponseValidationError(
                    "request demanded structured output but the "
                    "transport returned none")
        elif structured is not None and not isinstance(structured, dict):
            raise ResponseValidationError("structured must be a mapping")
        usage = response.get("usage")
        in_tok, out_tok = request.input_tokens, count_tokens(text)
        memory_peak = response.get("memory_bytes_peak")
        if isinstance(usage, Mapping):
            if isinstance(usage.get("input_tokens"), int):
                in_tok = usage["input_tokens"]
            if isinstance(usage.get("output_tokens"), int):
                out_tok = usage["output_tokens"]
        if memory_peak is not None and (
                isinstance(memory_peak, bool)
                or not isinstance(memory_peak, int) or memory_peak < 0):
            raise ResponseValidationError(
                "memory_bytes_peak must be a non-negative int or absent")
        completed = dict(base)
        completed["input_tokens"] = in_tok
        return ModelResult(
            **completed, outcome="completed", text=text,
            structured=structured, citations=tuple(citations_raw),
            uncertainty=uncertainty,
            output_tokens=out_tok, memory_bytes_peak=memory_peak,
            performed_inference=True,
            provenance_hash=_provenance(request, self.name, text))


def _failure_result(request: ModelRequest, provider_name: str,
                    model_id: str, model_revision: str, outcome: str,
                    error: str) -> ModelResult:
    return ModelResult(
        task_id=request.task_id, provider_name=provider_name,
        model_id=model_id, model_revision=model_revision,
        outcome=outcome, input_tokens=request.input_tokens,
        error=error, performed_inference=False,
        provenance_hash=_provenance(request, provider_name, ""))


def run_request(provider: Any, request: ModelRequest,
                cancel_token: Optional[CancellationToken] = None
                ) -> ModelResult:
    """Failure-isolating facade: model events never raise.

    A malformed request still raises MalformedRequestError (caller
    bug).  Every provider-side event -- failure, unavailability,
    cancellation, deadline, invalid response, even an unexpected
    exception from foreign provider code -- returns a ModelResult
    outcome instead, so observation, undo, recovery and emergency
    stop proceed with no model at all (P6 exit criterion).
    """
    _require_request(request)
    provider_name = getattr(provider, "name", None) or "unknown"
    if not isinstance(provider_name, str):
        provider_name = "unknown"
    try:
        result = provider.generate(request, cancel_token)
    except RequestCancelledError as exc:
        return _failure_result(request, provider_name, request.model_id,
                               request.model_revision, "cancelled",
                               str(exc))
    except ProviderUnavailableError as exc:
        return _failure_result(request, provider_name, request.model_id,
                               request.model_revision, "unavailable",
                               str(exc))
    except DeadlineExceededError as exc:
        return _failure_result(request, provider_name, request.model_id,
                               request.model_revision, "failed",
                               "deadline exceeded: " + str(exc))
    except ModelProviderError as exc:
        return _failure_result(request, provider_name, request.model_id,
                               request.model_revision, "failed", str(exc))
    except Exception as exc:  # foreign provider code must not crash callers
        return _failure_result(
            request, provider_name, request.model_id,
            request.model_revision, "failed",
            f"unexpected provider error: {type(exc).__name__}")
    if not isinstance(result, ModelResult):
        return _failure_result(
            request, provider_name, request.model_id,
            request.model_revision, "failed",
            f"provider returned {type(result).__name__}, not ModelResult")
    if result.task_id != request.task_id:
        return _failure_result(
            request, provider_name, request.model_id,
            request.model_revision, "failed",
            "provider returned a result for a different task_id")
    return result


def run_with_fallback(providers: List[Any], request: ModelRequest,
                      cancel_token: Optional[CancellationToken] = None
                      ) -> ModelResult:
    """Try ONLY the given providers in order; never invent another.

    Returns the first completed or abstained result.  If every
    provider fails, returns the last failure result.  An empty
    provider list is an honest unavailable result, not an error.
    """
    _require_request(request)
    if not providers:
        return _failure_result(request, "none", request.model_id,
                               request.model_revision, "unavailable",
                               "no providers configured")
    last: Optional[ModelResult] = None
    for provider in providers:
        last = run_request(provider, request, cancel_token)
        if last.outcome in ("completed", "abstained"):
            return last
        if last.outcome == "cancelled":
            return last
    assert last is not None
    return last


def create_provider(settings: Mapping[str, Any]) -> Any:
    """Build a provider from opt-in settings; no cloud fallback exists.

    ``{"provider": "mock"}`` (the default) builds the mock.
    ``{"provider": "local", "enabled": True, "endpoint": ...,
    "transport": callable}`` builds the local adapter; the transport
    is injected by the caller, never constructed here.  Any other
    provider name is refused: this protocol has no cloud provider
    and settings cannot smuggle one in.
    """
    if not isinstance(settings, Mapping):
        raise UnsupportedCapabilityError(
            f"settings must be a mapping, got {type(settings).__name__}")
    name = settings.get("provider", "mock")
    if name == "mock":
        return MockModelProvider()
    if name == "local":
        return LocalInferenceAdapter(
            endpoint=settings.get("endpoint", "local://aesir"),
            transport=settings.get("transport"),
            enabled=bool(settings.get("enabled", False)),
            model_id=settings.get("model_id", "local-1"),
            model_revision=settings.get("model_revision", "local-rev-1"))
    raise UnsupportedCapabilityError(
        f"unknown provider {name!r}; the protocol ships 'mock' and "
        f"'local' only and has no implicit cloud fallback")


__all__ = [
    "PROVIDER_SCHEMA", "PROVIDER_SCHEMA_VERSION", "OUTCOMES",
    "OUTPUT_SCHEMAS", "MAX_PROMPT_CHARS", "MAX_OUTPUT_CHARS",
    "MAX_CONTEXT_REFS", "MAX_INPUT_TOKENS", "MAX_OUTPUT_TOKENS",
    "ABSTAIN_MARKER", "FAIL_MARKER",
    "ModelProviderError", "MalformedRequestError",
    "MalformedResultError", "UnsupportedCapabilityError",
    "ProviderUnavailableError", "ProviderFailedError",
    "RequestCancelledError", "DeadlineExceededError",
    "ResponseValidationError", "CloudFallbackForbiddenError",
    "count_tokens", "CancellationToken", "ModelRequest",
    "request_from_dict", "ModelCapabilities", "ModelResult",
    "result_from_dict", "ModelProvider", "MockModelProvider",
    "LocalInferenceAdapter", "Transport", "run_request",
    "run_with_fallback", "create_provider",
]
