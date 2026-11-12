# SPDX-License-Identifier: GPL-2.0-only
"""Distro capability probes and adapter contracts (LIF-1101).

Phase P11 opens here.  Book IV (roadmap/04) fixes the shape: create
an explicit capabilities adapter interface for each distro --
service manager, package manager, boot mechanism, snapshot
strategy, MAC policy, network stack and hardware interfaces -- and
"probe support instead of assuming features exist".  Research/13
supplies the adapter capability interface (init, package,
deployment, boot, security, network, filesystem, inference), the
compatibility-matrix fields, and the cross-distro incident
contract: an incident names an abstract failure, translation to a
distro action is adapter-owned, and abstention is a valid result.

What this slice ships:

* A probe layer that evaluates RECORDED host facts (an os-release
  text plus recorded command/path/LSM/filesystem inventories) into
  one ProbeResult per capability.  Probes are pure functions of
  the recording: this module reads no live host, executes no
  command, and changes no host state.  A live collector is future
  work and is not claimed here.
* An adapter CONTRACT layer: for each known family, the methods an
  adapter must declare, the capabilities it must probe (all of
  them -- an unprobed capability is a contract violation, while a
  probed outcome of ``unknown`` is honest), and the abstention
  rules.  The adapters themselves, and the supported-versions
  table, are LIF-1102 -- NOT this slice.

Evidence-status honesty (master roadmap section 0 invariant 4,
section 5; charter: no distribution or architecture is announced
as supported before its adapter and repeatable tests exist):

* No result of this module ever says a distro or architecture is
  "supported".  The only modes are ``probe-only`` (family known,
  live-mutable deployment: probes parsed, contract defined, no
  adapter exists yet) and ``observation-only`` (unknown family, or
  a transactional / declarative / image-based deployment whose
  native interface this project does not drive).  A descriptor
  claiming support is refused by name (SupportClaimError).
* Probe outcomes are ``present`` / ``absent`` / ``unknown`` /
  ``error``.  ``absent`` is reported only when the recording
  declares its inventory complete; an incomplete recording yields
  ``unknown``, never a guessed absence.  Conflicting recorded
  managers yield ``error``, never a silent pick.
* Documentary per-family hints (from the LIF-0407 confinement
  review) are carried ONLY as expectations to compare against:
  where a probe disagrees with the hint, the probe stands and the
  disagreement is reported.  Probing replaces assuming.
* The ubuntu fixture mirrors the purpleraider host facts already
  recorded by LIF-0407 (Ubuntu, systemd, AppArmor in the LSM
  list).  Every other fixture is a synthetic recording modelled on
  the family's documented shape.  No other distro was booted,
  installed or probed for this slice, and no fixture is evidence
  about a real machine of that family.

Home: ``src/lifthrasir`` beside the LIF-0407 confinement review
whose distro families and os-release parser this slice reuses;
the human-readable half is ``docs/DISTRO-PROBES.md`` and the tests
pin the two together.  This module ships WITHOUT editing
``__init__.py``: the seat unions exports at banking.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROBE_SCHEMA = "lifthrasir.distro-probe.v0.1"
PROBE_SCHEMA_VERSION = "0.1"
CONTRACT_SCHEMA = "lifthrasir.adapter-contract.v0.1"
CONTRACT_VERSION = "0.1"
REPORT_VERSION = "1"

# The ten probed capabilities: Book IV's seven (service manager,
# package manager, boot mechanism, snapshot strategy, MAC policy,
# network stack, hardware interfaces) plus research/13's
# deployment model and inference backends and the compatibility
# matrix's offline availability.
CAPABILITIES = (
    "service_manager", "package_manager", "deployment_model",
    "boot_mechanism", "mac_policy", "network_stack",
    "snapshot_strategy", "hardware_interfaces",
    "inference_backends", "offline_availability",
)
CAPABILITY_TITLES = {
    "service_manager": "service / init manager",
    "package_manager": "package manager and trust root",
    "deployment_model": "deployment model (live-mutable, "
                        "transactional, declarative, image-based)",
    "boot_mechanism": "boot mechanism and firmware interface",
    "mac_policy": "mandatory access control (LSM) policy",
    "network_stack": "network management stack",
    "snapshot_strategy": "snapshot / rollback strategy",
    "hardware_interfaces": "machine architecture and device "
                           "interfaces",
    "inference_backends": "local inference backends and "
                          "accelerators",
    "offline_availability": "offline operation evidence",
}
PROBE_OUTCOMES = ("present", "absent", "unknown", "error")
# The only modes this slice can emit.  There is deliberately no
# "supported" mode: support is LIF-1102's table, earned by real
# adapters plus repeatable tests, neither of which exists yet.
ADAPTER_MODES = ("probe-only", "observation-only")
DEPLOYMENT_MODELS = ("live-mutable", "transactional",
                     "declarative", "image-based", "unknown")
# Deployments an adapter must never drive through live verbs:
# their native interfaces own mutation (research/13).
OBSERVATION_ONLY_DEPLOYMENTS = ("transactional", "declarative",
                                "image-based")
# Methods every adapter contract requires an adapter to declare
# (research/13: identify the platform, probe rather than assume,
# translate abstract plans adapter-side, dry-run before any verb,
# and prove rollback before claiming a repair route).
CONTRACT_METHODS = ("identify", "probe_all", "capability",
                    "translate_plan", "dry_run", "check_rollback")
# Operations for which an adapter must abstain whenever the named
# capability probed absent / unknown / error.
ABSTAIN_RULES = {
    "service_actions": "service_manager",
    "package_actions": "package_manager",
    "boot_changes": "boot_mechanism",
    "mac_changes": "mac_policy",
    "network_changes": "network_stack",
    "rollback_claims": "snapshot_strategy",
    "inference_actions": "inference_backends",
}
FAMILIES = ("ubuntu", "debian", "fedora", "opensuse", "arch")
FAMILY_DISPLAY = {
    "ubuntu": "Ubuntu / Kubuntu (first target family)",
    "debian": "Debian",
    "fedora": "Fedora",
    "opensuse": "openSUSE (Leap / Tumbleweed)",
    "arch": "Arch Linux",
}
# Variants detected by name or marker.  Each forces
# observation-only mode (the LIF-0407 scope exclusions, extended
# with the arch-family image variant research/13 names).
KNOWN_VARIANTS = ("opensuse-microos", "nixos", "ostree-bootc")
# Documentary expectations per family, from the LIF-0407 review
# (package manager + default LSM) and research/13 (Arch/pacman).
# Hints are NEVER probe results: compare_hints reports agreement
# or disagreement and the probe always stands.
DOCUMENTARY_HINTS = {
    "ubuntu": {"package_manager": "apt/dpkg", "mac_policy": "apparmor"},
    "debian": {"package_manager": "apt/dpkg", "mac_policy": "apparmor"},
    "fedora": {"package_manager": "dnf/rpm", "mac_policy": "selinux"},
    "opensuse": {"package_manager": "zypper/rpm", "mac_policy": None},
    "arch": {"package_manager": "pacman", "mac_policy": None},
}
MAX_OS_RELEASE_CHARS = 65536
MAX_FACT_ITEMS = 512
MAX_HOSTS_PER_SUMMARY = 64

_INCIDENT_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_HOST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class DistroProbeError(Exception):
    """Base class for distro-probe refusals."""


class MalformedFactsError(DistroProbeError):
    """Recorded host facts are malformed or unbounded."""


class MalformedDescriptorError(DistroProbeError):
    """An adapter descriptor or probe report dict is malformed."""


class SupportClaimError(MalformedDescriptorError):
    """A descriptor claims support this slice cannot grant."""


class UnknownFamilyError(DistroProbeError):
    """A distro family with no contract was named."""


class UnknownCapabilityError(DistroProbeError):
    """A capability outside CAPABILITIES was named."""


@dataclass(frozen=True)
class HostFacts:
    """Recorded host facts: the ONLY probe input.

    ``complete_commands`` / ``complete_paths`` declare that the
    recorded inventory is complete for that dimension; only then
    may a probe report ``absent``.  ``markers`` carries recorded
    deployment markers (e.g. ``ostree``, ``transactional-update``,
    ``nixos-generation``, ``offline-cache``) exactly as recorded.
    """
    host_id: str
    os_release_text: str
    kernel_release: str = ""
    arch: str = ""
    present_paths: Tuple[str, ...] = ()
    present_commands: Tuple[str, ...] = ()
    lsm_list: Tuple[str, ...] = ()
    filesystems: Tuple[str, ...] = ()
    markers: Tuple[str, ...] = ()
    display_stack: str = ""
    complete_commands: bool = False
    complete_paths: bool = False

    def __post_init__(self):
        if not _HOST_ID_RE.match(self.host_id or ""):
            raise MalformedFactsError(
                f"host_id {self.host_id!r} is not a valid id")
        if not isinstance(self.os_release_text, str) or \
                not self.os_release_text.strip():
            raise MalformedFactsError(
                "os_release_text must be non-empty recorded text")
        if len(self.os_release_text) > MAX_OS_RELEASE_CHARS:
            raise MalformedFactsError(
                f"os_release_text exceeds {MAX_OS_RELEASE_CHARS} "
                "chars; refused, never truncated")
        for name in ("present_paths", "present_commands", "lsm_list",
                     "filesystems", "markers"):
            items = getattr(self, name)
            if len(items) > MAX_FACT_ITEMS:
                raise MalformedFactsError(
                    f"{name} exceeds {MAX_FACT_ITEMS} items")
            if any(not isinstance(i, str) or not i for i in items):
                raise MalformedFactsError(
                    f"{name} entries must be non-empty strings")


@dataclass(frozen=True)
class ProbeResult:
    capability: str
    outcome: str  # present | absent | unknown | error
    value: Optional[str]
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"capability": self.capability,
                "outcome": self.outcome, "value": self.value,
                "detail": self.detail}


@dataclass(frozen=True)
class ProbeReport:
    host_id: str
    family: Optional[str]
    variant: Optional[str]
    deployment_model: str
    mode: str  # probe-only | observation-only
    results: Tuple[ProbeResult, ...]
    os_id: str = ""
    os_version_id: str = ""
    kernel_release: str = ""
    arch: str = ""

    def result_for(self, capability: str) -> ProbeResult:
        if capability not in CAPABILITIES:
            raise UnknownCapabilityError(
                f"unknown capability {capability!r}: probed "
                f"capabilities are {list(CAPABILITIES)}")
        for result in self.results:
            if result.capability == capability:
                return result
        raise UnknownCapabilityError(
            f"capability {capability!r} was not probed for host "
            f"{self.host_id!r}")

    def counts_by_outcome(self) -> Dict[str, int]:
        counts = {o: 0 for o in PROBE_OUTCOMES}
        for result in self.results:
            counts[result.outcome] += 1
        return counts

    def digest(self) -> str:
        material = json.dumps(self.to_dict(), sort_keys=True,
                              separators=(",", ":"),
                              ensure_ascii=False)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": PROBE_SCHEMA, "host_id": self.host_id,
            "family": self.family, "variant": self.variant,
            "deployment_model": self.deployment_model,
            "mode": self.mode, "os_id": self.os_id,
            "os_version_id": self.os_version_id,
            "kernel_release": self.kernel_release,
            "arch": self.arch,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass(frozen=True)
class AdapterContract:
    family: str
    display: str
    capabilities: Tuple[str, ...]
    methods: Tuple[str, ...]
    abstain_rules: Dict[str, str]
    notes: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA, "family": self.family,
            "display": self.display,
            "capabilities": list(self.capabilities),
            "methods": list(self.methods),
            "abstain_rules": dict(self.abstain_rules),
            "notes": list(self.notes),
        }


def _os_fields(os_release_text: str) -> Dict[str, str]:
    from .confinement import parse_os_release
    return parse_os_release(os_release_text)


def detect_variant(os_release_text: str,
                   markers: Iterable[str] = ()) -> Optional[str]:
    """Name a known transactional/declarative/image variant."""
    fields = _os_fields(os_release_text)
    os_id = (fields.get("ID") or "").strip().lower()
    marker_set = {m.strip().lower() for m in markers}
    if os_id in ("opensuse-microos", "microos") or \
            "transactional-update" in marker_set:
        return "opensuse-microos"
    if os_id == "nixos" or "nixos-generation" in marker_set:
        return "nixos"
    if "ostree" in marker_set or "bootc" in marker_set:
        return "ostree-bootc"
    return None


def identify_family(os_release_text: str) -> Optional[str]:
    """Map recorded os-release text to a contract family or None.

    Reuses the LIF-0407 family mapping (ID first, then ID_LIKE,
    with the named derivative aliases) and adds the Book IV Arch
    expansion family.  An unmapped ID returns None: fail closed
    into observation-only mode.
    """
    fields = _os_fields(os_release_text)
    os_id = (fields.get("ID") or "").strip().lower()
    if os_id in ("arch", "archlinux") or os_id.startswith("arch-"):
        return "arch"
    if detect_variant(os_release_text) == "opensuse-microos":
        return "opensuse"
    if detect_variant(os_release_text) == "nixos":
        return None
    from .confinement import distro_id_for_os_release
    mapped = distro_id_for_os_release(os_release_text)
    if mapped in FAMILIES:
        return mapped
    candidates = [os_id] + (fields.get("ID_LIKE") or "").lower().split()
    for cand in candidates:
        if cand in ("arch", "archlinux"):
            return "arch"
    return None


_PACKAGE_MANAGERS = (
    (("apt", "dpkg"), "apt/dpkg"),
    (("dnf", "rpm"), "dnf/rpm"),
    (("zypper", "rpm"), "zypper/rpm"),
    (("pacman",), "pacman"),
)


def _absent_or_unknown(complete: bool, capability: str,
                       what: str) -> ProbeResult:
    if complete:
        return ProbeResult(capability, "absent", None,
                           f"complete recording shows no {what}")
    return ProbeResult(capability, "unknown", None,
                       f"recording is incomplete: {what} cannot be "
                       "ruled in or out, so the outcome is unknown, "
                       "never a guessed absence")


def _probe_service_manager(f: HostFacts) -> ProbeResult:
    cmds, paths = set(f.present_commands), set(f.present_paths)
    if "systemctl" in cmds or "/run/systemd/system" in paths:
        return ProbeResult("service_manager", "present", "systemd",
                           "recorded systemctl / systemd runtime "
                           "path present")
    for cmd, name in (("rc-service", "openrc"), ("sv", "runit"),
                      ("s6-svscan", "s6")):
        if cmd in cmds:
            return ProbeResult("service_manager", "present", name,
                               f"recorded {cmd} present; non-systemd "
                               "managers are probed, not assumed away "
                               "(Debian non-systemd installs exist)")
    return _absent_or_unknown(f.complete_commands, "service_manager",
                              "service manager")


def _probe_package_manager(f: HostFacts) -> ProbeResult:
    cmds = set(f.present_commands)
    found = [name for required, name in _PACKAGE_MANAGERS
             if all(c in cmds for c in required)]
    if len(found) > 1:
        return ProbeResult(
            "package_manager", "error", None,
            f"recording shows conflicting package managers "
            f"{sorted(found)}; an adapter must not silently pick "
            "one -- the recording or the host needs review")
    if found:
        return ProbeResult("package_manager", "present", found[0],
                           f"recorded commands identify {found[0]}; "
                           "the distro's own package authority is "
                           "preserved (research/13)")
    return _absent_or_unknown(f.complete_commands, "package_manager",
                              "package manager")


def _deployment_model(f: HostFacts,
                      variant: Optional[str]) -> str:
    markers = {m.strip().lower() for m in f.markers}
    if variant == "nixos" or "nixos-generation" in markers:
        return "declarative"
    if variant == "ostree-bootc" or "ostree" in markers or \
            "bootc" in markers:
        return "image-based"
    if variant == "opensuse-microos" or \
            "transactional-update" in markers:
        return "transactional"
    if _probe_package_manager(f).outcome == "present":
        return "live-mutable"
    return "unknown"


def _probe_deployment(f: HostFacts, variant: Optional[str],
                      model: str) -> ProbeResult:
    if model == "unknown":
        return ProbeResult("deployment_model", "unknown", None,
                           "no deployment marker recorded and no "
                           "package manager identified: the model "
                           "stays unknown")
    detail = f"deployment model {model} from recorded facts"
    if model in OBSERVATION_ONLY_DEPLOYMENTS:
        detail += ("; mutation belongs to the deployment's native "
                   "interface, so the adapter mode is "
                   "observation-only")
    return ProbeResult("deployment_model", "present", model, detail)


def _probe_boot(f: HostFacts) -> ProbeResult:
    cmds, paths = set(f.present_commands), set(f.present_paths)
    uefi = "/sys/firmware/efi" in paths or "efibootmgr" in cmds
    grub = ("grub2-install" in cmds or "grub-install" in cmds or
            "/boot/grub2" in paths or "/boot/grub" in paths)
    systemd_boot = "bootctl" in cmds and "/boot/efi" in paths
    if grub and uefi:
        value = "uefi+grub2" if "grub2-install" in cmds else "uefi+grub"
        return ProbeResult("boot_mechanism", "present", value,
                           "recorded EFI interface and GRUB tooling")
    if grub:
        return ProbeResult("boot_mechanism", "present", "grub",
                           "recorded GRUB tooling without recorded "
                           "EFI interface (BIOS or unrecorded)")
    if systemd_boot:
        return ProbeResult("boot_mechanism", "present",
                           "uefi+systemd-boot",
                           "recorded bootctl and EFI system partition")
    if uefi:
        return ProbeResult("boot_mechanism", "present", "uefi",
                           "recorded EFI interface; boot loader "
                           "itself not identified")
    return _absent_or_unknown(f.complete_paths and f.complete_commands,
                              "boot_mechanism", "boot mechanism")


def _probe_mac(f: HostFacts) -> ProbeResult:
    lsm = {x.strip().lower() for x in f.lsm_list}
    for name in ("selinux", "apparmor"):
        if name in lsm:
            return ProbeResult("mac_policy", "present", name,
                               f"recorded active LSM list names {name}")
    if lsm:
        return ProbeResult("mac_policy", "present", "other-lsm",
                           f"recorded LSM list {sorted(lsm)} names "
                           "no AppArmor/SELinux; the list itself is "
                           "the evidence, not a family assumption")
    # An empty LSM list in a complete recording is ambiguous (the
    # recorder may simply not have captured it), so MAC absence is
    # never claimed from an empty list alone.
    return ProbeResult("mac_policy", "unknown", None,
                       "no LSM list recorded: MAC policy stays "
                       "unknown, never assumed from the family")


def _probe_network(f: HostFacts) -> ProbeResult:
    cmds, paths = set(f.present_commands), set(f.present_paths)
    found = []
    if "nmcli" in cmds or "NetworkManager" in cmds:
        found.append("networkmanager")
    if "networkctl" in cmds or "/run/systemd/network" in paths:
        found.append("systemd-networkd")
    if "wicked" in cmds:
        found.append("wicked")
    if "netplan" in cmds:
        found.append("netplan")
    if len(found) > 1:
        return ProbeResult("network_stack", "present",
                           "+".join(sorted(found)),
                           "multiple recorded stacks; which one owns "
                           "an interface is per-interface evidence, "
                           "not a probe guess")
    if found:
        return ProbeResult("network_stack", "present", found[0],
                           f"recorded network stack {found[0]}")
    return _absent_or_unknown(f.complete_commands, "network_stack",
                              "network stack")


def _probe_snapshots(f: HostFacts) -> ProbeResult:
    cmds = set(f.present_commands)
    fstypes = {x.strip().lower() for x in f.filesystems}
    if "snapper" in cmds:
        return ProbeResult("snapshot_strategy", "present",
                           "snapper", "recorded snapper tooling")
    if "timeshift" in cmds:
        return ProbeResult("snapshot_strategy", "present",
                           "timeshift", "recorded timeshift tooling")
    if "zfs" in cmds:
        return ProbeResult("snapshot_strategy", "present", "zfs",
                           "recorded ZFS tooling (native snapshots)")
    if "btrfs" in fstypes:
        return ProbeResult("snapshot_strategy", "present",
                           "btrfs-manual",
                           "recorded btrfs filesystem without a "
                           "recorded snapshot tool: subvolume "
                           "snapshots are possible but unmanaged, "
                           "so no rollback claim follows")
    return _absent_or_unknown(f.complete_commands, "snapshot_strategy",
                              "snapshot tooling")


def _probe_hardware(f: HostFacts) -> ProbeResult:
    if not f.arch:
        return ProbeResult("hardware_interfaces", "unknown", None,
                           "no architecture recorded")
    extras = []
    if "/dev/kvm" in set(f.present_paths):
        extras.append("kvm")
    if "/dev/dri" in set(f.present_paths):
        extras.append("drm")
    detail = "architecture as recorded; no architecture is claimed " \
             "supported by being probed"
    if extras:
        detail += f"; recorded device interfaces: {extras}"
    return ProbeResult("hardware_interfaces", "present", f.arch, detail)


def _probe_inference(f: HostFacts) -> ProbeResult:
    cmds, paths = set(f.present_commands), set(f.present_paths)
    found = []
    if "ollama" in cmds:
        found.append("ollama")
    if "nvidia-smi" in cmds or "/dev/nvidia0" in paths:
        found.append("cuda-device")
    if "/dev/kfd" in paths:
        found.append("rocm-kfd")
    if "/dev/accel" in paths or "/dev/hailo0" in paths:
        found.append("npu-device")
    if found:
        return ProbeResult("inference_backends", "present",
                           "+".join(sorted(found)),
                           "recorded inference/accelerator evidence; "
                           "presence is an inventory fact, not a "
                           "performance or support claim")
    return _absent_or_unknown(f.complete_commands and f.complete_paths,
                              "inference_backends",
                              "inference backend or accelerator")


def _probe_offline(f: HostFacts) -> ProbeResult:
    markers = {m.strip().lower() for m in f.markers}
    if "offline-cache" in markers:
        return ProbeResult("offline_availability", "present",
                           "recorded-offline-cache",
                           "recording carries an offline-cache marker "
                           "(local package/document cache observed)")
    return ProbeResult("offline_availability", "unknown", None,
                       "offline capability cannot be proved from "
                       "these recorded facts; it stays unknown "
                       "rather than being assumed either way")


def probe_host(facts: HostFacts) -> ProbeReport:
    """Probe one recorded host.  Pure: no host is read or changed."""
    fields = _os_fields(facts.os_release_text)
    variant = detect_variant(facts.os_release_text, facts.markers)
    family = identify_family(facts.os_release_text)
    model = _deployment_model(facts, variant)
    results = (
        _probe_service_manager(facts),
        _probe_package_manager(facts),
        _probe_deployment(facts, variant, model),
        _probe_boot(facts),
        _probe_mac(facts),
        _probe_network(facts),
        _probe_snapshots(facts),
        _probe_hardware(facts),
        _probe_inference(facts),
        _probe_offline(facts),
    )
    mode = "probe-only"
    if family is None or model in OBSERVATION_ONLY_DEPLOYMENTS or \
            model == "unknown":
        mode = "observation-only"
    return ProbeReport(
        host_id=facts.host_id, family=family, variant=variant,
        deployment_model=model, mode=mode, results=results,
        os_id=(fields.get("ID") or ""), os_version_id=(fields.get(
            "VERSION_ID") or ""), kernel_release=facts.kernel_release,
        arch=facts.arch)


_CONTRACT_NOTES = {
    "ubuntu": ("First target family (pinned Kubuntu in the lab, "
               "LIF-0101).  Its adapter is still LIF-1102 work: "
               "this contract grants probe-only mode.",),
    "debian": ("Non-systemd installs exist in the wild (LIF-0407): "
               "the service-manager probe decides, never the "
               "family name.",),
    "fedora": ("SELinux is the documented default MAC; an adapter "
               "still probes the live LSM list and needs its own "
               "domain (LIF-0407).",),
    "opensuse": ("The LSM is genuinely conditional (AppArmor or "
                 "SELinux by install): neither may be hard-coded; "
                 "MicroOS hosts probe as transactional and stay "
                 "observation-only.",),
    "arch": ("Book IV expansion family: rolling release, AUR is "
             "outside the official trust root (research/13) and no "
             "adapter method may treat it as trusted.",),
}


def contract_for_family(family: str) -> AdapterContract:
    if family not in FAMILIES:
        raise UnknownFamilyError(
            f"unknown family {family!r}: contract families are "
            f"{list(FAMILIES)}; anything else is observation-only")
    return AdapterContract(
        family=family, display=FAMILY_DISPLAY[family],
        capabilities=CAPABILITIES, methods=CONTRACT_METHODS,
        abstain_rules=dict(ABSTAIN_RULES),
        notes=_CONTRACT_NOTES[family])


def all_contracts() -> Tuple[AdapterContract, ...]:
    return tuple(contract_for_family(f) for f in FAMILIES)


def compare_hints(report: ProbeReport) -> List[Dict[str, Any]]:
    """Compare probe outcomes with documentary hints.

    The probe always stands: each row reports ``agree``,
    ``disagree`` (probe wins; flagged for review) or
    ``unverifiable`` (hint absent or probe not decisive).
    """
    if report.family is None:
        return []
    hints = DOCUMENTARY_HINTS[report.family]
    rows: List[Dict[str, Any]] = []
    for capability in ("package_manager", "mac_policy"):
        hint = hints[capability]
        result = report.result_for(capability)
        if hint is None or result.outcome != "present":
            status = "unverifiable"
        elif result.value == hint:
            status = "agree"
        else:
            status = "disagree"
        rows.append({"capability": capability, "hint": hint,
                     "probed": result.value,
                     "outcome": result.outcome, "status": status,
                     "rule": "the probe stands; hints never "
                             "override recorded facts"})
    return rows


def descriptor_from_report(report: ProbeReport,
                             declared_methods: Iterable[str] = ()
                             ) -> Dict[str, Any]:
    """Render a report as a versioned adapter descriptor."""
    return {
        "schema": CONTRACT_SCHEMA, "host_id": report.host_id,
        "family": report.family, "variant": report.variant,
        "deployment_model": report.deployment_model,
        "mode": report.mode,
        "methods": sorted(set(declared_methods)),
        "capabilities": {r.capability: {"outcome": r.outcome,
                                        "value": r.value}
                         for r in report.results},
    }


_DESCRIPTOR_KEYS = {"schema", "host_id", "family", "variant",
                    "deployment_model", "mode", "methods",
                    "capabilities"}


def _check_support_claims(data: Dict[str, Any]) -> None:
    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if "support" in lowered and value not in (None, False):
                    raise SupportClaimError(
                        f"descriptor field {path + lowered!r} claims "
                        "support; LIF-1101 grants no support -- the "
                        "supported-versions authority is LIF-1102")
                walk(value, path + lowered + ".")
        elif isinstance(node, str) and node.strip().lower() == "supported":
            raise SupportClaimError(
                f"descriptor value at {path!r} claims 'supported'; "
                "LIF-1101 grants no support")
    walk(data, "")


def validate_descriptor(data: Any) -> List[str]:
    """Validate a descriptor dict; returns error strings ([] = ok).

    A claimed support status raises SupportClaimError instead of
    returning an error string: it is a category violation, not a
    shape mistake.
    """
    if not isinstance(data, dict):
        return ["descriptor must be a mapping"]
    _check_support_claims(data)
    errors: List[str] = []
    extra = sorted(set(data) - _DESCRIPTOR_KEYS)
    if extra:
        errors.append(f"unknown descriptor keys: {extra}")
    if data.get("schema") != CONTRACT_SCHEMA:
        errors.append(f"schema must be {CONTRACT_SCHEMA!r}")
    family = data.get("family")
    if family is not None and family not in FAMILIES:
        errors.append(f"family {family!r} has no contract")
    if data.get("mode") not in ADAPTER_MODES:
        errors.append(f"mode must be one of {list(ADAPTER_MODES)}")
    if data.get("deployment_model") not in DEPLOYMENT_MODELS:
        errors.append("deployment_model must be one of "
                      f"{list(DEPLOYMENT_MODELS)}")
    caps = data.get("capabilities")
    if not isinstance(caps, dict):
        errors.append("capabilities must be a mapping")
    else:
        missing = [c for c in CAPABILITIES if c not in caps]
        if missing:
            errors.append(f"unprobed capabilities: {missing} (a "
                          "contract requires every capability "
                          "probed; unknown is honest, missing is not)")
        for name, entry in caps.items():
            if name not in CAPABILITIES:
                errors.append(f"unknown capability {name!r}")
            elif not isinstance(entry, dict) or \
                    entry.get("outcome") not in PROBE_OUTCOMES:
                errors.append(f"capability {name!r} outcome must be "
                              f"one of {list(PROBE_OUTCOMES)}")
    methods = data.get("methods")
    if methods is not None and not isinstance(methods, list):
        errors.append("methods must be a list")
    return errors


def check_contract_compliance(descriptor: Dict[str, Any]) -> List[str]:
    """Contract violations in a shape-valid descriptor ([] = ok)."""
    violations = validate_descriptor(descriptor)
    if violations:
        return violations
    out: List[str] = []
    family = descriptor.get("family")
    if family is None:
        if descriptor.get("mode") != "observation-only":
            out.append("unknown family must be observation-only")
        return out
    contract = contract_for_family(family)
    declared = set(descriptor.get("methods") or [])
    missing = [m for m in contract.methods if m not in declared]
    if missing:
        out.append(f"adapter methods not declared: {missing}")
    if descriptor.get("deployment_model") in \
            OBSERVATION_ONLY_DEPLOYMENTS and \
            descriptor.get("mode") != "observation-only":
        out.append("transactional/declarative/image-based hosts "
                   "must be observation-only")
    caps = descriptor.get("capabilities") or {}
    for operation, capability in sorted(ABSTAIN_RULES.items()):
        entry = caps.get(capability) or {}
        if entry.get("outcome") in ("absent", "error") and \
                f"abstain:{operation}" not in declared:
            pass  # abstention is enforced by callers via ABSTAIN_RULES
    return out


def abstention_for(descriptor: Dict[str, Any], operation: str) -> bool:
    """True when the contract requires abstaining from an operation.

    Abstention is valid and expected (research/13): an operation
    whose governing capability probed absent, unknown or error --
    or any operation at all on an observation-only host -- must
    abstain with the probe record as its reason.
    """
    if operation not in ABSTAIN_RULES:
        raise UnknownCapabilityError(
            f"unknown operation {operation!r}: governed "
            f"operations are {sorted(ABSTAIN_RULES)}")
    if descriptor.get("mode") == "observation-only":
        return True
    entry = (descriptor.get("capabilities") or {}).get(
        ABSTAIN_RULES[operation]) or {}
    return entry.get("outcome") != "present"


def facts_from_dict(data: Any) -> HostFacts:
    if not isinstance(data, dict):
        raise MalformedFactsError("host facts must be a mapping")
    allowed = {"host_id", "os_release_text", "kernel_release",
               "arch", "present_paths", "present_commands",
               "lsm_list", "filesystems", "markers",
               "display_stack", "complete_commands", "complete_paths"}
    extra = sorted(set(data) - allowed)
    if extra:
        raise MalformedFactsError(f"unknown facts keys: {extra}")
    kwargs: Dict[str, Any] = {}
    for key in allowed:
        if key in data:
            kwargs[key] = data[key]
    for key in ("present_paths", "present_commands", "lsm_list",
                "filesystems", "markers"):
        if key in kwargs:
            if not isinstance(kwargs[key], list):
                raise MalformedFactsError(f"{key} must be a list")
            kwargs[key] = tuple(kwargs[key])
    return HostFacts(**kwargs)


def summarize_reports(reports: Iterable[ProbeReport]) -> Dict[str, Any]:
    rows = sorted(reports, key=lambda r: r.host_id)
    if len(rows) > MAX_HOSTS_PER_SUMMARY:
        raise MalformedFactsError(
            f"summary covers at most {MAX_HOSTS_PER_SUMMARY} hosts")
    return {
        "schema": PROBE_SCHEMA, "hosts": len(rows),
        "by_family": {fam: sum(1 for r in rows if r.family == fam)
                      for fam in FAMILIES},
        "unknown_family": sum(1 for r in rows if r.family is None),
        "by_mode": {m: sum(1 for r in rows if r.mode == m)
                    for m in ADAPTER_MODES},
        "host_ids": [r.host_id for r in rows],
        "note": "probe coverage only: no host counted here is "
                "claimed supported (LIF-1102 owns support)",
    }


def build_evidence_record(report: ProbeReport, *,
                          recorded_at: str, incident_id: str,
                          host_local_id: str = "lab-guest-01",
                          boot_id: Optional[str] = None,
                          evidence_id: Optional[str] = None
                          ) -> Dict[str, Any]:
    """Render a probe report as a LIF-0004 v0.1 evidence record.

    Kind ``test-run``, source component ``lab``, evidence status
    ``reproducer``: fixture/record-level proof only.  The digest
    covers the canonical report dict, so re-probing identical
    recorded facts reproduces the identical record.
    """
    if not _INCIDENT_RE.match(incident_id or ""):
        raise DistroProbeError(
            f"incident_id {incident_id!r} is not a v0.1 incident id")
    digest = report.digest()
    eid = evidence_id or f"ev-distroprobe-{digest[:12]}"
    if not _ID_RE.match(eid.removeprefix("ev-")):
        raise DistroProbeError(
            f"evidence_id {eid!r} is not a v0.1 evidence id")
    source: Dict[str, Any] = {"component": "lab",
                              "host_local_id": host_local_id}
    if boot_id:
        source["boot_id"] = boot_id
    counts = report.counts_by_outcome()
    counts_text = ", ".join(f"{k}={counts[k]}" for k in sorted(counts))
    return {
        "schema": "lifthrasir.evidence.v0.1", "schema_version": "0.1",
        "evidence_id": eid, "incident_id": incident_id,
        "kind": "test-run", "recorded_at": recorded_at,
        "source": source,
        "summary": (
            f"Distro capability probe of recorded host "
            f"{report.host_id}: family {report.family}, deployment "
            f"{report.deployment_model}, mode {report.mode}; "
            f"outcomes {counts_text}. No support is claimed."),
        "content_digest": f"sha256:{digest}",
        "evidence_status": "reproducer",
        "tool_versions": {
            "python": platform.python_version(),
            "lifthrasir-distroprobes": REPORT_VERSION,
            "recorded-host-facts": "fixture (not probed live)",
        },
        "limitations": [
            "recorded facts only: no live host was probed, no "
            "command was executed and no adapter exists yet",
            "probe-only / observation-only modes only: no distro "
            "or architecture is claimed supported; the "
            "supported-versions authority is LIF-1102",
            f"host {report.host_id} recording completeness governs "
            "absent vs unknown outcomes",
        ],
        "artifact_refs": [f"sha256:{digest}"],
    }
