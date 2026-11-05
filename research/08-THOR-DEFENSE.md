# Thor: Defensive Security, Threat Hunting and Safe Containment
**Status:** defensive design research; 2026-11-05.

## Definition
Thor is a **defensive endpoint investigator**, not a self-appointed process executioner. The mythological 'troll-slayer' metaphor maps to narrowly scoped defensive actions such as block, suspend, isolate and quarantine when reliable evidence supports them. A suspicious process should be investigated, not automatically deleted.

## Inputs
- Kernel audit and LSM-reported events where authorized.
- Process lineage, executable path and file hash, package provenance.
- Network connection metadata where permitted.
- User-approved file-integrity baselines, signed update metadata.
- Correlation with known exploit indicators from reputable advisories.
- Environment inventory including services, containers, remote sessions and development tools.

## Threat categories
**Commodity malicious binaries:** foreign executable, persistence mechanisms, unauthorized modifications.  
**Cryptominers or unwanted compute:** distinguish user-approved simulations, benchmarks and distributed research from unauthorized mining.  
**Credential theft:** investigate secret access patterns without collecting secret contents.  
**Ransomware-like modification:** detect abnormal high-rate destructive writes; preserve immutable evidence and user data where possible.  
**Persistence and privilege escalation:** review sudo changes, service definitions, cron/systemd timers, kernel module loads and authentication logs.  
**Network intrusion:** identify suspicious remote access or data exfiltration while avoiding packet interception beyond consent.

## Evidence ladder
1. Anomaly: unusual resource or network pattern.
2. Correlation: suspicious event coincides with an unauthorized change.
3. Independent verification: signature, provenance mismatch, corroborated telemetry or reproduced exploit indicator.
4. Confirmed incident: sufficient evidence for a defined response, with an uncertainty report and review.

An anomaly alone is never a valid deletion trigger.

## Safe response ladder
- **R0:** explain and observe.
- **R1:** user-visible warning with evidence.
- **R2:** request approval for reversible containment such as blocking a specific outbound destination or temporarily stopping one verified process.
- **R3:** policy-approved high-confidence response for a user-opted-in, narrowly scoped class; auto-revert on control loss.
- **R4:** host-wide remediation only under explicit, incident-specific human authorization with recovery plan.

Quarantine should be content-addressed, access-controlled and restorable; never indiscriminately move files essential for boot. Preserve hashes, timestamps and chain of custody without copying sensitive user data into cloud services.

## Attack-resistant design
An attacker may plant a fake kernel panic line into a logfile, rename a useful daemon to 'malware', or make an AI agent reason about malicious instruction text. Ensure Thor's policy engine ignores model-generated authority claims. Defense actions must be based on typed conditions and independent evidence; privileged execution is broker-only.

## Verification and controls
Run false-positive tests with developer tools (compilers, fuzzers, local AI servers), high-throughput backup tools and game launchers. Ensure Thor does not confuse local inference with cryptomining or scheduled research with an attack. Test process PID reuse to prevent killing an unrelated successor. Block only precise network rules with expiry and local recovery.

## Security research ethics
Unknown critical security bugs require responsible reporting and potentially confidential handling; automatic public bug reports could create risk. Thor should preserve evidence and guide the human through a coordinated report to the proper maintainers.

## Research experiments
Measure precision/recall on a synthetic benign+malicious workload corpus; time to detect; containment reversibility; false service disruptions; agent refusal to execute forged instructions from logs; and recovery after a mistaken containment.

## References
- Linux LSM overview: https://docs.kernel.org/admin-guide/LSM/index.html
- Landlock: https://landlock.io/
- Linux kernel security reporting: https://docs.kernel.org/process/security-bugs.html
- Kernel tracing: https://docs.kernel.org/trace/index.html
