# Supply Chain Security, Provenance and Artifact Signing
**Status:** security research and schema proposal; 2026-11-05.

## Trust is not transitive
A trusted repository does not imply a safe build, and a signed artifact does not prove the code is bug-free. Lífþrasir must verify identity, source revision, origin, builder environment and intended deployment separately. Model-generated patch authorship is a distinct provenance dimension.

## Provenance for every candidate
Artifact ID/hash; source repository and immutable commit; dependency list/lockfile; compiler and link flags; build image hash; model/provider revision; generation context summary; human reviewers; test environment and raw result hashes; licenses; time, machine class and signature/attestation where supported.

## Existing standards
SLSA v1.2 describes supply-chain security requirements across build/source tracks and provenance. in-toto attestations and Sigstore-style signatures may help bind assertions to artifacts. Do not claim SLSA compliance just because a JSON file was produced; compliance depends on the actual builder and verified controls.

## Recommended artifact flow
- Fetch source using pinned revision, verify expected remote and integrity.
- Resolve dependencies from trusted approved registries with fixed versions.
- Build inside isolated reproducible environment when feasible.
- Capture build predicate/manifest and artifact digest.
- Run independent tests against exact digest, not an altered output.
- Sign/attest artifact using protected key mechanism only after human/policy approval.
- Verify attestation again at promotion/deployment time.
- Preserve immutable audit log and reversal target.

## Model provenance
Record model name, actual artifact hash, backend, system prompt template revision, non-secret task parameters and tools invoked. Do not include raw sensitive prompts or personal log fragments in public attestations. Recognize that model determinism may not be exact across accelerators or inference kernels.

## Key management
Never hand signing private keys to an LLM. Use dedicated signing service with policy-enforced one-action scope. Support key rotation and revocation; plan for offline devices where online identity verification is unavailable. A key compromise requires explicit alert and rejection of untrusted artifacts.

## Source and dependency attacks
Threat scenarios: typosquatted packages, malicious transitive dependency, poisoned commit or issue content, compromised build runner, modified compiler flags, replaced model file, unreviewed remote patch and mismatched local artifact hash. Each should become a test case.

## Evaluation
Publish a reproducibility report including exact clean-build steps and mismatch explanation. Run a tamper test: alter one byte of test artifact or its source pointer and ensure verifier rejects promotion. Test expired/revoked key handling and offline proof verification.

## References
- SLSA v1.2: https://slsa.dev/spec/v1.2/
- SLSA provenance: https://slsa.dev/spec/v1.2/provenance
- Kernel licensing rules: https://docs.kernel.org/process/license-rules.html
