# Governance, Permissions, Accountability and Human Control
**Status:** project policy draft; 2026-11-05.

## Value proposition
Lífþrasir should empower Linux users and maintainers, not transform machines into opaque, self-directed administrators. The project explicitly rejects automatic consent escalation, hidden telemetry sharing, fabricated sign-offs and high-risk mutation under the banner of 'evolution'.

## Governance layers
**User:** owns host decisions, permissions, schedule, budget and retention policy.  
**Device policy:** immutable guardrails for privilege, secrets, reboot, network and recovery.  
**Developer/operator:** responsible for source and release signing, vulnerability handling and configuration defaults.  
**Upstream maintainer:** retains full autonomy to accept, reject or defer proposed patches.

No autonomous agent can override all four boundaries.

## Rights and controls
- Installation defaults to read-only observation.
- Pause/disable and uninstall function offline.
- Every action has a plain-language explanation and reversible evidence trail.
- Users can approve exact scoped actions, not blanket root.
- Optional federation requires separate opt-in; can be disconnected immediately.
- Historical incident data can be exported or deleted by user subject to explicit legal/technical retention limits.
- UI clearly marks experimental, unverified and fully tested functionality.

## Review structure
Adopt a code of conduct, contribution guide, security policy, maintainer rotation and design-review process. High-risk broker changes require multiple independent reviewers and adversarial test evidence. Preserve public discussion of rejected designs so other contributors do not reintroduce dangerous shortcuts.

## AI participation
Agents may author research and code drafts, but are not substitutes for human DCO signatures, security triage ownership or legal consent. Publish honest AI-assisted provenance; credit human and machine tooling appropriately without attributing human experiences or legal personhood to software.

## Metrics and incentives
Reward reduction in real incidents, quality of diagnoses, safe abstention, reliable rollback, maintainer usefulness, reproducible evidence and low noise. Do not reward raw volume of patches or autonomous actions. Require explicit postmortem for every unintended production change.

## Abuse boundaries
No remote mass deployment without host consent; no stealth resource pooling, code execution or vulnerability probing of unrelated systems. Thor is defensive, not punitive. Federation cannot conscript devices. Research code capable of changing kernel behavior remains isolated by default.

## Release gates
A release is blocked by failed privilege-escalation tests, destructive-action loopholes, no manual recovery path, unattended public security disclosure, or inability to disable agent reasoning. Disclose known limitations; do not claim the product is 'self-evolving' in production until measured demonstrated milestones are met.

## Research and decision log
Use RFC documents with question, alternatives, evidence, dissent, expected user impact, security effects and decision date. Store architecture decisions separately from model-generated speculative suggestions. Periodically revisit assumptions after kernel/distro changes.

## References
- Linux kernel researcher guidelines: https://docs.kernel.org/process/researcher-guidelines.html
- AI kernel contribution guidance: https://www.kernel.org/dochtml/latest/process/coding-assistants.html
- Tool-generated content: https://docs.kernel.org/process/generated-content.html
