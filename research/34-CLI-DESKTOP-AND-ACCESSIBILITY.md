# User Experience: CLI, Desktop, Accessibility and Trust
**Status:** product design study; 2026-11-05.

## UX principle
A repair tool should never force its user to decipher opaque AI reasoning before getting a working computer. Display facts, suspected causes, proposed change, risk, exact scope, recovery and approval in clear separate sections.

## Interface tiers
**CLI first:** works from rescue shell or text-only server and degrades with no GPU or LLM.  
**Desktop later:** KDE/Qt-compatible UI on Kubuntu first; other desktop frontends optional.  
**Headless:** secure local API/CLI that can be accessed through a user-chosen remote channel, without disabling local consent.  
**Expert mode:** full diagnostic trace, source provenance, evaluation matrices and manual override of safe advisor heuristics without bypassing policy.

## Incident card
Show title, affected service, evidence source/time, certainty level, user impact, current mode (observe/advise/repair), action consequences and undo method. Distinguish 'suspected', 'reproduced', 'tested in VM', and 'verified on this host' with text, not only color.

## Approval screen
Before action: resource path/name, precise before/after diff, privilege requested, estimated downtime category, files touched, snapshot status and recovery. Offer **Reject**, **Explain**, and **Approve once**; do not hide the latter as a default control. For high risk require explicit review and maintenance plan.

## Accessibility and sensory design
Support keyboard-only navigation, screen readers, reduced motion, optional muted notifications, selectable contrast and compact logs. Alerts should be severity-sensitive and suppress repetitive harmless noise; a machine that chimes for every hypothesis is hostile to focus. No dark-pattern consent.

## Respect for autonomy
User can select constrained offline mode, disable agents, specify resource budgets or decline federation. No guilt language when declining upgrades. Actions are logged and human readable. Provide safe read-only exports without cloud signup.

## Research evaluation
Usability sessions with novice, intermediate and kernel-expert Linux users: do they identify what will change, explain how to revert, distinguish evidence from hypothesis and reject dangerous plans? Track error rate and consent comprehension, not time to click 'Approve'.

## References
- Linux contribution style: https://docs.kernel.org/process/submitting-patches.html
- systemd service status model: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
