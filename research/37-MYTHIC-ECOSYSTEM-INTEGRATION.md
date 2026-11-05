# Mythic Engineering Ecosystem Integration Contracts
**Status:** planned integration; interface names are conceptual; 2026-11-05.

## Architectural position
Lífþrasir should be usable standalone, while benefiting from sibling projects. It must not tightly couple its privileged broker to experimental agent engines, model servers or remote repository services.

## Proposed adapters
| Neighbor | Proposed role | Integration boundary |
|---|---|---|
| Mythic Engineering | Research workflow templates and named specialist agents | Unprivileged job envelope |
| Replicater | Parallel planning and verifiers | Bounded task orchestration protocol |
| Project A.E.S.I.R. | Optional local inference backend | Model request/response adapter |
| MímirAlloc | Optional allocator/memory experiments | Read-only metrics and sandboxed benchmark |
| Draupnir Forge | Build/artifact/test integration if compatible | Signed build provenance and API |
| Eir | In-repo repair-domain agent | Policy broker and rollback |
| Thor | In-repo defensive-domain agent | Evidence correlation and scoped containment |
| Upstream Forge | Kernel contribution preparation | Human-reviewed patch dossier |

Naming here describes *potential* integration. This document does not assert these projects already expose stable, interoperable APIs.

## Integration rules
- Typed versioned contract; no shared root shell.
- Identifiers and content hashes, not arbitrary filesystem paths to trust.
- Both caller and provider independently authenticate capability scopes.
- Cancellation, deadlines, resource quotas and structured errors.
- No required internet for host recovery.
- Per-integration license, privacy and threat-model review.
- Backward compatibility declared explicitly.

## Adapter handshake
Capabilities: model_generate, retrieve_docs, run_sandbox, benchmark, build_candidate, verify_attestation. Each capability declares version, availability, max resources, network policy and required permissions. Broader privileges cannot be negotiated through agent dialogue.

## End-to-end example
Heimdall detects fault → Mímir gathers exact version documentation → Replicater assigns parallel diagnostic branches → A.E.S.I.R. optionally generates localized candidate explanation → MímirAlloc optional benchmark tests memory-performance hypothesis → independent lab verifies candidate → Eir prepares human-approved reversible remediation → upstream steward creates patch dossier for Linux community.

## Avoid monolith
Each integration must fail gracefully when absent. User can install only observers/CLI with no model, or local model with no federation, or test lab without hardware acceleration. Keep per-project upgrade cadence separate.

## Research backlog
Inventory actual APIs and licenses in sibling repositories; produce compatibility table with evidence; prototype one adapter behind an integration test; add contract tests and dependency pinning; prohibit private tokens in agent context.

## References
- Local repo: https://github.com/hrabanazviking/RuneForgeAI-Lifthrasir
- Linux process: https://docs.kernel.org/process/development-process.html
- SLSA: https://slsa.dev/spec/v1.2/
