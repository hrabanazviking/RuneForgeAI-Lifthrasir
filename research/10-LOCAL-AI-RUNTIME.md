# Local AI Models: Selection, Inference, Offline Operation and Hardware Fit
**Status:** comparative research plan; 2026-11-05. **No benchmark numbers are claimed without measurement.**

## Architectural requirement
The Linux supervisor must be useful without an LLM. Models add hypothesis generation, source synthesis, patch drafting and explanation. They must never become the privileged policy engine. A local inference provider should be replaceable through a documented protocol; Project A.E.S.I.R. is a potential backend, not a required dependency.

## Functional workload decomposition
| Task | Model capability | Safer deterministic partner |
|---|---|---|
| Log clustering | Short structured extraction | Regex + severity parser |
| Incident explanation | Grounded synthesis | Exact timeline and citations |
| Root-cause hypothesis | Reasoning with alternatives | Reproducer/test selection |
| Patch drafting | Code-aware generation | Compiler, static analyzers, tests |
| Tool selection | Schema-constrained planning | Action policy broker |
| Long-running research | Retrieval + summarization | Search, source hashes, source expiry |

## Model interface
Request fields: task ID, model identifier and exact revision, prompt template version, trusted system constraints, untrusted context references, max input/output tokens, temperature, deadline, budget, grammar/schema target and cancellation token. Response fields: structured candidate, citations, uncertainty, runtime metrics, safety flags and reproducibility manifest.

## Model size and quantization
Benchmark models across sizes and quantizations on actual targets. Do not assume a larger model is always better; short deterministic workloads may favor smaller local models. Compare accuracy at a fixed latency/energy budget; some quantization schemes trade throughput for memory and may vary by backend/hardware. Treat vendor-reported TOPS and theoretical memory bandwidth as upper bounds, not application throughput.

## Hardware tiers
- **Tier S:** single-board computer, CPU-first, modest RAM, no assumed GPU/NPU, restricted concurrency and short contexts.
- **Tier M:** laptop/desktop with consumer GPU; mixed CPU/GPU memory, one interactive repair agent plus asynchronous lab.
- **Tier L:** high-memory unified-memory APU or workstation; multiple specialized models or agents, larger retrieved context.
- **Tier R:** optional remote worker; permission-limited and never required for critical recovery.

At installation run a hardware inventory, probe supported backend, report real allocated model memory, leave headroom for desktop/OS, and reduce jobs when PSI rises.

## Context and retrieval
Prefer compact, cited facts to raw multi-megabyte journal dumps. Chunk by incident and source revision; preserve timestamps and error codes. Use exact-match search for critical symbols (function names, errno, commit hashes). KV cache and prefix reuse are optimizations only if prompt boundaries and source revisions remain valid; cache poisoning tests are required.

## Evaluation harness
Construct gold-standard incident suites that include false leads and prompt injection. Report end-to-end diagnosis precision, actionable test quality, broken-fix rate, latency, GPU memory peak, RAM peak, battery drain and offline completion. Run identical tasks on each backend to avoid meaningless token-per-second comparisons.

## Security requirements
No implicit cloud fallback. No telemetry to model vendors without consent. No automatic download and execution of unsigned inference plugins. Verify model artifacts where possible; maintain source/license manifest and model-hash registry. Sandbox model runtime and limit filesystem access.

## Research tasks
Build inference adapter for one local OpenAI-compatible server and one native project adapter; add schema-enforced JSON responses; test model crash handling and fall back to pure heuristics; benchmark memory budget alongside real desktop use.

## References
- Linux resource pressure: https://docs.kernel.org/accounting/psi.html
- Cgroup v2 control: https://docs.kernel.org/admin-guide/cgroup-v2.html
- Model supply-chain discussion: https://slsa.dev/
