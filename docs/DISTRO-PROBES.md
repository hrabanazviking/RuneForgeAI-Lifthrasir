# Distro Capability Probes and Adapter Contracts (LIF-1101)

Machine-readable half: `src/lifthrasir/distroprobes.py`
(schema `lifthrasir.distro-probe.v0.1`, contract schema
`lifthrasir.adapter-contract.v0.1`). Fixtures:
`tests/fixtures/lif1101/hosts.json`. Tests:
`tests/test_distro_probes.py` pin this document to the module.

## Honest status

This slice defines probes and contracts at fixture/record level.
It does not change host configuration, executes no command on any
host, and ships no adapter. **No distro or architecture is
claimed supported by this slice** — no distro or architecture is
"supported" until LIF-1102 ships its adapter and the published
supported-versions table, earned by repeatable tests. The word
supported appears in this project only as that future authority.

The only modes a probe report can carry are:

- `probe-only` — family known, live-mutable deployment: probes
  parsed and the adapter contract is defined, but no adapter
  exists yet, so no live verb is authorised by this slice.
- `observation-only` — unknown family, unknown deployment model,
  or a transactional / declarative / image-based deployment whose
  native interface owns mutation (research/13). Unknown or
  untested is NOT verified.

## Method: probe instead of assuming

Book IV (roadmap/04) requires an explicit capabilities adapter
interface per distro and probing rather than assuming features
exist. Research/13 supplies the interface (init, package,
deployment, boot, security, network, filesystem, inference), the
compatibility-matrix fields, and the cross-distro incident
contract: an incident names an abstract failure; translation to a
distro action is adapter-owned; abstention is a valid result.

A probe evaluates RECORDED host facts only: an os-release text
plus recorded command, path, LSM and filesystem inventories and
deployment markers. Outcomes are `present`, `absent`, `unknown`
and `error`:

- `absent` is reported only when the recording declares its
  inventory complete for that dimension; an incomplete recording
  yields `unknown`, never a guessed absence.
- Conflicting recorded package managers yield `error`, never a
  silent pick.
- An empty LSM list never proves MAC absence: the MAC probe stays
  `unknown` rather than assuming a family default.
- Offline availability stays `unknown` unless the recording
  carries positive offline evidence; it is never assumed.

Documentary per-family hints (package manager and default LSM
from the LIF-0407 confinement review) are carried only as
expectations: `compare_hints` reports agree / disagree /
unverifiable, and the probe stands in every case.

## The ten probed capabilities

| Capability | Title |
|---|---|
| service_manager | service / init manager |
| package_manager | package manager and trust root |
| deployment_model | deployment model (live-mutable, transactional, declarative, image-based) |
| boot_mechanism | boot mechanism and firmware interface |
| mac_policy | mandatory access control (LSM) policy |
| network_stack | network management stack |
| snapshot_strategy | snapshot / rollback strategy |
| hardware_interfaces | machine architecture and device interfaces |
| inference_backends | local inference backends and accelerators |
| offline_availability | offline operation evidence |

Every capability must be probed for a descriptor to be valid: an
unprobed capability is a contract violation, while a probed
outcome of `unknown` is honest.

## Families and variants

Contract families (display names as the module records them):

- Ubuntu / Kubuntu (first target family)
- Debian
- Fedora
- openSUSE (Leap / Tumbleweed)
- Arch Linux

Family identification reuses the LIF-0407 os-release mapping (ID
first, then ID_LIKE, with named derivative aliases) and adds the
Book IV Arch expansion family. An unmapped ID identifies no
family and fails closed into observation-only mode.

Known variants — opensuse-microos, nixos, ostree-bootc — are
detected by os-release ID or recorded marker and force
observation-only mode: transactional, declarative and image-based
systems are handled through their native interfaces or not at
all.

## The adapter contract

Every family contract requires the same six declared methods:
identify, probe_all, capability, translate_plan, dry_run,
check_rollback. `check_contract_compliance` reports any method an
adapter descriptor fails to declare; `validate_descriptor`
refuses unknown keys, unknown families, unprobed capabilities and
bad outcomes, and any claim of support raises `SupportClaimError`
by name — support is LIF-1102's table, not a field a descriptor
may assert for itself.

Abstention rules (the governing capability must probe `present`,
and the host must not be observation-only, or the operation
abstains with the probe record as its reason):

| Operation | Governing capability |
|---|---|
| service_actions | service_manager |
| package_actions | package_manager |
| boot_changes | boot_mechanism |
| mac_changes | mac_policy |
| network_changes | network_stack |
| rollback_claims | snapshot_strategy |
| inference_actions | inference_backends |

Per-family contract notes the adapters must honour: Debian
non-systemd installs exist, so the service-manager probe decides,
never the family name; openSUSE's LSM is genuinely conditional
(AppArmor or SELinux by install) and may not be hard-coded;
Fedora's SELinux default still requires the adapter's own domain;
Arch's AUR is outside the official trust root and no method may
treat it as trusted; Ubuntu/Kubuntu is the first target family
and its adapter is still LIF-1102 work.

## Fixture hosts

Nine recorded hosts pin the behaviour: kubuntu-lab (mirrors the
purpleraider facts recorded by LIF-0407), debian-stable,
debian-sysv (an openrc service manager on a Debian family host:
the probe, not the family name, decides), fedora-workstation,
opensuse-leap, arch-rolling (empty LSM recording: MAC stays
unknown), microos-host (transactional, observation-only),
void-unknown (no contract family, observation-only) and
partial-recording (incomplete inventories: outcomes are unknown,
never absent). Only the kubuntu-lab fixture mirrors a real
machine's recorded facts; the rest are synthetic recordings
modelled on documented family shapes and are NOT verified
against real machines of those families.

## Limitations and undo

Fixture/record level only: no live collector, no adapter, no
supported-versions table (all LIF-1102 or later), no claim that
any fixture host exists, and no performance claim from accelerator
presence. Evidence status of this slice's proof is `reproducer`
(the LIF-0004 ladder): the tests prove the probe and contract
logic on recordings, on purpleraider only. Undo: revert the slice
commit — module, fixtures, tests and this document only; no
system state was changed. No Docker was used; no README was
touched; no DCO was signed.
