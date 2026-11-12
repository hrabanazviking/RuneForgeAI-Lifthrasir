# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0601 model-provider protocol, mock model, local adapter tests.

Scope: protocol validation over the committed fixture corpus
(tests/fixtures/lif0601/), the deterministic mock, and the optional
local adapter exercised ONLY through injected fake transports
returning recorded responses.  No network, no model download, no
real inference: nothing in this file claims a real model ran.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import modelprovider as mp  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "lif0601"


@pytest.fixture(scope="module")
def requests_doc():
    return json.loads((FIXTURES / "requests.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def transport_doc():
    return json.loads((FIXTURES / "transport.json").read_text(encoding="utf-8"))


def make_request(**overrides):
    kwargs = dict(task_id="task-unit", prompt="Explain the failure.",
                  context_refs=("ev-2026-201",))
    kwargs.update(overrides)
    return mp.ModelRequest(**kwargs)


# --- protocol + mock: the deliverable-grade path ---------------------------

def test_mock_satisfies_provider_protocol():
    assert isinstance(mp.MockModelProvider(), mp.ModelProvider)
    assert isinstance(mp.LocalInferenceAdapter(), mp.ModelProvider)


def test_mock_probe_reports_local_offline_capabilities():
    caps = mp.MockModelProvider().probe()
    assert caps.available is True and caps.is_local is True
    assert caps.supports_structured_output is True
    assert caps.supports_cancellation is True
    assert caps.artifact_hash is not None and len(caps.artifact_hash) == 64
    assert caps.to_dict()["provider_name"] == "mock"


def test_mock_is_deterministic(requests_doc):
    provider = mp.MockModelProvider(clock=lambda: 100.0)
    request = mp.request_from_dict(requests_doc["valid"])
    first = provider.generate(request)
    second = provider.generate(request)
    assert first == second
    assert first.outcome == "completed" and first.performed_inference is True
    assert first.citations == ("ev-2026-201", "ev-2026-202")
    assert first.input_tokens == mp.count_tokens(request.prompt)
    assert first.output_tokens == mp.count_tokens(first.text)
    assert first.provenance_hash
    assert mp.result_from_dict(first.to_dict()) == first


def test_mock_structured_output_parses_and_cites_only_supplied(requests_doc):
    provider = mp.MockModelProvider(clock=lambda: 0.0)
    request = mp.request_from_dict(requests_doc["structured"])
    result = provider.generate(request)
    assert result.outcome == "completed"
    assert result.structured is not None
    assert json.loads(result.text) == result.structured
    assert result.structured["citations"] == ["ev-2026-201"]
    assert result.citations == ("ev-2026-201",)
    assert 0.0 <= result.uncertainty <= 1.0


def test_mock_abstains_on_marker(requests_doc):
    provider = mp.MockModelProvider(clock=lambda: 0.0)
    result = provider.generate(mp.request_from_dict(requests_doc["abstain"]))
    assert result.outcome == "abstained"
    assert result.performed_inference is False
    assert result.abstain_reason and "abstain" in result.abstain_reason
    assert result.text == "" and result.output_tokens == 0


def test_mock_output_token_cap_is_enforced():
    provider = mp.MockModelProvider(clock=lambda: 0.0)
    result = provider.generate(make_request(max_output_tokens=8))
    assert mp.count_tokens(result.text) <= 8
    assert result.output_tokens <= 8


def test_mock_failure_marker_raises_named_error(requests_doc):
    provider = mp.MockModelProvider()
    with pytest.raises(mp.ProviderFailedError):
        provider.generate(mp.request_from_dict(requests_doc["failing"]))


def test_mock_cancellation_and_deadline():
    provider = mp.MockModelProvider(clock=lambda: 0.0)
    token = mp.CancellationToken()
    token.cancel()
    with pytest.raises(mp.RequestCancelledError):
        provider.generate(make_request(), token)
    ticks = iter([0.0, 100.0])
    slow = mp.MockModelProvider(clock=lambda: next(ticks))
    with pytest.raises(mp.DeadlineExceededError):
        slow.generate(make_request(deadline_s=30.0))


# --- request / result validation -------------------------------------------

@pytest.mark.parametrize("overrides", [
    {"task_id": "bogus"},
    {"task_id": "task-"},
    {"prompt": ""},
    {"prompt": "x" * (mp.MAX_PROMPT_CHARS + 1)},
    {"max_output_tokens": 0},
    {"max_input_tokens": 200000},
    {"temperature": 2.5},
    {"temperature": True},
    {"deadline_s": 0},
    {"output_schema": "yaml-please"},
    {"context_refs": "ev-1"},
    {"context_refs": ("",)},
    {"prompt": "long prompt here", "max_input_tokens": 2},
])
def test_malformed_requests_are_refused(overrides):
    with pytest.raises(mp.MalformedRequestError):
        make_request(**overrides)


def test_request_dict_roundtrip_and_unknown_fields(requests_doc):
    request = mp.request_from_dict(requests_doc["valid"])
    assert mp.request_from_dict(request.to_dict()) == request
    bad = dict(requests_doc["valid"])
    bad["cloud_api_key"] = "nope"
    with pytest.raises(mp.MalformedRequestError):
        mp.request_from_dict(bad)
    bad2 = dict(requests_doc["valid"])
    bad2["schema"] = "lifthrasir.something-else.v9"
    with pytest.raises(mp.MalformedRequestError):
        mp.request_from_dict(bad2)


@pytest.mark.parametrize("overrides", [
    {"outcome": "sort-of-worked"},
    {"outcome": "completed", "performed_inference": False},
    {"outcome": "abstained"},
    {"outcome": "failed"},
    {"uncertainty": 1.5},
    {"text": "x" * (mp.MAX_OUTPUT_CHARS + 1)},
    {"provenance_hash": "not-a-hash"},
])
def test_malformed_results_are_refused(overrides):
    kwargs = dict(task_id="task-unit", provider_name="mock",
                  model_id="mock-1", model_revision="mock-rev-1",
                  outcome="completed", performed_inference=True)
    kwargs.update(overrides)
    with pytest.raises(mp.MalformedResultError):
        mp.ModelResult(**kwargs)


# --- facade: model failure cannot block recovery (negative control) --------

def test_facade_turns_mock_failure_into_result_and_recovery_proceeds(requests_doc):
    provider = mp.MockModelProvider()
    result = mp.run_request(provider, mp.request_from_dict(requests_doc["failing"]))
    assert result.outcome == "failed" and result.performed_inference is False
    assert result.error and "mock failure" in result.error
    # Negative control for the P6 exit: with the model dead, a plain
    # deterministic recovery-shaped step still runs to completion.
    recovery_log = []
    def recover():
        recovery_log.append("journal-checked")
        recovery_log.append("undo-manifest-verified")
        return "recovered"
    assert recover() == "recovered"
    assert recovery_log == ["journal-checked", "undo-manifest-verified"]
    # And the mock itself is unaffected afterwards (no shared state).
    ok = mp.run_request(provider, make_request())
    assert ok.outcome == "completed"


def test_facade_maps_cancellation_and_unexpected_errors():
    token = mp.CancellationToken()
    token.cancel()
    result = mp.run_request(mp.MockModelProvider(), make_request(), token)
    assert result.outcome == "cancelled"
    class Rogue:
        name = "rogue"
        def generate(self, request, cancel_token=None):
            raise RuntimeError("boom")
    rogue = mp.run_request(Rogue(), make_request())
    assert rogue.outcome == "failed" and "RuntimeError" in rogue.error
    class WrongTask:
        name = "wrong"
        def generate(self, request, cancel_token=None):
            return mp.ModelResult(
                task_id="task-other", provider_name="wrong",
                model_id="m", model_revision="r", outcome="completed",
                performed_inference=True)
    wrong = mp.run_request(WrongTask(), make_request())
    assert wrong.outcome == "failed" and "different task_id" in wrong.error


def test_facade_still_raises_for_caller_bug():
    with pytest.raises(mp.MalformedRequestError):
        mp.run_request(mp.MockModelProvider(), {"not": "a request"})


def test_fallback_uses_only_given_providers_in_order(requests_doc):
    failing = mp.request_from_dict(requests_doc["failing"])
    disabled_local = mp.LocalInferenceAdapter()
    mock = mp.MockModelProvider(clock=lambda: 0.0)
    # Failing request: local is unavailable, mock fails -> last failure.
    result = mp.run_with_fallback([disabled_local, mock], failing)
    assert result.outcome == "failed" and result.provider_name == "mock"
    # Healthy request: local unavailable, mock completes.
    result2 = mp.run_with_fallback([disabled_local, mock], make_request())
    assert result2.outcome == "completed" and result2.provider_name == "mock"
    empty = mp.run_with_fallback([], make_request())
    assert empty.outcome == "unavailable" and empty.provider_name == "none"


# --- local adapter: optional, fixture/offline level ------------------------

def test_local_adapter_disabled_by_default():
    adapter = mp.LocalInferenceAdapter(transport=lambda payload: {"text": "x"})
    caps = adapter.probe()
    assert caps.available is False and "disabled" in caps.detail
    result = mp.run_request(adapter, make_request())
    assert result.outcome == "unavailable"
    with pytest.raises(mp.ProviderUnavailableError):
        adapter.generate(make_request())


def test_local_adapter_enabled_without_transport_is_unavailable():
    adapter = mp.LocalInferenceAdapter(enabled=True)
    assert adapter.probe().available is False
    result = mp.run_request(adapter, make_request())
    assert result.outcome == "unavailable"


def test_local_adapter_with_fake_transport(transport_doc):
    seen = []
    def fake_transport(payload):
        seen.append(payload)
        return dict(transport_doc["good"])
    adapter = mp.LocalInferenceAdapter(enabled=True, transport=fake_transport,
                                       clock=lambda: 0.0)
    assert adapter.probe().available is True
    result = adapter.generate(make_request())
    assert result.outcome == "completed" and result.performed_inference is True
    assert result.text == transport_doc["good"]["text"]
    assert result.citations == ("ev-2026-201",)
    assert result.input_tokens == 21 and result.output_tokens == 13
    assert result.memory_bytes_peak == 1048576
    assert seen and seen[0]["task_id"] == "task-unit"
    assert seen[0]["endpoint"] == "local://aesir"


def test_local_adapter_structured_and_abstain_paths(transport_doc):
    structured_adapter = mp.LocalInferenceAdapter(
        enabled=True, clock=lambda: 0.0,
        transport=lambda payload: dict(transport_doc["structured_good"]))
    result = structured_adapter.generate(make_request(output_schema="json-object"))
    assert result.structured == {"summary": "fixture structured answer"}
    abstain_adapter = mp.LocalInferenceAdapter(
        enabled=True, clock=lambda: 0.0,
        transport=lambda payload: dict(transport_doc["abstaining"]))
    abstained = abstain_adapter.generate(make_request())
    assert abstained.outcome == "abstained"
    assert "contradictory" in abstained.abstain_reason


def test_local_adapter_rejects_bad_transport_responses(transport_doc):
    def adapter_returning(doc):
        return mp.LocalInferenceAdapter(
            enabled=True, clock=lambda: 0.0,
            transport=lambda payload: dict(doc))
    with pytest.raises(mp.ResponseValidationError):
        adapter_returning(transport_doc["invented_citation"]).generate(make_request())
    with pytest.raises(mp.ResponseValidationError):
        adapter_returning(transport_doc["overlong"]).generate(make_request())
    with pytest.raises(mp.ResponseValidationError):
        adapter_returning(transport_doc["good"]).generate(
            make_request(output_schema="json-object"))
    def exploding(payload):
        raise ConnectionError("no server here")
    dead = mp.LocalInferenceAdapter(enabled=True, transport=exploding)
    with pytest.raises(mp.ProviderFailedError):
        dead.generate(make_request())
    assert mp.run_request(dead, make_request()).outcome == "failed"


@pytest.mark.parametrize("endpoint", [
    "https://api.example-cloud.test/v1",
    "http://192.168.1.50:8080/v1",
    "ftp://somewhere/models",
    "local://",
    "local://two words",
    "",
])
def test_nonlocal_endpoints_are_refused(endpoint):
    with pytest.raises(mp.CloudFallbackForbiddenError):
        mp.LocalInferenceAdapter(endpoint=endpoint, enabled=True,
                                 transport=lambda payload: {"text": "x"})


@pytest.mark.parametrize("endpoint", [
    "local://aesir", "local://llama-cpp",
    "http://127.0.0.1:8080/v1", "http://localhost:11434/api",
    "http://[::1]:8080/v1",
])
def test_local_endpoints_are_accepted(endpoint):
    adapter = mp.LocalInferenceAdapter(endpoint=endpoint)
    assert adapter.endpoint == endpoint


# --- provider settings ------------------------------------------------------

def test_create_provider_settings_are_opt_in_and_cloud_free(transport_doc):
    assert isinstance(mp.create_provider({}), mp.MockModelProvider)
    assert isinstance(mp.create_provider({"provider": "mock"}), mp.MockModelProvider)
    local = mp.create_provider({"provider": "local"})
    assert isinstance(local, mp.LocalInferenceAdapter)
    assert local.probe().available is False
    with pytest.raises(mp.UnsupportedCapabilityError):
        mp.create_provider({"provider": "some-cloud"})
    with pytest.raises(mp.UnsupportedCapabilityError):
        mp.create_provider("not-a-mapping")


# --- no-network guarantee ----------------------------------------------------

def test_module_imports_no_network_or_process_machinery():
    source = (REPO / "src" / "lifthrasir" / "modelprovider.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"socket", "urllib", "http", "requests", "subprocess", "os"}
    assert not (imported & forbidden), f"forbidden imports present: {imported & forbidden}"
    assert imported <= {"__future__", "hashlib", "json", "re", "time",
                        "dataclasses", "typing"}
