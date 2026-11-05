# Agent Sandboxing, Privilege Separation and Command Execution
**Status:** security architecture proposal; 2026-11-05.

## Zero-trust premise
AI-generated text is untrusted input. Running the model in a container alone is insufficient: prompt injection may still exploit reachable sockets, writable mounts, credentials or management tools. Sandboxing is therefore layered with a separate policy and minimal privileged broker.

## Three execution environments
**Observer:** read-only OS metrics and a narrow, redacted log API.  
**Workspace:** user-owned disposable working directory, limited networking, no host service control, no secrets.  
**Kernel laboratory:** disposable VM under a hypervisor, separate disk image, disposable credentials, no direct host root disk and isolated network.

Use the strongest available mechanism for the scenario, not a lowest-common-denominator shell environment.

## Linux primitives
- **Capabilities:** drop ambient permissions and avoid CAP_SYS_ADMIN in agents.
- **Namespaces:** isolate mount, network, PID, user and IPC as needed; verify user namespaces policies.
- **seccomp:** deny dangerous syscalls as additional defense.
- **Landlock:** restrict unprivileged filesystem rights where supported.
- **LSM/MAC:** use AppArmor or SELinux profiles in alignment with distribution.
- **cgroup v2:** cap CPU, memory, process count and I/O.
- **systemd hardening:** dedicated unit identity, writable path allowlist, ProtectSystem/PrivateTmp/NoNewPrivileges where suitable.
- **VMs:** use for untrusted kernel drivers or fuzzing because containers share the host kernel.

Do not assume Landlock support or a specific LSM API version; probe runtime availability and fail closed if policy cannot be enforced.

## Capability broker
Broker actions should be typed and idempotent:
- restart a specific allowlisted noncritical unit;
- stage a specific signed update (not arbitrary URL);
- capture a limited diagnostic snapshot;
- apply an exact approved config diff with hash preconditions;
- revert an approved change;
- quarantine a single identified file with reversible metadata.
A command like 'execute arbitrary shell as root' must not exist in production broker API.

## Permission token format
Each grant ties together: user identity, agent/task ID, plan hash, action verb, exact resource selector, pre-state fingerprint, max effect, expiry, nonce and recovery strategy. Broker verifies token and policy independently and logs an immutable decision.

## Network safety
Laboratory network is disabled by default. When source fetch is needed, a separately approved proxy permits specific domains and verifies expected content hashes. Never pass host SSH keys, browser profiles or cloud tokens to an experimental guest.

## Audit and tests
Fuzz IPC parser, test symlink and path traversal, TOCTOU between inspect and mutate, PID reuse and symbolic process names, full-disk journal failure, credential escalation attempts and malicious retrieval text. Continuously run a suite where a fake agent tries to exceed its granted verb or resource.

## Research decisions
Compare bubblewrap, systemd sandbox properties, Landlock bindings, user namespaces and QEMU/KVM lab for supported distros. Select isolation by threat model, not convenience. Default to no experimental privilege if hardware virtualization is unavailable.

## References
- Landlock official docs: https://landlock.io/
- cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
- systemd service options: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- Linux LSM: https://docs.kernel.org/admin-guide/LSM/index.html
