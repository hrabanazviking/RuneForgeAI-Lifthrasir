# The Upstream Forge: Linux Patch Contributions Without Maintainer Spam
**Status:** policy-backed engineering plan; 2026-11-05.

## Correct target
Linus Torvalds is not the default recipient for individual kernel fixes. The Linux kernel community uses subsystem maintainers and mailing lists, with MAINTAINERS and scripts/get_maintainer.pl identifying routes. GitHub can host Lífþrasir development but GitHub PRs are generally not the normal pathway for Linux kernel contributions.

## Required human responsibility
Linux kernel AI guidance says AI agents **must not** add Signed-off-by tags. A human contributor reviews the work, ensures appropriate license, takes responsibility and signs the Developer Certificate of Origin (DCO). Attribution of AI assistance should follow current kernel guidance; never invent a human identity or claim a model can legally sign.

## Prepare a patch dossier
- Precise symptom and user impact.
- Root cause with source references, not speculation.
- Minimal original reproducer and baseline fail evidence.
- Base tree commit and target maintainer tree.
- One logical change per patch; clear rationale.
- Regression tests and exact command/toolchain/config/platform.
- Static, dynamic, fuzz and cross-architecture results as relevant.
- Side-effect and performance numbers; include negative results.
- Tool-generated content transparency (models, tools, prompts where appropriate).
- Human review status, license audit and approval to send.

## Upstream workflow
1. Before writing, search existing patches and active reports. Prefer finishing known work to duplicating it.
2. Reproduce against current relevant maintainer tree.
3. Build minimal patch and test. Use kernel coding style and scripts/checkpatch.pl as a guide.
4. Run appropriate KUnit/kselftest, cross-build and subsystem tests.
5. Human reviews *every line*, provenance and implications.
6. Human adds Signed-off-by if legitimately certifying DCO; AI does not.
7. Use b4/git format-patch and maintainer-specific instructions as appropriate.
8. Send to relevant subsystem maintainers/lists, not indiscriminately to Linus or unrelated lists.
9. Respect reviewer time, answer comments, update version, repeat tests.
10. Track accept/reject/defer and integrate feedback into Mímir.

## AI attribution
The AI Coding Assistants documentation provides an Assisted-by format. Since guidance evolves, read the *current* docs before each submission rather than hardcode a historical string. Generated-content guidance asks for transparency about generation scope and testing. DCO is always a human attestation.

## Security bugs
Potentially exploitable vulnerabilities should follow kernel security reporting channels and avoid premature public disclosure. Do not broadcast fresh exploit details to a public federation or auto-open a public issue.

## Value over volume
Patch submission count is not a sensible KPI. Prefer accepted, regression-tested improvements with low maintainer effort, minimized reproducer, clear evidence and responsive human contributor. A patch that requires maintainers to debug an agent's hallucinations is a cost, not a donation.

## Example checklist
- [ ] Failing test on exact baseline recorded.
- [ ] Root cause and source line/path confirmed.
- [ ] Small patch and regression test reviewed.
- [ ] All test results tied to source/tool versions.
- [ ] Distribution and architecture claims limited to tested scope.
- [ ] Tool assistance disclosed.
- [ ] Human sign-off and submit approval.
- [ ] Correct subsystem recipients identified.
- [ ] Security disclosure routing checked.
- [ ] Follow-up owner assigned.

## References
- Submission guide: https://docs.kernel.org/process/submitting-patches.html
- AI coding assistants: https://www.kernel.org/dochtml/latest/process/coding-assistants.html
- Generated-content guidance: https://docs.kernel.org/process/generated-content.html
- Patch checklist: https://docs.kernel.org/process/submit-checklist.html
- b4 documentation: https://b4.docs.kernel.org/en/latest/
