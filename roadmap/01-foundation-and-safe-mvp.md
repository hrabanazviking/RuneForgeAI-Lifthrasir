# Book I: Foundations and Safe MVP

## P0: Architecture and governance

Define system boundaries, implementation languages, licensing, release policy, threat model, operator controls, and incident evidence schemas. Deliver reviewed design records and a reproducible developer environment. Gate: independent reviewers understand what the system is allowed to do.

## P1: Virtual laboratory

Build reproducible QEMU/KVM images, a resettable guest environment, synthetic failure fixtures, recorded test inputs, and CI. Test service errors, configuration errors, resource pressure, disconnections, and interruptions only inside dedicated lab environments. Gate: ten baseline faults reproduce and recover predictably.

## P2: Heimdall observation

Implement read-only systemd, journald, cgroup, PSI, disk, networking, and hardware sensors. Every observation includes a timestamp, source, provenance, severity, and sensitivity label. Gate: incident detection works entirely offline with bounded overhead.

## P3: Mímir evidence memory

Implement local structured events, exact-match text search, versioned official documentation, incident timelines, and optional vector retrieval. Expose source citations and record contradictory results. Gate: evidence remains traceable and private.

## P4: Permission and recovery foundation

Build a deterministic authorization policy separate from model inference, a minimal broker exposing a typed action catalog, a durable change journal, and an emergency stop. Validate resource limits, user approval, and restart recovery. Gate: denied operations do not change the host.

## P5: Eir healing MVP

Implement safe repair plans for a narrow class of noncritical user services, with preconditions, a precise proposed change, human approval, observation, and a tested undo mechanism. Gate: at least ten controlled failures, explicit abstentions, and recovery demonstrations pass.

## Phase deliverables

- Architecture decisions and published limitations.
- Disposable test VM, reset procedure, and test fixtures.
- Native observer and incident CLI.
- Searchable local evidence journal.
- Verified authorization and recovery services.
- First useful offline self-repair demonstration.

## Sources

- https://www.qemu.org/docs/master/system/
- https://docs.kernel.org/accounting/psi.html
- https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- https://docs.kernel.org/userspace-api/landlock.html
