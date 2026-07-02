"""Fetch the full VED dynamic dataset into ``data/ved/full/`` (gitignored).

The repo ships a small real sample (``data/ved/ved_sample.csv`` — see
``data/ved/README.md`` for selection criteria and attribution); this script pulls the
complete archives (~180 MB compressed, Apache-2.0 licensed) for larger replays:

    pip install py7zr requests
    python scripts/fetch_ved.py            # both parts
    python scripts/fetch_ved.py --part 1   # just Part 1

Then point the replay producer at any extracted weekly CSV:

    PYTHONPATH=src python -m replay.producer_replay \
        --source-csv data/ved/full/VED_171101_week.csv --out-dir data/temp/replay
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE_URL = "https://github.com/gsoh/VED/raw/master/Data"
PARTS = {1: "VED_DynamicData_Part1.7z", 2: "VED_DynamicData_Part2.7z"}
DEST = Path(__file__).resolve().parents[1] / "data" / "ved" / "full"


def fetch(part: int) -> None:
    try:
        import py7zr
    except ImportError:
        sys.exit("py7zr is required: pip install py7zr")

    DEST.mkdir(parents=True, exist_ok=True)
    name = PARTS[part]
    archive = DEST / name
    if not archive.exists():
        print(f"Downloading {name} (this is ~80–95 MB)...")
        urllib.request.urlretrieve(f"{BASE_URL}/{name}", archive)
    print(f"Extracting {name} → {DEST}/")
    with py7zr.SevenZipFile(archive) as z:
        z.extractall(path=DEST)
    archive.unlink()
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the full VED dynamic dataset")
    parser.add_argument("--part", type=int, choices=(1, 2), default=None, help="Fetch one part only")
    args = parser.parse_args()
    for part in [args.part] if args.part else sorted(PARTS):
        fetch(part)


if __name__ == "__main__":
    main()
