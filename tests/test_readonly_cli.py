# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0205 tests: read-only CLI over the committed fixture dataset."""
import io
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from ui.heimdall_cli import main  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "lif0205" / "fixture.json"


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_list_contains_fixture_incidents():
    code, out, _ = run_cli("incidents", "list")
    assert code == 0
    assert "inc-2026-001" in out and "inc-2026-002" in out
    assert "total: 2 incident(s)" in out


def test_show_known_incident_details():
    code, out, _ = run_cli("incidents", "show", "inc-2026-001")
    assert code == 0
    rec = json.loads(out)
    assert rec["severity"] == "medium"
    assert "demo.service" in rec["summary"]


def test_show_unknown_id_named_error_no_crash():
    code, out, err = run_cli("incidents", "show", "inc-9999-zzz")
    assert code == 2
    assert "unknown incident id: inc-9999-zzz" in err
    assert out == ""


def test_permissions_match_fixture_collectors():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    code, out, _ = run_cli("sensors", "permissions")
    assert code == 0
    for sensor in data["sensors"]:
        assert sensor["sensor_id"] in out
        assert sensor["risk_tier"] in out
    assert "observation only" in out


def test_corrupted_record_is_reported_not_shown(tmp_path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del data["incidents"][0]["severity"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    code, _, err = run_cli("--data", str(bad), "incidents", "list")
    assert code == 2
    assert "corrupted" in err and "severity" in err


def test_cli_source_has_no_mutating_operations():
    source = (REPO / "ui" / "heimdall_cli.py").read_text(encoding="utf-8")
    for token in [".write_text(", "os.remove", "os.unlink", "shutil",
                  "subprocess", "os.system", "mode=\"w\"", "mode='w'",
                  "open(", ".rename("]:
        assert token not in source, f"mutating token present: {token}"
    assert "read_text" in source


def test_module_entrypoint_exit_codes():
    ok = subprocess.run(
        [sys.executable, "-m", "ui.heimdall_cli", "incidents", "list"],
        cwd=REPO, capture_output=True, text=True)
    assert ok.returncode == 0 and "inc-2026-001" in ok.stdout
    bad = subprocess.run(
        [sys.executable, "-m", "ui.heimdall_cli", "incidents", "show",
         "inc-nope"], cwd=REPO, capture_output=True, text=True)
    assert bad.returncode == 2 and "unknown incident id" in bad.stderr
