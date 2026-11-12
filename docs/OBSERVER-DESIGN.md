# Phase 2 Observer Design — checked against CONFINEMENT-REVIEW.md

**Slice H (activation Phase 2 entry). Status: design + first run.**
The observer is the first Lifthrasir component to run live on
purpleraider. It observes and proposes only; it never executes.

## What it is

- An UNPRIVILEGED systemd **user** unit (`lifthrasir-observer.service`,
  template banked at `units/lifthrasir-observer.service`, installed to
  `~/.config/systemd/user/`). No root, no broker — Phase 2 has no
  privileged piece by design (plan §2, invariants 1 and 2).
- Code: `lab/host_observer.py`, following the lab-collector precedent
  (LIF-0202/0203/0204 modules do the parsing; the observer only wires
  their live read-only helpers to the real host).
- Reads (all read-only): `systemctl list-units --failed`, `df -P`,
  `df -iP`, `/proc/mounts`, `/proc/net/dev`, `/proc/meminfo`,
  `/proc/stat`. There is no mutating verb anywhere in the module;
  a source-scan test pins that.
- Writes: ONLY inside `~/.local/state/lifthrasir/` — `events.jsonl`
  (append-only cycle log), `latest.json`, `proposals.json`,
  `DIGEST.md` (plain-language daily-readable digest; refreshed each
  cycle). The unit enforces this with `ProtectHome=read-only` +
  `ReadWritePaths` for exactly that directory.
- Proposals: each real observation (failed unit, disk alert at the
  collectors' documented 80/90% thresholds) becomes a
  `lifthrasir.plan.v0.1` plan record, shape-validated and digested
  with `approval.plan_digest`. Quiet cycles draft nothing and log
  themselves honestly as non-issues. Proposals are records only —
  nothing consumes them for execution in Phase 2.
- Kill-switch (invariant 8, no model involved): the cycle checks,
  before collecting, for the state-dir `STOP` flag file and for an
  engaged `KillSwitch` in `<state>/killswitch`. Either halts the
  cycle with a recorded `halted` status. `systemctl --user stop
  lifthrasir-observer` also stops it. Documented stop command:
  `touch ~/.local/state/lifthrasir/STOP`.
- Quotas (LIF-0603 intent, via cgroup v2 per the review): unit-level
  `CPUQuota=25%`, `MemoryMax=512M`, `TasksMax=64`, `Nice=10`,
  300 s cycle interval.

## Confinement check (docs/CONFINEMENT-REVIEW.md, LIF-0407)

The review's recommendations, applied in its own order:

1. Catalog v0.2 — NOT this slice; the observer drafts no catalog
   mutations and its proposals name only the observed unit itself.
   Recorded as Phase 3 preparation, not silently assumed.
2. **Broker unit first — ADOPTED (adapted):** systemd hardening is
   the first confinement layer, here for a user unit instead of a
   broker: `NoNewPrivileges=yes`, `PrivateTmp=yes`,
   `ProtectSystem=strict`, `ProtectHome=read-only` with a single
   `ReadWritePaths`, kernel/control-group protections,
   `RestrictAddressFamilies=AF_UNIX` (the observer needs no network),
   `LockPersonality=yes`. There is no dedicated broker user because
   there is no broker in Phase 2.
3. Landlock second — NOT claimed. The observer does not yet apply
   Landlock rules; recorded as the next confinement layer if Phase 3
   builds the broker. Availability on this host is host-observed
   (ABI 11) per the review, but availability is not use.
4. **cgroup v2 for caps — ADOPTED:** the unit quotas above run on
   this host's unified cgroup v2 (host-observed in the review).
5. LSM last — NOT claimed: no AppArmor profile is written for the
   observer in this slice; the review warns profiles are per-distro
   work, never assumed portable.
6. **Probe, don't presume — ADOPTED:** the design assumes NO user
   namespaces (Ubuntu mediates unprivileged userns through AppArmor;
   the review names this the one conditional row that bites on the
   first target family). No directive in the unit requires userns.

## Honest limits

- This is one unprivileged observer on one host, not broker-grade
  isolation; the review's verdict stands that nothing in Lifthrasir
  is broker-grade yet.
- `ProtectHome=read-only` still lets the observer READ most of the
  home directory; its collectors in fact read only /proc, df and
  systemd state. A tighter read set is Landlock's job (item 3).
- Phase 2 exit needs 7 days of operation with zero host mutations;
  the clock starts at this slice's first unit run, and the state
  file records the start. This slice does not claim the exit.
