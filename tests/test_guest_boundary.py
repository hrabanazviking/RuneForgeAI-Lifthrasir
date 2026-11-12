# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0103 tests: restricted guest network + host filesystem isolation.

Done criterion (roadmap/07): boundary tests pass. The boundary tests
ARE the proof: the shipped profiles pass the checker, and opened-up
mutants (LAN route added, host home allowed, wildcard allowlist) FAIL
it -- those mutants are the negative controls. Profile + checker level
only; no live guest network is claimed (no real VM boot exists yet).
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.guest_boundary import (BoundaryRefusal, check_files, load_profile,
                                network_destination_allowed, path_allowed,
                                validate_allowlist_entry,
                                validate_filesystem_profile,
                                validate_network_profile, validate_profiles)

ROOT = Path(__file__).resolve().parents[1]
NET_PATH = ROOT / "lab" / "profiles" / "restricted-guest-network.json"
FS_PATH = ROOT / "lab" / "profiles" / "host-filesystem-isolation.json"
LAB = Path("/srv/lifthrasir-lab-fixture")


@pytest.fixture()
def net():
    return load_profile(NET_PATH)


@pytest.fixture()
def fs():
    return load_profile(FS_PATH)


def test_shipped_profiles_parse_and_are_valid(net, fs):
    assert net["profile"] == "restricted-guest-network"
    assert fs["profile"] == "host-filesystem-isolation"
    assert validate_profiles(net, fs, LAB) == []
    check_files(NET_PATH, FS_PATH, LAB)  # must not raise


def test_network_default_is_deny_and_allowlist_empty(net):
    assert net["default_policy"] == "deny"
    assert net["allowlist"] == []
    assert net["routes"] == []
    assert network_destination_allowed(net, "example.com") is False
    assert network_destination_allowed(net, "192.168.1.1") is False


def test_filesystem_confined_to_lab_dir(fs):
    assert fs["default_policy"] == "deny"
    assert fs["allowed_roots"] == ["$LAB_ROOT"]
    assert path_allowed(fs, LAB / "guests" / "g1.qcow2", LAB) is True
    assert path_allowed(fs, Path("/etc/passwd"), LAB) is False
    assert path_allowed(fs, Path("/home/volmarr/.ssh/id_ed25519"), LAB) is False
    assert path_allowed(fs, Path("/"), LAB) is False


def test_single_named_allowlist_entry_is_explicit():
    assert validate_allowlist_entry({"host": "lab-mirror.internal"}) == []
    assert validate_allowlist_entry({"host": "10.99.0.5"}) == []
    good = {"default_policy": "deny", "network_mode": "isolated-host-only",
            "slice": "LIF-0103", "version": 1, "nat": False, "bridged": False,
            "host_lan_access": False, "wan_access": False, "routes": [],
            "allowlist": [{"host": "lab-mirror.internal"}]}
    assert validate_network_profile(good) == []
    assert network_destination_allowed(good, "lab-mirror.internal") is True
    assert network_destination_allowed(good, "other.internal") is False


# -- negative controls: opened-up mutants must FAIL --------------------

def test_mutant_lan_route_fails(net, fs):
    m = copy.deepcopy(net)
    m["routes"] = [{"destination": "192.168.1.0/24", "via": "host-lan"}]
    m["host_lan_access"] = True
    assert validate_network_profile(m) != []


def test_mutant_nat_enabled_fails(net):
    m = copy.deepcopy(net)
    m["nat"] = True
    m["network_mode"] = "nat"
    assert validate_network_profile(m) != []


def test_mutant_default_allow_fails(net):
    m = copy.deepcopy(net)
    m["default_policy"] = "allow"
    assert validate_network_profile(m) != []


def test_mutant_wildcard_allowlist_fails(net):
    for bad in ("*", "*.example.com", "any"):
        m = copy.deepcopy(net)
        m["allowlist"] = [{"host": bad}]
        assert validate_network_profile(m) != [], bad


def test_mutant_cidr_allowlist_fails(net):
    m = copy.deepcopy(net)
    m["allowlist"] = [{"host": "192.168.0.0/16"}]
    assert validate_network_profile(m) != []


def test_mutant_host_home_allowed_fails(fs):
    m = copy.deepcopy(fs)
    m["allowed_roots"] = ["$LAB_ROOT", "$HOME"]
    assert validate_filesystem_profile(m, LAB) != []


def test_mutant_root_allowed_fails(fs):
    m = copy.deepcopy(fs)
    m["allowed_roots"] = ["/"]
    assert validate_filesystem_profile(m, LAB) != []


def test_mutant_etc_allowed_fails(fs):
    m = copy.deepcopy(fs)
    m["allowed_roots"] = ["$LAB_ROOT", "/etc"]
    assert validate_filesystem_profile(m, LAB) != []


def test_mutant_denied_list_weakened_fails(fs):
    m = copy.deepcopy(fs)
    m["denied_paths"] = ["/"]
    assert validate_filesystem_profile(m, LAB) != []


def test_check_files_raises_on_mutant_profile(tmp_path, net, fs):
    import json
    bad = copy.deepcopy(net)
    bad["allowlist"] = [{"host": "*"}]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(BoundaryRefusal):
        check_files(p, FS_PATH, LAB)
