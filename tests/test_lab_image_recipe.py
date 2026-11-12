"""LIF-0101 pinned Kubuntu image recipe tests."""
import hashlib, json, re, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RDIR = REPO / "lab" / "images" / "kubuntu-24.04.5-amd64"
RECIPE = RDIR / "recipe.json"
VERIFY = REPO / "lab" / "images" / "verify_iso.py"
MANIFEST = REPO / "lab" / "images" / "build_manifest.py"
def _recipe():
    return json.loads(RECIPE.read_text(encoding="utf-8"))
def _run_verify(recipe_path, target):
    return subprocess.run([sys.executable, str(VERIFY), str(recipe_path), str(target)], capture_output=True, text=True)
def test_recipe_pins_present_and_wellformed():
    r = _recipe()
    assert r["distro"] == "Kubuntu"
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", r["version"])
    assert r["architecture"] == "amd64"
    assert r["iso_filename"].endswith("-desktop-amd64.iso")
    assert r["version"] in r["iso_filename"]
    assert r["origin_url"].startswith("https://cdimage.ubuntu.com/")
    assert r["origin_url"].endswith(r["iso_filename"])
    assert r["checksum_url"].startswith("https://cdimage.ubuntu.com/")
    assert re.fullmatch(r"[0-9a-f]{64}", r["checksum_sha256"])
    assert r["checksum_status"] == "retrieved-from-official-source"
def test_recipe_doc_matches_json_pin():
    r = _recipe()
    doc = (RDIR / "recipe.md").read_text(encoding="utf-8")
    assert r["checksum_sha256"] in doc
    assert r["origin_url"] in doc
    assert "LIF-0101" in doc
def test_lab_layout_is_recipes_not_images():
    readme = (REPO / "lab" / "README.md").read_text(encoding="utf-8").lower()
    assert "recipes, not images" in readme or "recipes" in readme
    for p in RDIR.rglob("*"):
        assert p.suffix.lower() not in (".iso", ".img", ".qcow2", ".vmdk"), f"large image committed: {p}"
def test_verify_accepts_correct_checksum_fixture(tmp_path):
    payload = b"lifthrasir fixture payload for LIF-0101\n"
    fixture = tmp_path / "fixture.bin"
    fixture.write_bytes(payload)
    recipe = _recipe()
    recipe["checksum_sha256"] = hashlib.sha256(payload).hexdigest()
    rpath = tmp_path / "recipe.json"
    rpath.write_text(json.dumps(recipe), encoding="utf-8")
    res = _run_verify(rpath, fixture)
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout
def test_verify_rejects_wrong_checksum_fixture(tmp_path):
    fixture = tmp_path / "fixture.bin"
    fixture.write_bytes(b"not the pinned iso\n")
    res = _run_verify(RECIPE, fixture)
    assert res.returncode != 0
    assert "REJECT" in res.stderr
def test_verify_rejects_unofficial_origin(tmp_path):
    payload = b"x"
    fixture = tmp_path / "f.bin"
    fixture.write_bytes(payload)
    recipe = _recipe()
    recipe["checksum_sha256"] = hashlib.sha256(payload).hexdigest()
    recipe["origin_url"] = "https://example.invalid/" + recipe["iso_filename"]
    rpath = tmp_path / "recipe.json"
    rpath.write_text(json.dumps(recipe), encoding="utf-8")
    res = _run_verify(rpath, fixture)
    assert res.returncode != 0
    assert "REJECT" in res.stderr
def test_verify_rejects_missing_file(tmp_path):
    res = _run_verify(RECIPE, tmp_path / "absent.iso")
    assert res.returncode != 0
def _manifest(recipe_dir):
    res = subprocess.run([sys.executable, str(MANIFEST), str(recipe_dir)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return res.stdout
def test_manifest_determinism_two_clean_builds(tmp_path):
    import shutil
    d1, d2 = tmp_path / "b1", tmp_path / "b2"
    for d in (d1, d2):
        d.mkdir()
        shutil.copy(RECIPE, d / "recipe.json")
        shutil.copy(RDIR / "packages.txt", d / "packages.txt")
    m1, m2 = _manifest(d1), _manifest(d2)
    assert m1 == m2
    assert hashlib.sha256(m1.encode()).hexdigest() == hashlib.sha256(m2.encode()).hexdigest()
    assert _recipe()["checksum_sha256"] in m1
    assert "qemu-guest-agent" in m1
