# Reproduction, Regression Testing and Proof of Repair
**Status:** test methodology; 2026-11-05.

## No repair without a falsifiable test
A bug report establishes a candidate problem; it does not validate its cause. Before altering code, reproduce a symptom with a controlled input on an identified baseline, where practical. The proposed fix must pass the reproducer *and* guard against regressions.

## Testing layers
1. **Schema/unit:** pure policy, plan parsing, decision logic and serialization.
2. **Component integration:** SQLite, IPC, fake broker, mock systemd, truncated logs.
3. **System VM:** real service manager, package database and filesystem under disposable image.
4. **Kernel in-VM:** build, boot, KUnit, kselftest, targeted sanity tests, sanitizers.
5. **Hardware lab:** firmware/driver faults, suspend/resume, thermal and power, never personal production machines.
6. **Soak:** multi-day conditions where race, leak or stability evidence requires it, with bounded telemetry.

## Kernel-native frameworks
**KUnit** is appropriate for in-kernel unit tests of relatively isolated logic; **kselftest** exercises exposed behavior, often from user space. Choose based on component. The Linux testing guide explicitly distinguishes these. Use sanitizers such as KASAN/KCSAN for relevant classes of memory or concurrency failures; enabled instrumented kernels can alter timing and overhead.

## Reproducer structure
Document target hardware/VM, distro/kernel exact commit, config digest, compiler revision, package versions, input, expected baseline failure, verification command, observed results and known noise. Preserve minimal test artifacts, not whole personal home directories. Negative control should show the bug is absent in a known-good state or present with the trigger restored.

## Candidate acceptance matrix
| Gate | Demonstration |
|---|---|
| Baseline failure | Deterministic or quantified occurrence rate |
| Patched success | Same scenario now passes |
| Regression | Relevant existing suite passes |
| Differential | Candidate beats baseline on declared metric |
| Portability | Relevant architectures/configurations tested |
| Security | Static analysis, fuzzing as relevant |
| Rollback | Undo restores known-good state |
| Explanation | Human reviewer can describe why fix works |

If a bug is flaky, use repeated randomized trials, report distribution and confidence interval rather than claim certainty from a single clean run.

## Lab orchestration
Each experiment creates an ephemeral worktree and VM image; preserve base commit and toolchain manifest. Isolate network and set CPU/RAM/time limits. Test machine automatically expires. Failure and crash logs are archived as data; models cannot treat their contents as executable instructions.

## Test quality improvement
Agents can propose tests for untested failure modes, but review them for tautology ('assert patched behavior is patched') and overfitting. Introduce mutation testing to ensure tests fail when a known bug is reintroduced. A passing synthetic mock does not replace real integrated testing.

## Benchmarks and regressions
Establish noise floors; warm-up procedures; thermal controls; same power limits and storage state; repeated runs; disabled confounding background updates; appropriate baseline commit. Publish methodology and raw measurements. Reject improvements smaller than measurement uncertainty.

## References
- Kernel testing overview: https://docs.kernel.org/dev-tools/testing-overview.html
- Kselftest docs: https://docs.kernel.org/dev-tools/kselftest.html
- syzkaller: https://github.com/google/syzkaller
- Patch submission checklist: https://docs.kernel.org/process/submit-checklist.html
