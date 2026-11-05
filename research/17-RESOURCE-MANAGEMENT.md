# Scheduler, Memory, Cache, I/O and Storage Research
**Status:** technical investigation plan; 2026-11-05.

## The resource problem
Agentic automation competes with the user's actual work. A system that diagnoses problems by consuming all memory, CPU, storage bandwidth and battery is not self-healing. The research program must treat resource caps and interactive responsiveness as correctness constraints.

## Memory model
Distinguish DRAM, swap, zram, page cache, GPU VRAM, unified memory, mapped file pages, pinned buffers, model weights and KV caches. Shared physical memory does not guarantee fungible addresses, coherence or zero-copy access between all devices. Cross-device pooling requires explicit transport, permissions and performance measurements; never promise transparent 'one big memory' across machines.

## Memory interventions
- Observe MemAvailable, cgroup memory.current/high/events, PSI and swap trends.
- Detect steady growth and distinguish an application leak from growing useful cache.
- Shed noncritical Replicater jobs before the host OOM killer intervenes.
- Apply memory.high, pids.max and task concurrency bounds to experimental agents.
- Benchmark caching strategies with repeated workloads, avoiding arbitrary cache purges.
- Prefer explicit backpressure over high-risk global VM knob changes.

## Scheduling
Compare CPU affinity, cpuset groups, niceness, systemd slices, CPUWeight and IOWeight. Protect interactive desktop and security/rollback agents. A local inferencer should have a cancellation point and yield under sustained contention. Consider heterogeneous cores and NUMA as discovered capabilities, not assumptions.

## Storage
Track health separately from capacity. Distinguish drive wear metrics from filesystem errors, namespace/device identity and mount topology. Snapshot support depends on filesystem and logical volume setup; a file-level rollback differs from a bootable-system rollback.

## Device-to-device memory
A networked memory-pooling concept belongs in experimental research. Latency/throughput, RDMA or transport permissions, memory consistency and failure recovery may make it inferior to local storage for many workloads. Compare actual bandwidth and p99 access against local DRAM, swap and PCIe before any optimization claim.

## Controlled experiments
A. Determine when 2, 4 or 8 agents trigger measurable PSI and foreground latency.  
B. Compare zram vs swapfile under constrained Linux VM (data-integrity preserved).  
C. Measure KV cache eviction strategies under realistic sequential and parallel inference.  
D. Profile batch vs interactive response for mixed CPU/GPU workloads.  
E. Test cgroup limit enforcement when an agent process forks unexpectedly.

## Safety constraints
Never alter global swappiness, block I/O scheduler or CPU governor without knowing OS power policy, constraints and rollback. Do not write raw disk devices, resize partitions, disable OOM protections or patch allocator internals on a production host as an automatic remedy.

## Relationship with MímirAlloc
The sibling MímirAlloc project can supply optional memory-management experiments and data, but Lífþrasir must remain independent and should only promote an allocator if standard interfaces, ABI boundaries, license and benchmarks pass review.

## References
- Linux cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
- PSI: https://docs.kernel.org/accounting/psi.html
- Kernel memory docs: https://docs.kernel.org/admin-guide/mm/index.html
