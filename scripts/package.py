"""Export tracked plugin source only, excluding local books, designs and runtime."""

import argparse
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / "plugin.json").read_text(encoding="utf-8"))["version"]
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise RuntimeError("Invalid plugin version.")
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"], check=True, capture_output=True, text=True
    )
    if dirty.stdout.strip():
        raise RuntimeError("Commit intended plugin changes before exporting; ignored/private files are never copied.")
    output = (args.output_directory or root / ".runtime" / "dist").absolute()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"orcad-placement-{version}.zip"
    if archive.exists():
        raise FileExistsError("Archive exists; choose another output directory.")
    subprocess.run(
        ["git", "-C", str(root), "archive", "--format=zip", f"--output={archive}", "HEAD"], check=True
    )
    print(archive)
    print("Tracked source only. No ignored books, designs, captures or environments were copied.")


if __name__ == "__main__":
    main()
