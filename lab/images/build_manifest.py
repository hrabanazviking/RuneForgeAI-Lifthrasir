#!/usr/bin/env python3
"""LIF-0101: deterministically derive the build manifest for a lab image
recipe. Output depends ONLY on recipe.json + packages.txt: keys sorted,
packages sorted, fixed line endings, no timestamps, no randomness, no
host data. Two runs from clean state must be byte-identical (the slice
Done criterion applied to the recipe's derived artifacts)."""
import hashlib, json, sys
from pathlib import Path
def build_manifest(recipe_dir):
    recipe_dir = Path(recipe_dir)
    recipe = json.loads((recipe_dir / "recipe.json").read_text(encoding="utf-8"))
    packages = []
    for line in (recipe_dir / "packages.txt").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            packages.append(s)
    lines = ["lifthrasir-lab-manifest-v1", f"slice={recipe['slice']}", f"name={recipe['name']}", f"distro={recipe['distro']}", f"version={recipe['version']}", f"release_series={recipe['release_series']}", f"architecture={recipe['architecture']}", f"variant={recipe['variant']}", f"iso_filename={recipe['iso_filename']}", f"origin_url={recipe['origin_url']}", f"checksum_url={recipe['checksum_url']}", f"checksum_sha256={recipe['checksum_sha256']}", f"checksum_status={recipe['checksum_status']}", "packages:"]
    for pkg in sorted(packages):
        lines.append(f"  - {pkg}")
    body = "\n".join(lines) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body + f"manifest_sha256={digest}\n"
def main(argv):
    if len(argv) != 2:
        print("usage: build_manifest.py <recipe-dir>", file=sys.stderr)
        return 2
    sys.stdout.write(build_manifest(argv[1]))
    return 0
if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
