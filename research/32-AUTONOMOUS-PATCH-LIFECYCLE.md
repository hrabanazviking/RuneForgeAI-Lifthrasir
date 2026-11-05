# Self-Evolution Engine: Controlled Patch Generation and Promotion
**Status:** design proposal; no self-modifying deployment implemented; 2026-11-05.

## Why 'self-evolving' is more than auto-update
A system that installs existing vendor updates is maintained, not necessarily self-evolving. Lífþrasir's research ambition is to discover a previously unaddressed defect or inefficiency, formulate a falsifiable theory, generate a minimal candidate, independently verify it, and present it for responsible integration. The active installation should not rewrite its own executable files while depending on them for rollback.

## Candidate state machine
**DISCOVERED → REPRODUCED → ROOT_CAUSE_PROPOSED → PATCH_DRAFTED → BUILT → TESTED → INDEPENDENTLY_VERIFIED → HUMAN_REVIEWED → STAGED → CANARY → DEPLOYED / REJECTED / REVERTED.**

No transitions may be skipped merely because the generator reports high confidence. Tests are matched to exact source digest and compiler version. A candidate that changes after verification must restart applicable gates.

## Minimal changes and evidence
- Begin from authoritative source history and exact failing commit.
- Produce the smallest diff addressing demonstrated behavior.
- Include at least one regression test that fails before and passes after.
- Compare source checker output and security impact.
- Use held-out tests and adversarial review independent from patch generator.
- Verify clean-room originality and license compatibility.
- Never auto-merge into the kernel or upload patches as a substitute for a human maintainer.

## Self-hosting paradox
If Lífþrasir itself has a bug, it may be least capable of safely fixing itself. Protect the broker, policy and journal via a minimal independent recovery supervisor. Generate new binaries in a separate build; test them under a shadow process; stage upgrade with transactional rollback. During migration, preserve protocol compatibility with older recovery agent.

## Promotion tiers
**Experiment:** entirely disposable VM, automatic within declared quota.  
**Candidate:** human-facing proposal with complete evidence.  
**Canary:** approved on one optional test device or VM; elevated telemetry, automatic rollback on regression.  
**General:** release signed by maintainers and distributed through normal package channel.  
**Kernel upstream:** separate human-led maintainer review and DCO process.

## Experiment
Take a small intentionally buggy open-source fixture. Use Replicater to propose patches, independent verifier to run mutation and regression tests, then record false-positive patch acceptance under adversarial injected logs. No host root needed.

## References
- Linux kernel patch process: https://docs.kernel.org/process/submitting-patches.html
- Kernel testing: https://docs.kernel.org/dev-tools/testing-overview.html
- SLSA: https://slsa.dev/spec/v1.2/
