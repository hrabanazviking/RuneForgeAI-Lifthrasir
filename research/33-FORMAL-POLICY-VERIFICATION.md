# Deterministic Policy Verification and Security Invariants
**Status:** formal methods research agenda; 2026-11-05.

## Core hypothesis
A small, auditable policy kernel is easier to verify than a large agent runtime. Constrain privileged behavior to a finite catalog of actions and machine-checkable invariants. The model can propose, but cannot certify that a policy has been satisfied.

## Essential invariants
1. Any write action requires a valid, unexpired, non-replayable authorization for the exact plan digest.
2. A user action outside the allowed target resource must fail.
3. Neither prompts, logs nor retrieved documents can grant broker capabilities.
4. Unknown schema, action verb, tool result or platform capability denies execution.
5. A policy transition cannot be caused by model self-reported 'emergency'.
6. After a crash, recovery never accidentally replays a previously committed action.
7. For an automated action, a verified undo path must exist before execute.
8. Broker cannot access arbitrary filesystem paths or networks outside granted scope.

## Verification techniques
**Property-based testing:** Generate random plans and credentials; assert invariants.  
**Model checking:** Describe the repair lifecycle as a state machine and explore interleavings of crash, rollback, expiry, approval and revocation.  
**Fuzzing:** Attack serialized request formats, path traversal and signed-token decoder.  
**Static analysis:** Run sanitizers, linters, code scanning and dependency analysis on privileged components.  
**Manual review:** Examine the tiny trusted base, especially capability attenuation and race handling.

## Example dangerous interleaving
Plan approved for service A when config hash X. Another process changes config to Y. A naive broker applies a patch based on X and corrupts Y. The invariant demands atomic recheck at point of mutation, or failure if exact safe precondition cannot be established.

## Proposals for specification
Use finite state machine and temporal logic in a formal model (e.g., TLA+ or Alloy subject to team expertise). Start with a bounded model of token issuance, plan acceptance, broker execution and recovery. Test loss of power between every durable write and every external side effect. Keep formal proof limitations explicit: a verified model is not the same thing as verified deployed code.

## Review artifact
Each release contains policy test report, list of permitted verbs, denied-case coverage, residual risks, and evidence showing that an AI agent cannot dynamically add a broker verb.

## References
- Landlock isolation: https://landlock.io/
- Linux LSM: https://docs.kernel.org/admin-guide/LSM/index.html
- cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
