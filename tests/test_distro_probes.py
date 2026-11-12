# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1101 tests: distro capability probes and adapter contracts.

Checked five ways: (1) every fixture host probes to its recorded
expectations (family, variant, deployment model, mode, key
capability values and outcomes) from recorded facts alone;
(2) honesty rules -- absent only from complete recordings,
conflicts are errors, an empty LSM list proves nothing, offline
is never assumed, and NO result anywhere claims support;
(3) identification fails closed (unknown family and the
transactional/declarative/image variants are observation-only);
(4) the adapter contract -- every capability probed, all six
methods declared, support claims refused by name, abstention
follows the governing capability; (5) the human document mirrors
the machine contract.  Scope: recordings and fixtures only.  No
test boots a distro, probes a live host, or claims an adapter.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lifthrasir.confinement import PROFILES as CONFINEMENT_PROFILES  # noqa: E402
from lifthrasir.distroprobes import (  # noqa: E402
    ABSTAIN_RULES, ADAPTER_MODES, CAPABILITIES, CONTRACT_METHODS,
    DOCUMENTARY_HINTS, FAMILIES, FAMILY_DISPLAY, KNOWN_VARIANTS,
    PROBE_OUTCOMES, HostFacts, MalformedFactsError,
    SupportClaimError, UnknownCapabilityError, UnknownFamilyError,
    abstention_for, all_contracts, build_evidence_record,
    check_contract_compliance, compare_hints, contract_for_family,
    descriptor_from_report, detect_variant, facts_from_dict,
    identify_family, probe_host, summarize_reports,
    validate_descriptor)

FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "lif1101" /
                       "hosts.json").read_text())
DOC = (ROOT / "docs" / "DISTRO-PROBES.md").read_text()
HOSTS = {h["facts"]["host_id"]: h for h in FIXTURES["hosts"]}


def _report(host_id):
    return probe_host(facts_from_dict(HOSTS[host_id]["facts"]))


def _full_descriptor(host_id="kubuntu-lab"):
    return descriptor_from_report(_report(host_id),
                                  declared_methods=CONTRACT_METHODS)


# --- fixtures -------------------------------------------------------

def test_fixture_hosts_probe_to_expectations():
    assert len(HOSTS) == 9
    for host_id, row in HOSTS.items():
        report = _report(host_id)
        exp = row["expected"]
        assert report.family == exp["family"], host_id
        assert report.variant == exp["variant"], host_id
        assert report.deployment_model == exp["deployment_model"], host_id
        assert report.mode == exp["mode"], host_id
        for cap, value in exp["values"].items():
            assert report.result_for(cap).value == value, (host_id, cap)
        for cap, outcome in exp["outcomes"].items():
            assert report.result_for(cap).outcome == outcome, (host_id, cap)


def test_every_report_probes_every_capability_in_order():
    for host_id in HOSTS:
        report = _report(host_id)
        assert [r.capability for r in report.results] == list(CAPABILITIES)
        assert all(r.outcome in PROBE_OUTCOMES for r in report.results)
        assert report.mode in ADAPTER_MODES


def test_probe_is_deterministic():
    for host_id in HOSTS:
        assert _report(host_id).digest() == _report(host_id).digest()
        assert _report(host_id).to_dict() == _report(host_id).to_dict()


# --- honesty: no support, ever ---------------------------------------

def test_no_result_claims_support():
    # Structured claim fields only: prose details may (and must)
    # NEGATE support ("not claimed supported"); what is forbidden
    # is a mode, outcome or value asserting it.
    for host_id in HOSTS:
        report = _report(host_id)
        assert report.mode in ADAPTER_MODES
        for result in report.results:
            assert result.outcome in PROBE_OUTCOMES
            assert result.value != "supported"
        assert report.deployment_model != "supported"
    assert "supported" not in ADAPTER_MODES
    assert "supported" not in PROBE_OUTCOMES


def test_support_claim_in_descriptor_refused_by_name():
    desc = _full_descriptor()
    desc["status"] = "supported"
    with pytest.raises(SupportClaimError):
        validate_descriptor(desc)
    desc2 = _full_descriptor()
    desc2["supported_distros"] = ["fedora"]
    with pytest.raises(SupportClaimError):
        validate_descriptor(desc2)
    desc3 = _full_descriptor()
    desc3["mode"] = "supported"
    with pytest.raises(SupportClaimError):
        validate_descriptor(desc3)


def test_absent_requires_a_complete_recording():
    partial = _report("partial-recording")
    assert partial.result_for("package_manager").outcome == "unknown"
    assert partial.result_for("service_manager").outcome == "unknown"
    assert all(r.outcome != "absent" for r in partial.results)
    kubuntu = _report("kubuntu-lab")
    assert kubuntu.result_for("snapshot_strategy").outcome == "absent"


def test_empty_lsm_list_never_proves_mac_absence():
    arch = _report("arch-rolling")
    assert arch.result_for("mac_policy").outcome == "unknown"
    assert arch.result_for("mac_policy").value is None


def test_offline_is_never_assumed():
    for host_id in HOSTS:
        result = _report(host_id).result_for("offline_availability")
        assert result.outcome == "unknown", host_id


def test_conflicting_package_managers_are_an_error():
    facts = HostFacts(
        host_id="conflicted", os_release_text="ID=debian\n",
        present_commands=("apt", "dpkg", "dnf", "rpm"),
        complete_commands=True)
    result = probe_host(facts).result_for("package_manager")
    assert result.outcome == "error" and result.value is None


def test_probe_wins_over_family_assumption_for_init():
    report = _report("debian-sysv")
    assert report.family == "debian"
    assert report.result_for("service_manager").value == "openrc"


def test_hints_agree_disagree_and_probe_stands():
    rows = {r["capability"]: r for r in compare_hints(_report("fedora-workstation"))}
    assert rows["package_manager"]["status"] == "agree"
    assert rows["mac_policy"]["status"] == "agree"
    rows = {r["capability"]: r for r in compare_hints(_report("debian-sysv"))}
    assert rows["mac_policy"]["status"] == "agree"
    facts = HostFacts(
        host_id="fedora-selinux-off", os_release_text="ID=fedora\n",
        present_commands=("systemctl", "dnf", "rpm"),
        lsm_list=("apparmor",), complete_commands=True)
    report = probe_host(facts)
    rows = {r["capability"]: r for r in compare_hints(report)}
    assert rows["mac_policy"]["status"] == "disagree"
    assert report.result_for("mac_policy").value == "apparmor"  # probe stands
    assert compare_hints(_report("void-unknown")) == []


def test_hints_match_confinement_review_where_they_overlap():
    for family in ("ubuntu", "debian", "fedora", "opensuse"):
        profile = CONFINEMENT_PROFILES[family]
        assert DOCUMENTARY_HINTS[family]["package_manager"] == profile.package_manager
    assert DOCUMENTARY_HINTS["ubuntu"]["mac_policy"] == "apparmor"
    assert DOCUMENTARY_HINTS["fedora"]["mac_policy"] == "selinux"
    assert DOCUMENTARY_HINTS["opensuse"]["mac_policy"] is None  # conditional


# --- identification fails closed --------------------------------------

def test_identify_family_mapping_and_unknown():
    assert identify_family("ID=kubuntu\n") == "ubuntu"
    assert identify_family('ID="opensuse-tumbleweed"\n') == "opensuse"
    assert identify_family("ID=arch\n") == "arch"
    assert identify_family("ID=void\n") is None
    assert identify_family("ID=nixos\n") is None


def test_variants_force_observation_only():
    assert detect_variant("ID=nixos\n") == "nixos"
    assert _report("microos-host").variant == "opensuse-microos"
    assert _report("microos-host").mode == "observation-only"
    for variant in KNOWN_VARIANTS:
        assert variant in DOC
    facts = HostFacts(
        host_id="nixos-host", os_release_text="ID=nixos\n",
        present_commands=("systemctl",), complete_commands=True)
    report = probe_host(facts)
    assert report.deployment_model == "declarative"
    assert report.mode == "observation-only" and report.family is None


def test_unknown_family_is_observation_only():
    report = _report("void-unknown")
    assert report.family is None and report.mode == "observation-only"
    assert report.result_for("service_manager").value == "runit"


# --- contracts ----------------------------------------------------------

def test_contracts_cover_all_families_capabilities_methods():
    contracts = all_contracts()
    assert [c.family for c in contracts] == list(FAMILIES)
    for contract in contracts:
        assert contract.capabilities == CAPABILITIES
        assert contract.methods == CONTRACT_METHODS
        assert contract.abstain_rules == ABSTAIN_RULES
        assert contract.display == FAMILY_DISPLAY[contract.family]
    with pytest.raises(UnknownFamilyError):
        contract_for_family("nixos")
    with pytest.raises(UnknownFamilyError):
        contract_for_family("void")


def test_descriptor_validation_and_compliance():
    desc = _full_descriptor()
    assert validate_descriptor(desc) == []
    assert check_contract_compliance(desc) == []
    broken = _full_descriptor()
    del broken["capabilities"]["mac_policy"]
    errors = validate_descriptor(broken)
    assert any("unprobed" in e for e in errors)
    lazy = descriptor_from_report(_report("kubuntu-lab"),
                                  declared_methods=("identify",))
    violations = check_contract_compliance(lazy)
    assert any("not declared" in v for v in violations)
    bad = _full_descriptor()
    bad["surprise"] = True
    assert any("unknown descriptor keys" in e
               for e in validate_descriptor(bad))


def test_transactional_descriptor_must_be_observation_only():
    desc = descriptor_from_report(_report("microos-host"),
                                  declared_methods=CONTRACT_METHODS)
    assert check_contract_compliance(desc) == []
    desc["mode"] = "probe-only"
    assert any("observation-only" in v
               for v in check_contract_compliance(desc))


def test_abstention_follows_governing_capability_and_mode():
    desc = _full_descriptor()  # kubuntu: snapshots absent, rest present
    assert abstention_for(desc, "rollback_claims") is True
    assert abstention_for(desc, "package_actions") is False
    assert abstention_for(desc, "inference_actions") is False
    microos = descriptor_from_report(_report("microos-host"),
                                     declared_methods=CONTRACT_METHODS)
    assert all(abstention_for(microos, op) for op in ABSTAIN_RULES)
    partial = descriptor_from_report(_report("partial-recording"),
                                     declared_methods=CONTRACT_METHODS)
    assert abstention_for(partial, "package_actions") is True  # unknown
    with pytest.raises(UnknownCapabilityError):
        abstention_for(desc, "kernel_actions")


def test_unknown_capability_refused_by_name():
    with pytest.raises(UnknownCapabilityError):
        _report("kubuntu-lab").result_for("teleportation")


# --- facts discipline -----------------------------------------------------

def test_malformed_facts_refused():
    with pytest.raises(MalformedFactsError):
        HostFacts(host_id="Bad Host", os_release_text="ID=debian\n")
    with pytest.raises(MalformedFactsError):
        HostFacts(host_id="ok-host", os_release_text="  ")
    with pytest.raises(MalformedFactsError):
        facts_from_dict({"host_id": "x", "os_release_text": "ID=debian\n",
                         "surprise": 1})
    with pytest.raises(MalformedFactsError):
        facts_from_dict({"host_id": "x", "os_release_text": "ID=debian\n",
                         "present_commands": "apt"})


def test_summary_counts_coverage_not_support():
    summary = summarize_reports([_report(h) for h in HOSTS])
    assert summary["hosts"] == 9
    assert summary["unknown_family"] == 1
    assert summary["by_mode"]["observation-only"] == 3
    assert summary["by_mode"]["probe-only"] == 6
    assert "supported" not in json.dumps(summary).lower().replace(
        "no host counted here is claimed supported", "")


def test_evidence_record_is_reproducer_rung():
    record = build_evidence_record(
        _report("kubuntu-lab"), recorded_at="2026-11-12T05:30:00Z",
        incident_id="inc-lif1101-probes")
    assert record["evidence_status"] == "reproducer"
    assert record["kind"] == "test-run" and record["tool_versions"]
    assert record["content_digest"].startswith("sha256:")
    assert any("LIF-1102" in limit for limit in record["limitations"])
    again = build_evidence_record(
        _report("kubuntu-lab"), recorded_at="2026-11-12T05:30:00Z",
        incident_id="inc-lif1101-probes")
    assert again["evidence_id"] == record["evidence_id"]


# --- document mirrors the machine contract --------------------------------

def test_document_mirrors_module():
    for capability in CAPABILITIES:
        assert capability in DOC, capability
    for family in FAMILIES:
        assert FAMILY_DISPLAY[family].split("(")[0].strip() in DOC, family
    for method in CONTRACT_METHODS:
        assert method in DOC, method
    for operation, capability in ABSTAIN_RULES.items():
        assert operation in DOC and capability in DOC
    for host_id in HOSTS:
        assert host_id in DOC, host_id
    assert "NOT verified" in DOC
    assert "No distro or architecture is" in DOC
    assert "LIF-1102" in DOC


def test_module_reads_no_live_host_and_executes_nothing():
    source = (ROOT / "src" / "lifthrasir" / "distroprobes.py").read_text()
    for banned in ("subprocess", "os.system", "socket", "urllib",
                   "requests", "os.chmod", "os.chown", "open("):
        assert banned not in source, banned
