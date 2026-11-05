# Linux Observability, Root Cause Analysis and Telemetry
**Status:** research and implementation proposal; 2026-11-05.

## Principle
Lífþrasir must know what is wrong before changing anything. Treat telemetry as sampled, fallible and possibly adversarial: missing metrics are not healthy metrics, and an error message does not establish the true cause. The design combines low-cost baseline health monitoring with targeted deep tracing only when justified.

## Candidate data sources
| Layer | Primary signals | Evidence limits |
|---|---|---|
| Boot | previous boot ID, failed units, kernel journal, watchdog resets | Missing journal on sudden power loss |
| Service | systemd unit state, restart count, watchdog, dependency failure | A running process can still be unhealthy |
| CPU | per-process usage, PSI, scheduler latency, thermal and frequency state | High CPU is not necessarily a problem |
| RAM | MemAvailable, cgroup memory events, OOM, faults, PSI | Working-set estimates need context |
| Storage | smartctl where supported, I/O latency, mount errors, disk free, fsck history | SMART depends on controller/drive |
| Networking | link state, route, DNS, socket errors, connectivity probe | Avoid scanning or transmitting user traffic |
| Security | audit events, package integrity, suspicious process trees | Anomaly != malware |
| Devices | udev, PCI/USB IDs, driver bindings, power state, kernel warnings | Requires hardware-specific adapters |

## Minimal sensor loop
Poll cheap counters on a configurable interval; subscribe to relevant systemd/journald events where possible; trace using ftrace/tracefs or BPF only after a trigger and with bounded duration. Preserve kernel boot ID, monotonic timestamp and wall clock; do not naïvely order distributed incidents solely by wall time.

### PSI and cgroups
The Linux pressure stall interface (/proc/pressure/cpu, memory, io) measures stalled time; per-cgroup equivalents support diagnosis of which workload is experiencing pressure. A large cache is not automatically a leak. Correlate PSI with process memory, cgroup pressure, disk traffic and workload identity before tuning.

### Tracing escalation
- Tier 0: unit status, logs, resource counters.
- Tier 1: narrow process trace or sampled perf, only with consent where required.
- Tier 2: targeted ftrace/BPF/kernel instrumentation inside a lab reproduction.
- Tier 3: debug kernel or instrumented driver under VM/test host only.

Instrumentation can change performance. Use an uninstrumented comparison run for optimization claims.

## Causal diagnosis method
1. Establish normal baseline for *this host and workload*.
2. Identify onset and user-visible impact.
3. Construct event timeline across relevant subsystems.
4. Separate immediate trigger from contributing factors.
5. Generate multiple falsifiable hypotheses.
6. Predict disambiguating observations or minimal experiments.
7. Select repair only after controls and rollback evaluation.

A journal line saying 'service failed' only proves a recorded failure, not whether a faulty unit, missing dependency, full disk or device timeout is primary.

## Event retention and privacy
Use minimum necessary sampling; allow field-level scrubbing of hostnames, usernames, paths, MAC/IP, serial numbers, process arguments and tokens. Make opt-in recording of command lines separately explicit. Store raw evidence locally with quotas and expiry; publish only redacted aggregate data with affirmative consent.

## Example incident timeline
T0: disk usage 97%. T1: service database write fails. T2: unit restarts repeatedly. T3: network endpoint unavailable. Hypothesis A: insufficient writable disk is causal. Verify by reproducing write failure in disposable mirror, inspecting error codes and resolving capacity. Reject proposal to reinstall the package until the storage hypothesis is tested.

## Acceptance criteria
Alert specificity measured on known synthetic failures; detection latency within configured SLO; no meaningful overhead at idle; signal collection never blocks normal services; bounded file sizes; correct preservation of provenance; obvious off switch.

## References
- Linux tracing guide: https://docs.kernel.org/trace/index.html
- PSI: https://docs.kernel.org/accounting/psi.html
- cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
- systemd service states: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
