# Energy-Aware Linux Agents, Laptop Power and Suspend Safety
**Status:** hardware research plan; 2026-11-05.

## Why energy is a safety constraint
Agentic repair may occur on laptops, solar-powered computers, single-board devices, workstations and systems with fragile cooling. Unlimited parallel patch compilation or LLM inference could exhaust batteries, thermal-throttle useful workloads or make a device unreachable.

## Scheduler signals
Battery presence, charge %, AC state, power budget, thermal zone readings, CPU frequency, active GPU power limits, device suspend state, PSI and user-defined quiet-hours. Some metrics are not exposed on all hardware: mark UNKNOWN rather than guess.

## Work classes
- **Immediate safety:** rollback and critical incident notification may run under tight budget.
- **Urgent user-requested:** bounded diagnosis, local only if offline.
- **Opportunistic:** benchmarking, source indexing, fuzzing, patch search.
- **Deferred:** distributed jobs and long-form agent swarms.

Default policy: pause opportunistic work on battery below configurable threshold; yield to foreground apps; avoid large writes on low-storage/wear-sensitive media. Protect rollback service from the same pressure controls applied to experimental workers.

## Suspend/resume interactions
Long-running agents must save checkpoints, not prevent suspend indefinitely. Stop GPU jobs safely, persist transaction status, release volatile policy grants and rebuild telemetry baseline after wake. Never assume a monotonic clock includes time spent suspended uniformly across all systems.

## Thermal and battery experiments
Compare idle versus agent-loop draw; same screen brightness and background load; repeated hot/cool measurements; use wall power meter when available and clearly label software-only power estimates. Test thermal sensor failures and missing battery API; no unsafe thermal override.

## Portable inference
Choose models and contexts based on measured free memory and power state. Optimize energy-per-correct-diagnosis rather than tokens per second alone. CPU fallback can be slower yet safer than GPU jobs that destabilize desktop interaction.

## Research questions
How many concurrent model workers are tolerable on an APU laptop? Can long background research be checkpointed across suspend? Can content-addressed evidence avoid redundant SSD writes? How well can a low-power SBC run a deterministic Eir agent without a local LLM?

## References
- Kernel PM debugging: https://docs.kernel.org/power/basic-pm-debugging.html
- Linux PSI: https://docs.kernel.org/accounting/psi.html
- GPU driver controls: https://docs.kernel.org/gpu/drivers.html
