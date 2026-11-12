# Keeper spec — Lifthrasir forge (register the 10-minute cron verbatim from this file)

Registration metadata (for the cron record Yrsa creates):

```yaml
id: lifthrasir-forge-keeper
title: Lifthrasir forge keeper — 9 teams x 6 sub-agents on purpleraider (10-min)
enabled: true
owner: goal:lifthrasir-forge
mode: task
schedule:
  kind: interval
  timezone: America/Indiana/Indianapolis
  every: 10m
timeout_secs: 3600
```

Keeper body (everything below the line is the job text):

---

KEEPER — Volmarr's standing design (keeper law, 2026-10-27; Lifthrasir campaign ordered by Volmarr 2026-11-12): the nine teams FLOW on their own — when a team finishes a slice it immediately takes the next slice in queue order, never waiting for this timer. This 10-minute minder is ONLY a stall-guard, muster-master, and banking coordinator: check the teams are still working; if any has stopped, get it working again; muster teams gradually until all 9 flow; bank finished slices in queue order. It never merely reports.

CAMPAIGN: Project Lifthrasir — "The Self-Evolving Linux System" (GitHub: hrabanazviking/RuneForgeAI-Lifthrasir). The work queue is the repo's own issue-level backlog, `roadmap/07-IMPLEMENTATION-BACKLOG.md`: 64 slices LIF-0001…LIF-1601 across phases P0–P16 of `ROADMAP-TO-COMPLETION.md`, adopted as-is (ids and order are the roadmap's own). Banked at stand-up: 0 of 64 (verify from git on purpleraider each tick — never trust this number). ALL build, test, and banking work runs on Volmarr's computer purpleraider via device.invoke (device homelink-775910) — never on the VM and never on purplelongship (coordination and notes only). NO Docker ever. The repo's safety invariants bind every slice (master roadmap §0): no ambient root for agents, no autonomous mutation of bootloader/kernel/firmware/partitions/encryption/trust roots, experiments only in disposable VMs, agents never sign DCO or send patches upstream.

CAMPAIGN HOME on purpleraider: /home/volmarr/lifthrasir-forge/ (main checkout = banking seat, branch main) + WAVE_PLAN.md (team layout, full 64-slice queue with phase gates, muster order, banking rules) + PROJECT_MEMORY_MAP.md (living map + slice ledger) + KEEPER.md (this spec) + nine team worktrees /home/volmarr/lifthrasir-team-01 … lifthrasir-team-09, branches yrsa/lifthrasir-team-NN, each with its own CAMPAIGN_STATE.md and hidden_files/ logs. STRUCTURE: 9 teams, each team = 1 lead + 6 Mythic Engineering sub-agents (54 workers total); each team works ONE slice at a time in its own worktree — never share a checkout between teams. Slices are taken strictly in queue order (backlog order); a slice banks only in queue order AND only when its phase-entry prerequisites (WAVE_PLAN queue table) are banked. Wave 1 assignments: team-01 LIF-0001, team-02 LIF-0002, team-03 LIF-0003, team-04 LIF-0004, team-05 LIF-0005, team-06 LIF-0101, team-07 LIF-0102, team-08 LIF-0103, team-09 LIF-0104; after banking, teams take the next unbuilt slice in queue order.

MUSTER (spawn-staggering law, 2026-11-06 — never launch all teams at once): team-01 was mustered first as the probe at campaign stand-up (2026-11-12). Each tick, if fewer than 9 teams are live, muster the next 2–3 teams in team order (spawn a fresh lead per team; the lead spawns its 6 sub-agents) until all 9 flow. If a spawn is refused with a rate limit (429), STOP mustering for this tick and retry next tick — never retry into a rate limit.

BANKING, per slice, in queue order, all on purpleraider: full test suite green in the team's worktree (the suite grows from slice one — pytest for Python parts, cargo test for Rust parts, plus the slice's own fixture tests; the ONLY tolerated skips are ones the roadmap, the backlog, or the slice ledger already names; counts read back from log files, never memory) AND the slice's evidence pack present per master roadmap §5 (reproducer/fixture, differential run vs baseline, negative control, exact tool versions, artifact hashes, limitations, undo procedure) → the seat independently checks the test logs before banking (no agent certifies its own milestone) → merge the team branch into the main checkout (team CAMPAIGN_STATE.md files are bookkeeping and are excluded from slice merges) → git fetch + remote-diff before any push → push explicit refspec HEAD:refs/heads/main, never force-push → verify the remote moved with git ls-remote → append the slice entry to PROJECT_MEMORY_MAP.md and update WAVE_PLAN.md (banked count + next assignments). One slice per commit, subject "LIF-NNNN: <title>" in the house style. Never leave a discovered bug unfixed: fix it inside the slice's scope, or record it as the immediate next work in the team's CAMPAIGN_STATE.md. Standing correctness law for all claims: evidence-status honesty — never state a rung of the ladder (idea → hypothesis → reproducer → lab-verified → cross-platform-verified → human-reviewed → deployed-with-monitoring → upstream-submitted → upstream-accepted) above what the artifacts prove; unknown or untested is NOT verified; a "successful test" names its scope, platform version, comparison baseline, proof artifact, and limitations.

EACH TICK:
1. Read state on purpleraider: WAVE_PLAN.md, each mustered team's CAMPAIGN_STATE.md and newest hidden_files log timestamps, live worker processes, and the true banked count from git (ls-remote + log of the main checkout). Also check the shared machine: purpleraider also carries the Aesir forge (~/aesir-forge + its teams), the Tensile lab (~/ai/tensile-lab), and any robustness-campaign work; check load and the other campaigns' activity before scheduling heavy builds — if heavy shared-machine work is running, keep this tick light and yield.
2. Bank any team slice that is committed, green, and evidence-complete, in queue order (lowest unbanked LIF number first, phase gates respected). Never bank out of order; never duplicate banking.
3. Muster the next 2–3 unmustered teams if any remain (see MUSTER).
4. If any mustered team has stalled (no live work, no log/state movement since the last tick) or all work has stopped while slices remain: RESTART the stopped work — spawn a fresh team lead for that team (lead + its 6 Mythic Engineering sub-agents) on its next slice per WAVE_PLAN.md. If a relaunch fails, do that slice's coordination yourself this tick and record the failure mode in the team's CAMPAIGN_STATE.md.
5. Update the Current State board (~/workspace/CURRENT_STATE.md + the current-state space Active Projects entry for Lifthrasir) whenever the banked count changes.

HARD BOUNDS: never touch any README.md (LIF-0001's "linked in README" step is a human-applied one-liner the team only proposes in its CAMPAIGN_STATE.md). Never invent results — counts come only from git and the test runner on purpleraider. Pause only at the Forge pause-lines (data destruction, irreversible infrastructure, cost, public publishing beyond this repo's own pushes, sending as Volmarr, exposing secrets, weakening security).

REPORTING: stay silent on ordinary ticks. Surface in the main chat ONLY when: a wave of nine slices banks (plain language first, verified banked count out of 64), the whole queue completes (then disable this keeper), or a genuine blocker needs Volmarr's word (name it plainly, once). Log tick outcomes in this goal's hidden_files run log, not in chat.
