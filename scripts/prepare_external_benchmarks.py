"""Clone and verify pinned external benchmark sources in ASTRA's ignored cache."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.external_benchmarks import audit_external_sources, cache_root, load_registry


def _run(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, text=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")


def download_missing() -> None:
    registry = load_registry()
    root = cache_root(registry)
    root.mkdir(parents=True, exist_ok=True)
    for dataset in registry["datasets"].values():
        for source in dataset["sources"]:
            target = root / source["name"]
            if target.exists():
                continue
            _run(["git", "clone", "--filter=blob:none", source["url"], str(target)])
            _run(["git", "fetch", "--depth", "1", "origin", source["commit"]], target)
            _run(["git", "checkout", "--detach", source["commit"]], target)


def download_scicode_tests() -> None:
    registry = load_registry()
    target = cache_root(registry) / "SciCode" / "eval" / "data" / "test_data.h5"
    if target.exists():
        print(f"SciCode numeric targets already present: {target}")
        return
    try:
        import gdown
    except ImportError as exc:
        raise RuntimeError(
            "gdown is required; install ASTRA's requirements before downloading "
            "the SciCode numeric targets"
        ) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    url = registry["datasets"]["scicode"]["numeric_test_folder"]
    downloaded = gdown.download_folder(
        url=url,
        output=str(target.parent),
        quiet=False,
        remaining_ok=True,
    )
    if not downloaded or not target.exists():
        raise RuntimeError(
            "SciCode download completed without the expected test_data.h5 target"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare pinned external benchmarks")
    parser.add_argument("--download", action="store_true", help="Clone missing sources")
    parser.add_argument(
        "--download-scicode-tests",
        action="store_true",
        help="Download SciCode's official numeric HDF5 test targets",
    )
    args = parser.parse_args()
    if args.download:
        download_missing()
    if args.download_scicode_tests:
        download_scicode_tests()
    audit = audit_external_sources()
    print(json.dumps(audit, indent=2))
    if not audit["ok"]:
        print(
            "External cache is incomplete or not at the pinned commits. Existing "
            "directories were not overwritten.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
