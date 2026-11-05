# Licensing, DCO, Dependencies and Distribution Strategy
**Status:** technical/legal research guide, not legal advice; 2026-11-05.

## Current repository status
The existing repository contains a GNU GPL version 2 license text. The project should identify intended code license unambiguously as **GPL-2.0-only** if that is the chosen policy, and apply SPDX identifiers in new source files. Preserve third-party notices and obligations. Documentation and artwork may require separate explicit licensing assessment when added.

## Kernel integration
Linux kernel code is GPL-2.0-only, with specific additional licensing rules for particular files and dual-licensed components. Avoid assuming every license marketed as 'open source' is compatible with incorporation into GPLv2-only kernel code. Use the kernel's preferred SPDX conventions.

## User-space compatibility
User-space components are not automatically derived works of the kernel just because they call normal syscalls. Kernel UAPI, linking, static/dynamic dependencies and redistribution need careful case-specific legal review. A GPLv2-only core can coexist with separately licensed tools subject to actual interaction and redistribution details; no blanket compatibility claim.

## Third-party assets
The Viking Tux artwork is part of the repository but should have explicit owner and permission/license documentation before redistribution into packages. Model weights, training datasets, inference libraries, drivers and firmware frequently have different terms; record them individually.

## Contribution process
Require contributors to affirm rights to contribute original or properly licensed code. For Linux upstream, only a human can provide DCO Signed-off-by. For Lífþrasir's own repository, choose and document whether to adopt DCO as well. Reject copied code without traceable provenance and license.

## Dependency manifest
For every runtime dependency record name, version or pinned commit, upstream URL, license SPDX, transitive license issues, known vulnerabilities, update policy, platform support and reproducible build strategy. Produce SBOM in an appropriate standard format before significant binary distribution.

## Build and packaging
Do not bundle proprietary or incompatible kernel components indiscriminately. Allow optional connectors with documented user-controlled installation where legally appropriate. Keep GPL-covered source, build instructions and corresponding source distribution obligations available for distributed binaries.

## Security of model licenses
'Open weights' does not necessarily mean open source. Some model licenses impose use restrictions, attribution or commercial terms. Support model substitution and warn on unverified license rather than silently download an unavailable model.

## Research actions
Review LICENSE against expected SPDX; add LICENSES/ directory if using mixed components; write THIRD_PARTY_NOTICES; document art license; scan dependencies in CI; set a clean-room policy for patches produced from external proprietary code and refuse plagiarism.

## References
- Linux kernel licensing rules: https://docs.kernel.org/process/license-rules.html
- SPDX license list: https://spdx.org/licenses/
- Kernel AI development policy: https://www.kernel.org/dochtml/latest/process/coding-assistants.html
