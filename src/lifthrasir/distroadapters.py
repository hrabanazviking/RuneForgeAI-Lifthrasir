"""Fedora/Debian/openSUSE adapters + supported-versions table (LIF-1102).

SPDX-License-Identifier: GPL-2.0-only

Home: core package beside the banked LIF-0407 confinement review
(``confinement.py``), whose per-distro profiles this slice reuses
verbatim for package names, critical units and protected paths --
the adapter layer must never drift from the review layer. This
module ships WITHOUT editing ``__init__.py``: the seat unions
exports at banking (precedent LIF-0402/0403/0407).

What an adapter is here, and is not (roadmap section 0 honesty):
* An adapter is DATA + pure rendering: per-distro package-manager
  argv templates, package-concept translation, service/log/trust
  locations, and a support verdict. Rendering a command executes
  NOTHING: there is no subprocess, no host read, no install.
* The supported-versions table below is THE authority for what
  may be called supported (WAVE_PLAN: no distro is announced
  supported until its adapter + tests exist). Today NO row is
  supported: the Fedora/Debian/openSUSE rows are documentary
  (from LIF-0407, labelled documented there; no such distro was
  booted, installed or probed for this slice), so every listed
  version is UNVERIFIED and every unlisted version fails closed
  as UNLISTED. ``is_supported`` therefore returns False for every
  input in this version -- that is the honest table, not a bug.
  A row may move to supported only with lab-verified adapter
  parity evidence on that exact version (P11 graduation gate).
* 1101 independence: LIF-1101 (capability probes + adapter
  contracts) is unbanked and in flight on team-04. This slice
  depends ONLY on banked modules (confinement). It assumes the
  future probe contract will supply os-release text + a distro
  id; ``identify`` consumes exactly that minimal shape. If 1101
  banks a different contract, this module reconciles to it.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from .confinement import get_profile, parse_os_release, distro_id_for_os_release

ADAPTER_VERSION = "0.1"
ADAPTER_SCHEMA = "lifthrasir.distro-adapters.v0.1"
TABLE_VERSION = "0.1"
TABLE_SCHEMA = "lifthrasir.supported-versions.v0.1"
ADAPTER_IDS = ("fedora", "debian", "opensuse")
STATUS_SUPPORTED = "supported"
STATUS_UNVERIFIED = "unverified"
STATUS_UNLISTED = "unlisted"
STATUS_UNSUPPORTED_DISTRO = "unsupported-distro"
SUPPORT_STATUSES = (STATUS_SUPPORTED, STATUS_UNVERIFIED, STATUS_UNLISTED, STATUS_UNSUPPORTED_DISTRO)
OPERATIONS = ("query_package", "refresh_metadata", "install_package", "remove_package", "list_updates", "service_status")
MUTATING_OPERATIONS = ("refresh_metadata", "install_package", "remove_package")

class DistroAdapterError(Exception):
    """Base class for distro-adapter refusals."""
class UnknownAdapterError(DistroAdapterError):
    """Raised when no LIF-1102 adapter exists for a distro id."""
class UnknownOperationError(DistroAdapterError):
    """Raised for an operation outside the adapter vocabulary."""
class UnknownConceptError(DistroAdapterError):
    """Raised for a package concept the profile does not name."""
class MalformedOsReleaseError(DistroAdapterError):
    """Raised when os-release text cannot identify a distro."""

@dataclass(frozen=True)
class SupportedVersion:
    distro_id: str
    version_id: str
    label: str
    kind: str  # point | rolling
    evidence: str  # documented | host-observed
    status: str  # only STATUS_* values; supported needs lab proof
    notes: str

SUPPORTED_VERSIONS = (
    SupportedVersion("fedora", "41", "Fedora 41", "point", "documented", STATUS_UNVERIFIED, "Documentary candidate only; never booted or probed in the lab."),
    SupportedVersion("fedora", "42", "Fedora 42", "point", "documented", STATUS_UNVERIFIED, "Documentary candidate only; never booted or probed in the lab."),
    SupportedVersion("debian", "12", "Debian 12 (bookworm)", "point", "documented", STATUS_UNVERIFIED, "Documentary candidate only; non-systemd installs exist and must be probed, not assumed."),
    SupportedVersion("debian", "13", "Debian 13 (trixie)", "point", "documented", STATUS_UNVERIFIED, "Documentary candidate only; never booted or probed in the lab."),
    SupportedVersion("opensuse", "15.6", "openSUSE Leap 15.6", "point", "documented", STATUS_UNVERIFIED, "Documentary candidate only; transactional variants (MicroOS) are out of scope."),
    SupportedVersion("opensuse", "tumbleweed", "openSUSE Tumbleweed", "rolling", "documented", STATUS_UNVERIFIED, "Rolling release: a version pin cannot certify it; parity must be re-proved continuously."),
    SupportedVersion("ubuntu", "26.10", "Ubuntu 26.10 (reference host)", "point", "host-observed", STATUS_UNVERIFIED, "Reference only: purpleraider host was observed for LIF-0407, but LIF-1102 ships no Ubuntu adapter and host observation is not adapter parity."),
)

@dataclass(frozen=True)
class CommandPlan:
    distro_id: str
    operation: str
    argv: Tuple[str, ...]
    package_name: Optional[str]
    mutating: bool
    note: str

@dataclass(frozen=True)
class DistroAdapter:
    distro_id: str
    display: str
    package_manager: str
    pm_binary: str
    templates: Dict[str, Tuple[str, ...]]
    log_sources: Tuple[str, ...]
    notes: Tuple[str, ...]
    def profile(self):
        return get_profile(self.distro_id)
    def package_names(self) -> Dict[str, str]:
        return dict(self.profile().package_names)
    def critical_units(self):
        return self.profile().extra_critical_units
    def protected_paths(self):
        return self.profile().extra_protected_paths

def _adapter(distro_id, display, pm, binary, templates, logs, notes):
    return DistroAdapter(distro_id, display, pm, binary, templates, logs, notes)

ADAPTERS = {
    "fedora": _adapter("fedora", "Fedora", "dnf/rpm", "dnf", {
        "query_package": ("rpm", "-q", "{package}"),
        "refresh_metadata": ("dnf", "--refresh", "check-update"),
        "install_package": ("dnf", "install", "{package}"),
        "remove_package": ("dnf", "remove", "{package}"),
        "list_updates": ("dnf", "check-update"),
        "service_status": ("systemctl", "status", "{unit}", "--no-pager"),
    }, ("journald", "/var/log/dnf.log"), ("SELinux enforcing by default (LIF-0407 documented).", "Message bus unit is dbus-broker.service, not dbus.service.")),
    "debian": _adapter("debian", "Debian", "apt/dpkg", "apt-get", {
        "query_package": ("dpkg-query", "-W", "{package}"),
        "refresh_metadata": ("apt-get", "update"),
        "install_package": ("apt-get", "install", "{package}"),
        "remove_package": ("apt-get", "remove", "{package}"),
        "list_updates": ("apt-get", "-s", "upgrade"),
        "service_status": ("systemctl", "status", "{unit}", "--no-pager"),
    }, ("journald", "/var/log/apt/history.log", "/var/log/dpkg.log"), ("AppArmor ships enabled with a smaller enforcing set than Ubuntu (LIF-0407).", "Non-systemd installs exist; init must be probed (future LIF-1101), never assumed.")),
    "opensuse": _adapter("opensuse", "openSUSE (Leap / Tumbleweed)", "zypper/rpm", "zypper", {
        "query_package": ("rpm", "-q", "{package}"),
        "refresh_metadata": ("zypper", "refresh"),
        "install_package": ("zypper", "install", "{package}"),
        "remove_package": ("zypper", "remove", "{package}"),
        "list_updates": ("zypper", "list-updates"),
        "service_status": ("systemctl", "status", "{unit}", "--no-pager"),
    }, ("journald", "/var/log/zypp/history"), ("LSM is conditional: AppArmor traditional, SELinux offered; neither may be hard-coded (LIF-0407).", "Transactional variants (MicroOS) out of scope: live verbs must abstain there.")),
}

def get_adapter(distro_id: str) -> DistroAdapter:
    try:
        return ADAPTERS[distro_id]
    except KeyError:
        raise UnknownAdapterError(f"no LIF-1102 adapter for {distro_id!r}: adapters exist for {sorted(ADAPTERS)}; anything else is unsupported-distro and fails closed")

def translate_package(distro_id: str, concept: str) -> str:
    adapter = get_adapter(distro_id)
    names = adapter.package_names()
    if concept not in names:
        raise UnknownConceptError(f"unknown package concept {concept!r} for {distro_id}: known {sorted(names)}")
    return names[concept]

def render_command(distro_id: str, operation: str, package_concept: Optional[str] = None, unit: Optional[str] = None) -> CommandPlan:
    adapter = get_adapter(distro_id)
    if operation not in OPERATIONS:
        raise UnknownOperationError(f"unknown operation {operation!r}: known {list(OPERATIONS)}")
    template = adapter.templates[operation]
    package_name = None
    argv = []
    for part in template:
        if part == "{package}":
            if package_concept is None:
                raise DistroAdapterError(f"operation {operation} requires a package concept")
            package_name = translate_package(distro_id, package_concept)
            argv.append(package_name)
        elif part == "{unit}":
            if not unit:
                raise DistroAdapterError(f"operation {operation} requires a unit name")
            argv.append(unit)
        else:
            argv.append(part)
    mutating = operation in MUTATING_OPERATIONS
    note = "rendered argv only; nothing was executed"
    if mutating:
        note += "; mutating operations additionally require policy ALLOW + human approval + broker execution under roadmap section 0 -- this adapter never executes them"
    return CommandPlan(distro_id, operation, tuple(argv), package_name, mutating, note)

def _row_dict(r: SupportedVersion) -> Dict[str, object]:
    return {"distro_id": r.distro_id, "version_id": r.version_id, "label": r.label, "kind": r.kind, "evidence": r.evidence, "status": r.status, "notes": r.notes}

def supported_versions_table() -> List[Dict[str, object]]:
    return [_row_dict(r) for r in SUPPORTED_VERSIONS]

def support_for(distro_id: Optional[str], version_id: Optional[str]) -> Dict[str, object]:
    if distro_id is None or distro_id not in {r.distro_id for r in SUPPORTED_VERSIONS}:
        return {"distro_id": distro_id, "version_id": version_id, "status": STATUS_UNSUPPORTED_DISTRO, "supported": False, "reason": "distro not in the supported-versions table; fail closed"}
    for r in SUPPORTED_VERSIONS:
        if r.distro_id == distro_id and r.version_id == version_id:
            return {"distro_id": distro_id, "version_id": version_id, "status": r.status, "supported": r.status == STATUS_SUPPORTED, "evidence": r.evidence, "label": r.label, "reason": r.notes}
    return {"distro_id": distro_id, "version_id": version_id, "status": STATUS_UNLISTED, "supported": False, "reason": "version not listed in the table for this distro; unlisted is not supported"}

def is_supported(distro_id: Optional[str], version_id: Optional[str]) -> bool:
    return bool(support_for(distro_id, version_id)["supported"])

def identify(os_release_text: str) -> Dict[str, object]:
    if not os_release_text or not os_release_text.strip():
        raise MalformedOsReleaseError("empty os-release text cannot identify a distro")
    parsed = parse_os_release(os_release_text)
    distro_id = distro_id_for_os_release(os_release_text)
    version_id = parsed.get("VERSION_ID")
    if distro_id is None:
        return {"distro_id": None, "version_id": version_id, "adapter": None, "support": support_for(None, version_id)}
    # openSUSE rolling: VERSION_ID is a date stamp on Tumbleweed.
    support_version = version_id
    if distro_id == "opensuse" and parsed.get("ID", "").lower().find("tumbleweed") >= 0:
        support_version = "tumbleweed"
    return {"distro_id": distro_id, "version_id": version_id, "adapter": distro_id if distro_id in ADAPTERS else None, "support": support_for(distro_id, support_version)}

def adapters_as_dict() -> Dict[str, object]:
    return {"schema": ADAPTER_SCHEMA, "version": ADAPTER_VERSION, "adapters": {k: {"display": a.display, "package_manager": a.package_manager, "pm_binary": a.pm_binary, "package_names": a.package_names(), "critical_units": [u[0] for u in a.critical_units()], "protected_paths": [p[0] for p in a.protected_paths()], "log_sources": list(a.log_sources), "notes": list(a.notes)} for k, a in ADAPTERS.items()}, "table": {"schema": TABLE_SCHEMA, "version": TABLE_VERSION, "rows": supported_versions_table()}}

def build_evidence_record(distro_id: str, version_id: Optional[str]) -> Dict[str, object]:
    verdict = support_for(distro_id, version_id)
    payload = f"{ADAPTER_SCHEMA}|{distro_id}|{version_id}|{verdict['status']}"
    return {"schema": ADAPTER_SCHEMA, "version": ADAPTER_VERSION, "kind": "distro-support-verdict", "distro_id": distro_id, "version_id": version_id, "verdict": verdict, "evidence_status": "lab-verified (adapter code at fixture level on purpleraider, Ubuntu 26.10 host) for the rendering/table logic; distro support itself is at the row's own evidence level and is never upgraded by this record", "digest": hashlib.sha256(payload.encode()).hexdigest()}

def render_supported_versions_markdown() -> str:
    lines = ["| Distro | Version | Kind | Evidence | Status |", "|---|---|---|---|---|"]
    for r in SUPPORTED_VERSIONS:
        lines.append(f"| {r.distro_id} | {r.version_id} ({r.label}) | {r.kind} | {r.evidence} | {r.status} |")
    return "\n".join(lines) + "\n"
