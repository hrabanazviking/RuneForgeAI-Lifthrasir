# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0103: restricted guest network + host filesystem isolation checker.

Home: master roadmap section 3 places lab tooling under ``lab/``; the
LIF-0101 image recipe and the LIF-0102 workflow both keep their
machine-readable contracts as data beside the code that consumes them.
This slice follows the same pattern:

* ``lab/profiles/restricted-guest-network.json`` -- the guest gets NO
  route to the host LAN/WAN by default: an isolated host-only segment,
  default deny, and an explicit enumerated allowlist (empty by
  default). Any destination not on the allowlist is denied.
* ``lab/profiles/host-filesystem-isolation.json`` -- the guest's disk
  access is confined to the lab directory. Allowed roots = the lab
  directory only (the ``$LAB_ROOT`` token); host home, ``/``, ``/etc``
  and SSH keys are named-denied. This formalizes as consumable data
  the boundary ``lab/vm_workflow.py`` (LIF-0102) already enforces in
  code with its in-lab path check.

This module is the validator a workflow or CI step consumes. A profile
without a failing-when-open test is a claim, not a boundary, so
``tests/test_guest_boundary.py`` proves the shipped profiles pass and
opened-up mutants (LAN route, host home allowed, wildcard allowlist)
fail.

Scope honesty (master roadmap section 0, invariants 1, 2, 5): this is
profile + checker level proof only. No live guest network is tested
and no host network/firewall state is read or mutated -- invariant 2
names critical firewall/network state as never autonomously mutated,
and no real VM boot exists yet in this campaign.
"""
from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path

ISOLATED_MODES = {"isolated", "host-only", "isolated-host-only", "none"}
LAB_TOKEN = "$LAB_ROOT"
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")


class BoundaryRefusal(Exception):
    """Raised when a profile fails the boundary check."""


def load_profile(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BoundaryRefusal(f"{path}: profile is not a JSON object")
    return data


def validate_allowlist_entry(entry: object) -> list[str]:
    """One allowlist entry must name exactly one explicit destination."""
    if not isinstance(entry, dict) or not isinstance(entry.get("host"), str):
        return ["allowlist entry must be an object with a 'host' string"]
    host = entry["host"]
    problems: list[str] = []
    if not host or host.lower() in {"any", "all", "*"}:
        problems.append(f"allowlist host {host!r} is not an explicit destination")
    if any(ch in host for ch in "*?/"):
        problems.append(
            f"allowlist host {host!r} contains a wildcard, range or network prefix")
    if not problems:
        try:
            ipaddress.ip_address(host)
            return []
        except ValueError:
            pass
        try:
            if ipaddress.ip_network(host, strict=False):
                problems.append(f"allowlist host {host!r} is a network, not one host")
        except ValueError:
            if not _HOSTNAME_RE.match(host):
                problems.append(f"allowlist host {host!r} is not a valid single hostname")
    return problems


def validate_network_profile(data: dict) -> list[str]:
    v: list[str] = []
    if data.get("slice") != "LIF-0103":
        v.append("network profile slice must be LIF-0103")
    if not isinstance(data.get("version"), int):
        v.append("network profile version must be an integer")
    if data.get("default_policy") != "deny":
        v.append("network default_policy must be 'deny'")
    if data.get("network_mode") not in ISOLATED_MODES:
        v.append(f"network_mode {data.get('network_mode')!r} is not an isolated mode")
    for flag in ("nat", "bridged", "host_lan_access", "wan_access"):
        if data.get(flag) is not False:
            v.append(f"network flag {flag!r} must be false")
    if data.get("routes") != []:
        v.append("routes must be empty: the restricted guest has no routes")
    allowlist = data.get("allowlist")
    if not isinstance(allowlist, list):
        v.append("allowlist must be a list")
    else:
        for entry in allowlist:
            v.extend(validate_allowlist_entry(entry))
    return v


def _resolve_root(entry: str, lab_root: Path) -> Path:
    expanded = entry.replace("${LAB_ROOT}", str(lab_root)).replace(
        LAB_TOKEN, str(lab_root))
    p = Path(expanded)
    if not p.is_absolute():
        p = lab_root / p
    return p.resolve()


def validate_filesystem_profile(data: dict, lab_root: Path) -> list[str]:
    lab = Path(lab_root).resolve()
    v: list[str] = []
    if data.get("slice") != "LIF-0103":
        v.append("filesystem profile slice must be LIF-0103")
    if not isinstance(data.get("version"), int):
        v.append("filesystem profile version must be an integer")
    if data.get("default_policy") != "deny":
        v.append("filesystem default_policy must be 'deny'")
    allowed = data.get("allowed_roots")
    if not isinstance(allowed, list) or not allowed:
        v.append("allowed_roots must be a non-empty list")
        allowed = []
    for entry in allowed:
        if not isinstance(entry, str) or not entry:
            v.append(f"allowed root {entry!r} must be a non-empty string")
            continue
        resolved = _resolve_root(entry, lab)
        if resolved != lab and lab not in resolved.parents:
            v.append(f"allowed root {entry!r} resolves outside the lab directory")
    denied = data.get("denied_paths")
    if not isinstance(denied, list):
        v.append("denied_paths must be a list")
        denied = []
    if "/" not in denied:
        v.append("denied_paths must name '/'")
    if "/etc" not in denied:
        v.append("denied_paths must name '/etc'")
    if not any(e in ("$HOME", "/home") or e.startswith("/home") for e in denied):
        v.append("denied_paths must name the host home directory")
    if not any(".ssh" in str(e) for e in denied):
        v.append("denied_paths must name SSH keys (a .ssh path)")
    for entry in allowed:
        if isinstance(entry, str) and entry in denied:
            v.append(f"allowed root {entry!r} is also denied")
    return v


def validate_profiles(network: dict, filesystem: dict, lab_root: Path) -> list[str]:
    return (validate_network_profile(network)
            + validate_filesystem_profile(filesystem, lab_root))


def check_files(network_path: Path, filesystem_path: Path, lab_root: Path) -> None:
    problems = validate_profiles(load_profile(network_path),
                                  load_profile(filesystem_path), lab_root)
    if problems:
        raise BoundaryRefusal("boundary check failed: " + "; ".join(problems))


def network_destination_allowed(network: dict, host: str) -> bool:
    """Default deny: only an exact allowlist match is allowed."""
    if validate_network_profile(network):
        return False
    return any(isinstance(e, dict) and e.get("host") == host
               for e in network.get("allowlist", []))


def path_allowed(filesystem: dict, path: Path, lab_root: Path) -> bool:
    """True only for paths resolving inside an allowed root."""
    lab = Path(lab_root).resolve()
    if validate_filesystem_profile(filesystem, lab):
        return False
    resolved = Path(path).resolve()
    return any(resolved == _resolve_root(e, lab)
               or _resolve_root(e, lab) in resolved.parents
               for e in filesystem.get("allowed_roots", []))
