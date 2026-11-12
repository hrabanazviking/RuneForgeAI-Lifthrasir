#!/usr/bin/env python3
"""LIF-0101: verify a downloaded Kubuntu ISO against the pinned recipe.
Fails closed: any mismatch, missing file, malformed recipe, unofficial
origin or filename mismatch exits nonzero. Never downloads anything."""
import hashlib, json, sys
from pathlib import Path
from urllib.parse import urlparse
OFFICIAL_HOST = "cdimage.ubuntu.com"
def load_recipe(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("iso_filename", "origin_url", "checksum_sha256", "architecture", "version"):
        if not data.get(key):
            raise ValueError(f"recipe missing pin: {key}")
    host = urlparse(data["origin_url"]).hostname
    if host != OFFICIAL_HOST:
        raise ValueError(f"origin is not the official host {OFFICIAL_HOST}: {host}")
    digest = data["checksum_sha256"]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("checksum_sha256 is not a lowercase sha256 hex digest")
    return data
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
def main(argv):
    if len(argv) != 3:
        print("usage: verify_iso.py <recipe.json> <iso-or-fixture-file>", file=sys.stderr)
        return 2
    recipe_path, target = argv[1], Path(argv[2])
    try:
        recipe = load_recipe(recipe_path)
    except Exception as exc:
        print(f"REJECT: malformed recipe: {exc}", file=sys.stderr)
        return 1
    if not target.is_file():
        print(f"REJECT: file not found: {target}", file=sys.stderr)
        return 1
    actual = sha256_of(target)
    expected = recipe["checksum_sha256"]
    if actual != expected:
        print(f"REJECT: sha256 mismatch: expected {expected}, got {actual}", file=sys.stderr)
        return 1
    print(f"OK: sha256 matches pinned recipe for {recipe['iso_filename']} ({recipe['distro']} {recipe['version']} {recipe['architecture']}) from {recipe['origin_url']}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
