from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.benchmarks import get_benchmark, load_benchmarks


def main() -> int:
    parser = argparse.ArgumentParser(description="List ASTRUM benchmark cases or print one benchmark prompt.")
    parser.add_argument("--prompt", help="Benchmark id to print as an ASTRUM prompt.")
    args = parser.parse_args()

    if args.prompt:
        print(get_benchmark(args.prompt).to_prompt())
        return 0

    benchmarks = load_benchmarks()
    print(f"ASTRUM benchmarks: {len(benchmarks)}")
    for benchmark in benchmarks:
        print(f"- {benchmark.id:42} {benchmark.domain:22} expected={benchmark.expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
