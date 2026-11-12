# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0603 tests: memory/CPU quotas, time limits and cancellation.

Scope: the OS-level enforcement layer in src/lifthrasir/quotas.py,
exercised ONLY against this project's own fixture child processes
(tests/fixtures/lif0603/worker.py, spawned through the module under
test) and a fixture cgroup directory under tmp_path.  No test
signals, limits or cancels any process the module did not spawn:
the one foreign process spawned here is deliberately left alone by
every quota API and the test asserts it survives (then cleans it up
itself).  No real cgroup is written; the cgroup adapter is tested
only against its fixture tree and its refusal of real system roots.

Pinned behaviour: quota validation is fail-closed; rlimits provably
land in the child (the child reads its own limits back); memory and
CPU breaches are classified quota_exceeded by mechanism (RLIMIT_AS
MemoryError / SIGXCPU); the wall limit and CancellationToken
cancellation terminate only the module's own child, escalating to
SIGKILL when SIGTERM is ignored; the LIF-0601 provider bridge
refuses over-quota requests pre-flight and hard-walls slow
providers; enforcement is rlimit-level only and the module claims
no real cgroup, GPU or RSS-exact enforcement.
"""
import ast
import inspect
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import modelprovider as mp  # noqa: E402
from lifthrasir import quotas as q  # noqa: E402

WORKER = REPO / "tests" / "fixtures" / "lif0603" / "worker.py"
PY = sys.executable
MB = 1024 * 1024


def argv(*args):
    return [PY, str(WORKER), *[str(a) for a in args]]


# --- quota validation: fail closed, never trimmed --------------------------

def test_quota_defaults_and_dict_roundtrip():
    quota = q.ResourceQuota(memory_bytes=256 * MB, cpu_seconds=5)
    assert quota.wall_seconds == 30.0
    assert q.quota_from_dict(quota.to_dict()) == quota
    assert q.ResourceQuota.from_dict({"wall_seconds": 5}) == \
        q.ResourceQuota(wall_seconds=5.0)


def test_quota_refuses_out_of_ceiling_values():
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(memory_bytes=1024)  # below the honest floor
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(memory_bytes=q.MAX_MEMORY_BYTES + 1)
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(cpu_seconds=0)
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(cpu_seconds=q.MAX_CPU_SECONDS + 1)
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(wall_seconds=0)
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(wall_seconds=q.MAX_WALL_SECONDS + 1)
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(cpu_fraction=1.5)
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(max_output_bytes=10)
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota(memory_bytes=True)  # bool is not an int budget


def test_quota_dict_refuses_unknown_fields_and_wrong_schema():
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota.from_dict({"gpu_bytes": 5})
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota.from_dict({"schema": "other/9"})
    with pytest.raises(q.MalformedQuotaError):
        q.ResourceQuota.from_dict("not-a-dict")


# --- rlimits provably land in the child ------------------------------------

def test_child_reports_the_rlimits_the_quota_set():
    quota = q.ResourceQuota(memory_bytes=256 * MB, cpu_seconds=7,
                            wall_seconds=10)
    result = q.run_guarded(argv("report-limits"), quota)
    assert result.outcome == "completed"
    seen = json.loads(result.stdout)
    assert seen["rlimit_as"] == [256 * MB, 256 * MB]
    assert seen["rlimit_cpu"] == [7, 8]  # soft, hard = soft + 1
    assert seen["rlimit_nofile"] == [64, 64]
    assert seen["rlimit_core"] == [0, 0]
    assert seen["pid"] == result.child_pid != _pid()


def _pid():
    import os
    return os.getpid()


def test_child_without_memory_quota_reports_unlimited_as():
    result = q.run_guarded(argv("report-limits"),
                           q.ResourceQuota(wall_seconds=10))
    seen = json.loads(result.stdout)
    assert seen["rlimit_as"][0] == -1  # RLIM_INFINITY: no quota set


# --- basic supervised runs ---------------------------------------------------

def test_echo_completes_in_a_separate_process():
    result = q.run_guarded(argv("echo", "hello-quota"),
                           q.ResourceQuota(wall_seconds=10))
    assert result.outcome == "completed"
    assert result.stdout.strip() == "hello-quota"
    assert result.child_pid != _pid() and result.child_pid > 0
    assert result.exit_code == 0 and result.signal_number is None
    assert result.wall_s < 10


def test_short_sleep_within_wall_completes():
    result = q.run_guarded(argv("sleep", 0.2),
                           q.ResourceQuota(wall_seconds=10))
    assert result.outcome == "completed"
    assert result.stdout.strip() == "slept"


def test_crash_is_a_plain_failure_and_the_caller_survives():
    quota = q.ResourceQuota(wall_seconds=10)
    crashed = q.run_guarded(argv("crash"), quota)
    assert crashed.outcome == "failed" and crashed.exit_code == 3
    again = q.run_guarded(argv("echo", "still-alive"), quota)
    assert again.outcome == "completed"


def test_shell_string_argv_is_refused():
    with pytest.raises(q.QuotaRefusalError):
        q.run_guarded("echo hi", q.ResourceQuota())
    with pytest.raises(q.QuotaRefusalError):
        q.run_guarded([], q.ResourceQuota())


def test_output_cap_truncates_but_the_child_still_completes():
    quota = q.ResourceQuota(wall_seconds=10, max_output_bytes=4096)
    result = q.run_guarded(argv("spew", 200_000), quota)
    assert result.outcome == "completed"
    assert result.output_truncated is True
    assert len(result.stdout.encode()) <= 4096


# --- memory quota --------------------------------------------------------------

def test_memory_quota_breach_is_classified_by_mechanism():
    quota = q.ResourceQuota(memory_bytes=256 * MB, wall_seconds=20)
    result = q.run_guarded(argv("allocate", 500), quota)
    assert result.outcome == "quota_exceeded"
    assert "memory" in result.detail
    assert "MemoryError" in result.stderr


def test_allocation_within_memory_quota_completes():
    quota = q.ResourceQuota(memory_bytes=1024 * MB, wall_seconds=20)
    result = q.run_guarded(argv("allocate", 50), quota)
    assert result.outcome == "completed"
    assert result.stdout.strip() == f"ALLOCATED {50 * MB}"


# --- CPU quota -------------------------------------------------------------------

def test_cpu_quota_kills_a_busy_child_with_sigxcpu():
    quota = q.ResourceQuota(cpu_seconds=1, wall_seconds=30)
    started = time.monotonic()
    result = q.run_guarded(argv("spin", 30), quota)
    wall = time.monotonic() - started
    assert result.outcome == "quota_exceeded"
    assert "cpu" in result.detail
    assert result.signal_number in (24, 9)  # SIGXCPU, or SIGKILL hard cap
    assert wall < 15  # nowhere near the child's 30s spin or the wall
    assert result.cpu_s >= 0.8


def test_spin_within_cpu_quota_completes():
    quota = q.ResourceQuota(cpu_seconds=10, wall_seconds=20)
    result = q.run_guarded(argv("spin", 0.3), quota)
    assert result.outcome == "completed"
    assert result.stdout.strip() == "spun"


# --- hard wall limit ----------------------------------------------------------------

def test_wall_limit_terminates_a_sleeping_child():
    quota = q.ResourceQuota(wall_seconds=0.5)
    started = time.monotonic()
    result = q.run_guarded(argv("sleep", 30), quota)
    wall = time.monotonic() - started
    assert result.outcome == "timed_out"
    assert wall < 8
    assert _process_gone(result.child_pid)


def _process_gone(pid):
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    # A zombie still answers kill(pid, 0); check /proc state instead.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return stat.rsplit(")", 1)[1].split()[0] == "Z"
    except OSError:
        return True


# --- cancellation ---------------------------------------------------------------------

def test_cancellation_token_stops_running_work():
    token = mp.CancellationToken()
    quota = q.ResourceQuota(wall_seconds=60)
    proc = q.start_guarded(argv("sleep", 30), quota, cancel_token=token)
    timer = threading.Timer(0.3, token.cancel)
    timer.start()
    result = proc.wait()
    timer.cancel()
    assert result.outcome == "cancelled"
    assert result.wall_s < 8
    assert _process_gone(result.child_pid)


def test_direct_cancel_escalates_when_the_child_ignores_sigterm():
    quota = q.ResourceQuota(wall_seconds=60, term_grace_s=0.5)
    proc = q.start_guarded(argv("sleep", 30, "--ignore-term"), quota)
    time.sleep(0.3)
    assert proc.cancel("test cancellation") is True
    result = proc.wait()
    assert result.outcome == "cancelled"
    assert result.escalated_to_kill is True
    assert _process_gone(result.child_pid)
    assert proc.cancel("again") is False  # already reaped: no-op


def test_foreign_process_is_never_touched():
    # A process this module did NOT spawn: no quota API can aim at
    # it (GuardedProcess holds only its own Popen handle; nothing in
    # the module accepts a bare pid to signal).
    foreign = subprocess.Popen(argv("sleep", 30),
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        result = q.run_guarded(argv("sleep", 30),
                               q.ResourceQuota(wall_seconds=0.4))
        assert result.outcome == "timed_out"
        assert foreign.poll() is None  # untouched, still sleeping
        for name, fn in vars(q).items():
            if callable(fn) and not name.startswith("_"):
                try:
                    params = list(inspect.signature(fn).parameters)
                except (TypeError, ValueError):
                    continue  # builtins without signatures: not an API
                assert "pid" not in params, name
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)


# --- cgroup adapter interface (fixture level only) -----------------------------

def test_unavailable_adapter_is_the_honest_default():
    adapter = q.UnavailableCgroupAdapter()
    assert adapter.available() is False
    with pytest.raises(q.CgroupUnavailableError):
        adapter.apply("agents", q.ResourceQuota(memory_bytes=64 * MB))


def test_cgroup_value_translation_is_pure_and_exact():
    values = q.cgroup_values(q.ResourceQuota(
        memory_bytes=256 * MB, cpu_fraction=0.5, max_pids=64))
    assert values == {"memory.max": str(256 * MB),
                      "cpu.max": "50000 100000", "pids.max": "64"}
    open_values = q.cgroup_values(q.ResourceQuota())
    assert open_values == {"memory.max": "max",
                           "cpu.max": "max 100000", "pids.max": "max"}


def test_fixture_adapter_writes_and_reads_back(tmp_path):
    adapter = q.FixtureCgroupAdapter(tmp_path / "cg")
    assert adapter.available() is True
    receipt = adapter.apply("agents", q.ResourceQuota(
        memory_bytes=128 * MB, cpu_fraction=0.25, max_pids=32))
    assert receipt.adapter == "fixture" and receipt.group == "agents"
    group = tmp_path / "cg" / "agents"
    assert (group / "memory.max").read_text().strip() == str(128 * MB)
    assert (group / "cpu.max").read_text().strip() == "25000 100000"
    assert (group / "pids.max").read_text().strip() == "32"
    assert receipt.values["memory.max"] == str(128 * MB)


def test_fixture_adapter_refuses_real_system_roots():
    for root in ("/sys/fs/cgroup", "/sys", "/proc/self", "/"):
        with pytest.raises(q.CgroupPathError):
            q.FixtureCgroupAdapter(root)
    with pytest.raises(q.CgroupPathError):
        q.FixtureCgroupAdapter("/tmp/x").apply(
            "../escape", q.ResourceQuota())


# --- provider bridge (LIF-0601) ---------------------------------------------------

def make_request(**overrides):
    kwargs = dict(task_id="task-quota", prompt="Explain the failure.",
                  deadline_s=10.0, max_input_tokens=100,
                  max_output_tokens=50)
    kwargs.update(overrides)
    return mp.ModelRequest(**kwargs)


def test_provider_within_quota_completes_via_run_request():
    quota = q.ResourceQuota(wall_seconds=20, max_total_tokens=1000)
    result = q.run_model_with_quotas(mp.MockModelProvider(),
                                     make_request(), quota)
    assert result.outcome == "completed"
    assert result.performed_inference is True


def test_over_deadline_request_is_refused_before_any_provider_call():
    calls = []

    class CountingProvider:
        name = "counting"

        def generate(self, request, cancel_token=None):
            calls.append(request.task_id)
            return mp.MockModelProvider().generate(request, cancel_token)

    quota = q.ResourceQuota(wall_seconds=5)
    with pytest.raises(q.QuotaRefusalError):
        q.run_model_with_quotas(CountingProvider(),
                                make_request(deadline_s=30.0), quota)
    assert calls == []  # the provider was never called


def test_over_token_budget_request_is_refused_pre_flight():
    quota = q.ResourceQuota(wall_seconds=20, max_total_tokens=100)
    with pytest.raises(q.QuotaRefusalError):
        q.check_model_request(
            make_request(max_input_tokens=90, max_output_tokens=50),
            quota)


class _SlowCooperativeProvider:
    name = "slow-cooperative"

    def generate(self, request, cancel_token=None):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            time.sleep(0.02)
        return mp.MockModelProvider().generate(request, cancel_token)


class _SlowDeafProvider:
    name = "slow-deaf"

    def generate(self, request, cancel_token=None):
        time.sleep(30)  # never polls the token
        return mp.MockModelProvider().generate(request, cancel_token)


def test_hard_wall_cancels_a_cooperative_provider():
    quota = q.ResourceQuota(wall_seconds=0.5, term_grace_s=1.0)
    started = time.monotonic()
    result = q.run_model_with_quotas(
        _SlowCooperativeProvider(), make_request(deadline_s=0.5), quota)
    assert time.monotonic() - started < 8
    assert result.outcome == "cancelled"


def test_hard_wall_abandons_an_uncooperative_provider_honestly():
    quota = q.ResourceQuota(wall_seconds=0.5, term_grace_s=0.5)
    started = time.monotonic()
    result = q.run_model_with_quotas(
        _SlowDeafProvider(), make_request(deadline_s=0.5), quota)
    wall = time.monotonic() - started
    assert wall < 8  # returned; did not hang for the provider's 30s
    assert result.outcome == "failed"
    assert "did not honour cancellation" in result.error


# --- honesty guards -----------------------------------------------------------------

def test_module_source_has_no_network_or_real_cgroup_writes():
    source = (REPO / "src" / "lifthrasir" / "quotas.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not ({"socket", "urllib", "http", "requests"} & imported)
    # The only /sys/fs/cgroup mention is inside refusal/doc text;
    # the module never opens it for writing.
    assert 'open("/sys' not in source and "open('/sys" not in source
    # killpg is the only signal call, and it is aimed at the Guarded
    # process's own group; there is no bare os.kill(pid) surface.
    assert "os.killpg(self._proc.pid" in source
    assert "os.kill(" not in source.replace("os.killpg(", "")
