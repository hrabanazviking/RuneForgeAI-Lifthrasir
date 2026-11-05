# Incident Response Playbooks: Realistic Decision Trees
**Status:** proposed response runbooks; 2026-11-05.

## Global decision policy
**Safety and preservation first:** collect bounded observations, check whether user action is intentional, assess impact, obtain approval, ensure recovery, execute a minimal scoped change, verify and report. Incident urgency does not magically grant missing permissions.

## Playbook 1: failed noncritical service
Trigger: explicit failed unit state and observed user impact. Investigate dependency graph, recent package/config change, exit status and logs. If a safe restart is appropriate, offer one attempt with start-limit awareness. Repeated failures trigger Eir diagnosis and no further restart storm. Verify real endpoint behavior.

## Playbook 2: disk full / apparent application corruption
Trigger: ENOSPC errors and near-capacity device. Confirm mount, quota and inode availability; correlate to failed writes. Offer space report, app-specific safe cleanup suggestions, or user-approved targeted deletion of disposable cache files. Do not delete arbitrary files or run filesystem recovery on a mounted production FS. Recommend independent backup when signs of corruption exist.

## Playbook 3: unexplained memory pressure
Trigger: sustained memory PSI and OOM events. Identify cgroups/processes, workload context and limits; check whether an experimental agent triggered contention. First cancel Lifthrasir's own nonessential jobs. Propose bounded resource changes only after baseline measurement. Avoid killing user workloads solely because they are large.

## Playbook 4: networking broken after change
Trigger: link works but DNS/route fails after specific config modification. Preserve old config, show exact diff, require remote connectivity fallback before writes. Timed rollback mandatory when working over SSH. If remote access is sole administration route and no OOB recovery exists, block autonomous network edits.

## Playbook 5: suspected malicious process
Trigger: multiple independent suspicious indicators. Thor gathers process lineage and hashes, checks installed package provenance, labels uncertainty, warns user. Containment must be scoped, reversible and approved per policy. Do not delete user data or publish exploitable issue automatically. Eir may restore known-good configs once incident closed.

## Playbook 6: driver reset during local inference
Trigger: GPU reset/timeouts correlated with workload. Pause AI acceleration; preserve system usability; switch diagnostic inference to CPU. Collect exact kernel/driver/runtime/hardware versions and compare vendor support matrix. Research candidate fix in test VM; avoid unapproved firmware or driver change.

## Playbook 7: kernel panic after update
Trigger: known boot failure with last-good image available. Do not depend on agent being alive during panic. Use bootloader/snapshot fallback via independent recovery process. Once booted, gather prior journal and source/version diff; hold updates pending manual assessment.

## Playbook 8: suspected upstream bug
Trigger: reproducible failure on identified kernel version. Locate subsystem owner and known fixes, isolate reproducer, run relevant tests, prepare candidate patch dossier. Human review and DCO sign-off only. Security bugs require private reporting route.

## Documentation artifacts
Every playbook defines severity, user-impact criteria, required evidence, safe/no-action boundary, rollback trigger, escalation contact class, audit output and follow-up window. 'Cannot safely determine' is a legitimate outcome.

## References
- systemd service: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- Security reporting: https://docs.kernel.org/process/security-bugs.html
- Kernel upstream: https://docs.kernel.org/process/submitting-patches.html
