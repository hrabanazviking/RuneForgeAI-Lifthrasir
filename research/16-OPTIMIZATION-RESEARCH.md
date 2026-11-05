# Continuous Linux Optimization: Scientific Experimentation
**Status:** research methodology, not product claims; 2026-11-05.

## Optimization targets
Responsiveness, CPU latency, throughput, memory pressure, GPU compute efficiency, disk I/O tail latency, boot speed, power draw, thermal stability and system reliability. Optimizations are workload-specific. 'Fastest Linux' is not a coherent universal target.

## One experiment, one hypothesis
Example: 'For this inference workload on this hardware, a specific cgroup CPU weight reduces interactive desktop p95 latency while keeping inference throughput within 2% of baseline.' Define measurements, controls and rejection thresholds **before** running the test. An agent must not post-hoc select the metric that makes its result look good.

## Benchmark methodology
- Record hardware model, cooling state, governor/power settings, kernel build, package versions and workload checksum.
- Compare candidate vs baseline on same host or matched test instance.
- Randomize order and repeat runs to mitigate warm-cache, ambient and thermal confounders.
- Measure tail latency, throughput, energy and system resource use simultaneously.
- Give raw data, sample count, dispersion and confidence interval.
- Separate measurement noise from statistically and practically meaningful change.
- Reject candidates that reduce reliability even when they improve an isolated microbenchmark.

## Experiment families
**Scheduler:** priorities, CPU affinity, core pinning and fair scheduling behavior; avoid starvation of foreground or critical services.  
**Memory:** cgroup memory.high, reclaim, zram, huge pages and memory compaction tuning; measure OOM and p99 responsiveness.  
**Storage:** read-ahead, filesystem mount options or application batch size; backup and test data integrity first.  
**Networking:** queue disciplines, TCP settings and buffering; test under realistic packet loss and low-latency interactive traffic.  
**Inference:** thread placement, quantization, batching, KV cache policy and CPU/GPU contention; include time-to-first-token and power.  
**Power:** suspend and sleep, device runtime PM, workload coalescing; never violate critical thermal controls.

## Candidate promotion
Optimization may be proposed, never silently enabled for everyone. A candidate needs a measured improvement exceeding a declared threshold, no regression on guardrail workload, rollback path and clear applicability. Keep per-machine tuning profiles and automatically disable a setting if health monitors detect deterioration.

## Avoid benchmark gaming
Use holdout tasks unknown to the patch proposer. Beware optimizers that sacrifice error handling, logging or security checks. Any patch to reduce overhead must be assessed for attack surface and long-term maintenance complexity.

## Long-term adaptive tuning
Model environment as non-stationary: battery vs AC, office vs VR gaming, idle vs sustained inference, hot vs cool. A profile can be selected from previously validated settings; new ones must be evaluated under explicit experimentation mode. Do not use reinforcement-learning exploration that risks user data or host health.

## Baseline deliverable
A reproducible benchmark runner that emits JSON with monotonic timings, system version, power proxy if available, and confidence report. Begin with user-space CPU and memory workload tests in a VM before proposing kernel changes.

## References
- PSI: https://docs.kernel.org/accounting/psi.html
- cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
- Linux tracing: https://docs.kernel.org/trace/index.html
