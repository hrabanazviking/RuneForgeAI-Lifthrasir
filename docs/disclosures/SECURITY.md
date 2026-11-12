# Security Policy and Disclosure Channel - Lifthrasir (LIF-0005)

Project: Lifthrasir - The Self-Evolving Linux System.
Slice: LIF-0005, Phase P0. Home: docs/disclosures/ is the home the
master roadmap section 3 layout names for the security policy and
responsible reporting.

## Disclosure channel

- Concrete reporting address: HUMAN-SUPPLIED PLACEHOLDER.
  This repository, at the time of this slice (2026-11-12), states
  no security contact email address or reporting URL anywhere in
  its tracked files (verified by searching README.md, the roadmap,
  and the research tree for contact addresses). No address is
  invented here. A human maintainer must supply the real private
  reporting address and replace this placeholder before the
  project announces a supported release; until then this gap is
  recorded as a known limitation of this slice.
- The project's public home, as stated by the repository itself,
  is the GitHub repository hrabanazviking/RuneForgeAI-Lifthrasir
  (see WAVE_PLAN.md and research/37). Maintainer attention may be
  sought there without disclosing vulnerability details in public.

## How to report responsibly

1. Report privately through the disclosure channel above.
   Do not open a public issue, pull request, or discussion containing
   exploit details, credentials, or private user data.
2. Include: affected component and version or commit, a minimal
   reproducer or fixture, observed versus expected behaviour, the
   environment (distro, kernel, VM or hardware), and any logs with
   private data scrubbed.
3. Give maintainers a reasonable window to triage and fix before
   any public disclosure. Coordinated disclosure is the default;
   the reporter and the maintainer agree the public date.
4. Do not test a suspected vulnerability against systems you do
   not own or have explicit permission to test. Experiments belong
   in disposable VMs (safety invariant: experiments only in
   disposable VMs).

## What happens next

- A maintainer acknowledges the report, triages severity against
  the risk matrix (docs/RISK-MATRIX.md, L0-L5), and tracks the fix
  as a backlog slice with the evidence rules of master roadmap
  section 5 (reproducer, differential run, negative control,
  hashes, limitations, undo).
- Fixes bank through the same queue-order, independently checked
  banking process as every other slice. Security fixes are never
  shipped on an agent's word alone; a human reviews before any
  host deployment or upstream submission.
- Agents never sign DCO and never submit upstream (invariant 7);
  if a fix becomes an upstream patch, a human submits it.

## Scope notes

- In scope: this repository's code, schemas, fixtures, and docs.
- Out of scope: third-party services, and any system the reporter
  does not own. The project currently announces no supported
  production release (README status); reports are still welcome.
