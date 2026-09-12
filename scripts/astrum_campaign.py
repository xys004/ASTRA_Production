#!/usr/bin/env python3
"""Register, inspect, and resume fail-closed experimental ASTRUM campaigns."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.experimental_astrum_campaign_adapter import (
    ClusterRpcGateway,
    ExperimentalAstrumCampaignAdapter,
    validate_scheduler_request,
)
from core.experimental_campaign_manager import (
    CampaignManifestError,
    ExperimentalCampaignStore,
    validate_manifest,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(manifest).encode("utf-8")).hexdigest()


def load_and_preflight(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignManifestError("cannot read manifest: %s" % exc) from exc
    normalized = validate_manifest(raw)
    scheduler_requests = {}
    for task in normalized["tasks"]:
        try:
            scheduler_requests[task["task_id"]] = validate_scheduler_request(task)
        except (TypeError, ValueError) as exc:
            raise CampaignManifestError(
                "invalid scheduler request for %s: %s" % (task["task_id"], exc)
            ) from exc
    return {
        "status": "PASS",
        "campaign_id": normalized["campaign_id"],
        "manifest_sha256": _manifest_sha256(normalized),
        "task_count": len(normalized["tasks"]),
        "max_concurrency": normalized["max_concurrency"],
        "scheduler_requests": scheduler_requests,
        "manifest": normalized,
    }


def _emit(value: Mapping[str, Any], stream: Any = None) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), file=stream)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="validate without writing or SSH")
    preflight.add_argument("--manifest", type=Path, required=True)

    register = subparsers.add_parser("register", help="persist an immutable manifest")
    register.add_argument("--manifest", type=Path, required=True)
    register.add_argument("--db", type=Path, required=True)

    status = subparsers.add_parser("status", help="print a persisted campaign snapshot")
    status.add_argument("--campaign-id", required=True)
    status.add_argument("--db", type=Path, required=True)

    resume = subparsers.add_parser("resume", help="reconcile and run pending tasks")
    resume.add_argument("--campaign-id", required=True)
    resume.add_argument("--db", type=Path, required=True)
    resume.add_argument(
        "--execute-remote",
        action="store_true",
        help="required acknowledgement that this command can submit through SSH",
    )
    resume.add_argument("--poll-interval-seconds", type=float, default=1.0)
    resume.add_argument("--max-poll-seconds", type=float, default=7 * 86400)
    return parser


def _open_existing_store(path: Path) -> ExperimentalCampaignStore:
    if not path.is_file():
        raise FileNotFoundError("campaign database does not exist: %s" % path)
    return ExperimentalCampaignStore(path)


def main(
    argv: Optional[Sequence[str]] = None,
    gateway_factory: Callable[[], Any] = ClusterRpcGateway,
) -> int:
    args = build_parser().parse_args(argv)
    store: Optional[ExperimentalCampaignStore] = None
    try:
        if args.command == "preflight":
            report = load_and_preflight(args.manifest)
            report.pop("manifest")
            _emit(report)
            return 0

        if args.command == "register":
            report = load_and_preflight(args.manifest)
            args.db.parent.mkdir(parents=True, exist_ok=True)
            store = ExperimentalCampaignStore(args.db)
            snapshot = store.register(report["manifest"])
            _emit(
                {
                    "status": "registered",
                    "campaign_id": snapshot["campaign_id"],
                    "manifest_sha256": snapshot["manifest_sha256"],
                    "task_count": len(snapshot["tasks"]),
                    "database": str(args.db.resolve()),
                }
            )
            return 0

        if args.command == "status":
            store = _open_existing_store(args.db)
            _emit(store.snapshot(args.campaign_id))
            return 0

        if not args.execute_remote:
            raise CampaignManifestError("resume requires explicit --execute-remote")
        store = _open_existing_store(args.db)
        manifest = store.manifest(args.campaign_id)
        # Re-run the complete payload preflight on immutable persisted bytes.
        normalized = validate_manifest(manifest)
        for task in normalized["tasks"]:
            validate_scheduler_request(task)
        adapter = ExperimentalAstrumCampaignAdapter(
            store,
            args.campaign_id,
            gateway_factory(),
            poll_interval_seconds=args.poll_interval_seconds,
            max_poll_seconds=args.max_poll_seconds,
        )
        _emit(adapter.run())
        return 0
    except (
        CampaignManifestError,
        FileNotFoundError,
        KeyError,
        RuntimeError,
        TimeoutError,
        ValueError,
    ) as exc:
        _emit(
            {"status": "ERROR", "error_type": type(exc).__name__, "error": str(exc)},
            stream=sys.stderr,
        )
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
