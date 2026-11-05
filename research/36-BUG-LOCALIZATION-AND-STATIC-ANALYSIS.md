# Bug Localization, Static Analysis, Bisection and Semantic Patches
**Status:** technical research roadmap; 2026-11-05.

## Tool-first strategy
Before generating novel code, search upstream for known fixes; inspect relevant symbol history; reproduce symptom; narrow culprit with deterministic tools. LLMs synthesize hypotheses and explain diffs, but static analyzers and tests supply evidence.

## Candidate tools
**Git bisect:** identify first bad source commit with a repeatable test.  
**Coccinelle:** semantic source transformations using semantic patches for certain bug patterns.  
**Sparse:** kernel-aware static checking and type/annotation validation.  
**Smatch:** static analysis for C paths, where available.  
**clang tooling:** compile diagnostics, analyzers and sanitizer-based experiments.  
**ftrace/BPF/perf:** runtime symptom and execution evidence.  
**KUnit/kselftest:** regression validation.  
**KASAN/KCSAN/KFENCE:** memory and race bug finding with differing overhead.

## Automated culprit ranking
Correlate failing stack trace, modules, recent changes, function call graph, source ownership, target architecture and kernel configuration. Present ranked *candidate* paths with links, never a fabricated definitive cause. Keep low-ranked candidates available for contradictory evidence.

## Minimal reproducers
Reproducing source bug must be safer than blindly pushing candidate patch. Prefer unit test or emulated device condition. Reproducer minimization via delta debugging can remove extraneous operations; review that it still produces same failure class.

## Semantic patches
Generated Coccinelle rules should be human-reviewed and initially run in read-only/check mode. A semantic transformation may change legitimate patterns; tests and manual diffs remain necessary. Avoid broad mechanical rewriting of unrelated files in one upstream patch.

## Controlled bisection
Agent may automate git bisect inside VM/build farm, but test harness must distinguish PASS/FAIL/SKIP and flaky result. Treat crash logs as data. Document first-bad commit confidence and known nondeterminism.

## Reproducibility dossier
Source commit range, bisection log, compiler flags, config, minimal triggering input, sanitizer output, proposed code change, before/after test results, relevant maintainer and AI tool provenance.

## References
- Kernel development tools: https://docs.kernel.org/dev-tools/index.html
- Kernel testing: https://docs.kernel.org/dev-tools/testing-overview.html
- Kernel researcher guidelines: https://docs.kernel.org/process/researcher-guidelines.html
