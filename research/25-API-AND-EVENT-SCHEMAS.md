# API Contracts, Event Schemas and Policy Engine Interfaces
**Status:** provisional v0 schema proposal; not an implemented API; 2026-11-05.

## Design principles
Version every envelope; validate all inputs strictly; model outputs are *untrusted proposals*; use explicit state transitions; make destructive actions impossible to express in a generic shell string. Binary logs are stored separately with hashes; API metadata contains only references.

## Primary event types
**health.observation.v0**: event_id, host_local_id, recorded_at, monotonic_ns, boot_id, source, observed_resource, metric, severity, raw_evidence_digest.  
**incident.opened.v0**: incident_id, impact, symptoms, triggering_events, known_unknowns.  
**hypothesis.proposed.v0**: hypothesis_id, incident_id, claim, evidence_for, evidence_against, test_plan.  
**repair.proposed.v0**: plan_id, target_resource, action_verb, exact_arguments, preconditions, failure_rollback, risk_level, verification, expiry.  
**repair.authorization.v0**: actor, plan_digest, permitted_action, target_hash, consent_time, expiry, nonce.  
**repair.result.v0**: execution digest, policy decision, actor, before/after states, test results, rollback status.  
**lab.evidence.v0**: immutable build/test provenance and result artifacts.  
**upstream.dossier.v0**: patch series details, evidence, tool-assistance declaration, human-review status.

## Illustrative JSON contract (not executable policy)
    {
      "schema": "lifthrasir.repair.proposal.v0",
      "plan_id": "example-001",
      "target": {"type": "systemd-user-unit", "name": "demo.service"},
      "action": {"verb": "restart_unit", "args": {"unit": "demo.service"}},
      "precondition": {"expected_state": "failed"},
      "risk": "low-reversible",
      "rollback": {"method": "restore_recorded_state"},
      "verify": {"method": "unit_healthy", "timeout_seconds": 20},
      "expires_at": "2026-11-05T18:00:00Z"
    }

Important: 'restart_unit' in this example is conceptual. The broker would still check that the unit is allowlisted, the identity and current state match, the user authorized the action, and the operation cannot target a critical service.

## Policy decision API
Input: immutable plan, authorization context, host capability descriptor and current exact precondition snapshot. Output: ALLOW, DENY or REQUIRE_HUMAN, with policy version and reason codes. The agent cannot submit a policy override. The default for unknown action/resource/version is DENY.

## Concurrency and replay
No implicit last-write-wins for critical state. Treat plan ID and current digest as compare-and-swap; perform one-time nonce consumption and audit append before applying the action. On crash recovery, inspect actual host state rather than blindly reissue plan. Event order is per-host monotonic, cross-host causal references use explicit parents.

## IPC security
Prefer Unix domain sockets, process identity verification and limits on message size, nesting and rate. Validate UTF-8 paths, prohibit traversal and symlink escapes, and never use unsanitized string interpolation into shell commands. If a task needs a shell, keep it inside a low-privilege test VM and outside broker capability vocabulary.

## Compatibility rules
Additive fields may be tolerated if explicitly advertised; unknown action verbs must always be rejected. Schema migrations preserve original audit records, hashes and causality. Human-facing output explains authorization reasoning and exact diff.

## Testing
Property tests for untrusted JSON and malformed Unicode; fuzz decoder; duplicate nonce; expired token; request after state change; mismatched resource ID; malicious log instruction; race between authorization and execution; failed journal write.

## References
- Linux capability controls: https://docs.kernel.org/admin-guide/LSM/index.html
- cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
