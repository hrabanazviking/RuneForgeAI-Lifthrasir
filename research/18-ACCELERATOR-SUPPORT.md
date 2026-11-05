# GPU, NPU, CPU and Heterogeneous Accelerator Support
**Status:** architecture and vendor-compatibility research; 2026-11-05.

## Main finding
Linux graphics driver availability and AI compute backend compatibility are different questions. A GPU that drives a Wayland desktop may not be supported by a particular ROCm or CUDA version; an NPU may have model/operator restrictions. Lífþrasir must probe capabilities rather than declare support based on vendor name.

## Hardware inventory
Record PCI/USB identifiers, CPU microarchitecture, NUMA nodes, GPU driver and firmware versions, usable VRAM/unified-memory budget, compute API availability, OS/kernel revision, supported precision and measured inference throughput. Never infer memory capacity solely from nominal GPU name.

## Backends to investigate
**CPU:** portable inference fallback; optimized BLAS kernels; threading/affinity under cgroup constraints.  
**AMD:** amdgpu kernel stack, ROCm/HIP where the exact APU/GPU+OS combination appears in AMD's support matrix; other experimental backends must be clearly labeled unverified.  
**NVIDIA:** proprietary or open kernel modules and supported user-space CUDA driver/toolkit combinations; test permissions and host stack compatibility.  
**Intel:** oneAPI/Level Zero/OpenCL where supported; integrated GPU and NPU frameworks require separate validation.  
**ARM/SBC:** CPU-first execution, GPU-specific backends and Hailo/other NPU SDKs only if exact firmware/runtime available.  
**Other:** Vulkan compute can be investigated where backend supports relevant operators; portability must be tested, not assumed.

## Resource sharing
GPU used for the graphical desktop should retain latency and memory headroom. AI experiments may starve the display or trigger reset; measure cursor/input latency, VRAM pressure, driver faults, kernel warnings and thermal/power constraints. Have a CPU-only diagnostic fallback when GPU backend crashes.

## Experimental device classes
A high-memory unified-memory APU, a conventional dGPU laptop, a Raspberry Pi class SBC and a machine without any accelerator should all be represented in evaluation. The goal is graceful scaling, not forcing identical performance or features.

## Failure categories
- Driver module and user-space runtime mismatch.
- Firmware absent or incompatible.
- GPU reset or timeout during inference.
- OOM while allocating model weights or KV caches.
- Unexpected precision or operator limitation.
- Scheduler contention between interactive display and AI.
- Suspend/resume failure with compute workloads active.
- Thermal or power limits causing misleading benchmark results.

## Test design
Probe compute runtime; run tiny tensor sanity check; allocate within a conservative memory budget; benchmark TTFT/token throughput/energy; inject runtime termination; verify host remains usable and can fall back to CPU. Record all data with explicit version and hardware identifiers; do not hard-code a changing ROCm compatibility matrix into the project.

## Security
Model files, shaders and GPU compute kernels are untrusted code/data inputs. Run in constrained process with least filesystem access; keep firmware modifications entirely outside autonomous repair. Monitor GPU driver error counters without granting direct device-control privileges to planning agents.

## References
- Linux DRM/GPU: https://docs.kernel.org/gpu/
- AMDGPU docs: https://docs.kernel.org/gpu/amdgpu/index.html
- AMD ROCm compatibility: https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility.html
- cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
