# Offline-First Architecture, Privacy and Data Minimization
**Status:** design policy; 2026-11-05.

## What privacy means here
Linux health logs may contain usernames, command arguments, environment variables, private file paths, IP addresses, hostnames, SSH metadata, credentials and application content. A repair agent should not automatically turn its owner's machine into a telemetry broadcaster.

## Default stance
No network access required for observation, repair decisions or manual recovery. No remote model API enabled automatically. No raw log upload, no periodic telemetry submission, no automatic federation. The user opts in to *specific purposes*, scopes and destination classes.

## Offline functionality levels
1. **Full local basics:** Health check, deterministic diagnostics, policy engine, safe approved low-risk actions, rollback, CLI.
2. **Optional local AI:** Models stored on disk; explain incidents and propose tests.
3. **Offline documentation:** Cached man pages, distribution docs and previously fetched source references with visible ages.
4. **Deferred network:** If disconnected, queue user-approved research tasks with expiry; never queue secrets.
5. **Network-enabled research:** Use a restricted proxy, display destination, review sensitive fields, and verify downloaded artifacts.

## Redaction pipeline
Tag fields with source and sensitivity. Remove credentials using multiple strategies: known token formats, process arguments, path components and custom user rules. Treat regex-based scrubbing as fallible; enforce preview for outgoing artifacts and conservative default blocking for unknown binary blobs.

## Retention
Set separate limits for operational event metadata, raw logs, model prompts, model outputs, traces, crash dumps, experiment results and federation outputs. Older incidents may preserve aggregated metadata without raw secrets. Provide an accessible 'delete local knowledge' path that also covers derived indexes, with caution about backups already exported.

## User-visible privacy budget
Each remote research request shows the minimal fields to share. Allow manual approval of redacted excerpt. Provide no hidden 'send diagnostics' control. De-identification is difficult; require opt-in even for hashed hardware IDs, which can still be linkable.

## Connectivity resiliency
Never make early boot depend on remote authentication, GitHub, a cloud LLM or a federation coordinator. Offline first also implies no license activation server, no forced vendor account and no critical remote key fetch without a documented local recovery plan.

## Tests
Fake a credential in journal metadata and confirm it never leaves host in a research artifact. Deny network and verify repair process works. Revoke consent while a job runs; ensure subsequent upload is blocked. Remove encrypted data key and verify retention deletion behavior is documented.

## References
- Linux logging/tracing: https://docs.kernel.org/trace/index.html
- Security data hygiene: https://slsa.dev/spec/v1.2/
