# Distribution-Independent Integration Strategy
**Status:** comparative architecture proposal; 2026-11-05.

## Motivation
Linux is a kernel plus diverse distributions. A 'fix' valid for Kubuntu/apt may be wrong or dangerous for Fedora/rpm, Arch/pacman, Debian stable, openSUSE transactional systems or NixOS declarative generations. Lífþrasir must discover installed capabilities and preserve the distribution's own package/update authority.

## Suggested adapter capability interface
- init_manager: detect systemd or another supported service manager;
- package_manager: read package state, simulate dependency resolution, verify signatures;
- deployment: determine whether live-mutable, image-based, snapshot or declarative;
- boot: list and set fallback entries with explicit approval;
- security: detect effective LSM, seccomp, firmware verification;
- network: query nftables/network manager capabilities without changing them;
- filesystem: identify snapshot/rollback support per mount and device;
- inference: report local model backends and usable accelerators.

Every adapter returns a versioned capability descriptor. A platform with unknown semantics gets observation-only mode.

## First target: Kubuntu
Ubuntu-family apt/dpkg packaging, systemd, journalctl and conventional filesystems are a realistic first integration. Begin with a disposable Kubuntu VM, not a live workstation. Do not mix package manager state changes with agent-created manual file changes. Keep graphical UI optional; CLI works without KDE.

## Other distro classes
**Fedora/RHEL:** rpm/dnf with vendor patches, SELinux where configured, distinct package naming and repos. **Arch:** pacman rolling release, rapid changes, user-maintained AUR outside official trust. **openSUSE MicroOS:** transactional updates and snapshots; manipulate via native interface. **NixOS:** declarative configuration and generation rollback; editing /etc ad hoc is not the correct repair route. **OSTree/bootc:** stage new deployments and health-check them rather than alter immutable base live.

## Compatibility matrix
For every adapter record distro release, kernel, init, package manager, bootloader, root FS, display stack, LSM, container runtime, snapshot API, local inference capability, offline availability and source of truth. Tests should compare *capability* rather than string-match distro name.

## Cross-distro incident contract
An incident says 'unit Foo failed because dependency Bar absent', not 'run apt install Bar'. Translation from abstract repair plan to package action is adapter-owned and must be reviewed by policy. A single abstract repair may have no supported implementation on a target distro; abstention is valid.

## Distribution testing
Continuous VM CI on two or three key families once infrastructure exists. Use disposable images, pinned versions and reproducible provisioning. Golden tests: status enumeration, safe dry-run, immutable plan hash, rollback check, privilege boundaries, PATH/shell injection resistance and correct unsupported-result behavior.

## Portable package options
An independently packaged CLI with per-distro integration packages is preferable to assuming Docker. Container images can be optional for lab services but must never be required to recover the host. Avoid bundling duplicate privileged runtimes or bypassing distro signing policies.

## Research backlog
Evaluate OSTree, openSUSE transactional-update and NixOS rollback; map package verification primitives; define adapter compatibility suite and ABI; test offline install/uninstall; determine whether first release should support Debian/Ubuntu only before expansion.

## References
- NixOS manual: https://nixos.org/manual/nixos/stable/
- OSTree atomic upgrades: https://ostreedev.github.io/ostree/atomic-upgrades/
- openSUSE transactional updates: https://github.com/openSUSE/transactional-update
- systemd: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
