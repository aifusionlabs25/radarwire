from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a fresh local-capture scratch config/data dir for one SMTP capture test.")
    parser.add_argument("--source-config", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scratch-root", default=".radar-data", type=Path)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1025)
    parser.add_argument("--report-url", default=None)
    return parser.parse_args(argv)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _as_posix(path: Path) -> str:
    return path.as_posix()


def prepare_scratch(source_config: Path, run_id: str, scratch_root: Path, timestamp: str | None, host: str, port: int, report_url: str | None = None) -> dict:
    cfg = yaml.safe_load(source_config.read_text(encoding="utf-8"))
    source_data_dir = Path(cfg["data_dir"])
    source_report_dir = source_data_dir / "reports" / run_id
    if not source_report_dir.exists():
        raise FileNotFoundError(f"missing report artifact directory: {source_report_dir}")
    required = ["digest.json", "digest.html", "digest.txt", "run-summary.json"]
    if cfg.get("email", {}).get("attach_markdown", False):
        required.append("digest.md")
    missing = [name for name in required if not (source_report_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing report artifact(s): {', '.join(missing)}")

    stamp = timestamp or _timestamp()
    source_stem = source_data_dir.name or "local-capture"
    scratch_data_dir = scratch_root / f"{source_stem}-{stamp}"
    scratch_config_path = source_config.with_name(f"{source_config.stem}-{stamp}{source_config.suffix}")
    if scratch_data_dir.exists():
        raise FileExistsError(f"scratch data dir already exists: {scratch_data_dir}")
    if scratch_config_path.exists():
        raise FileExistsError(f"scratch config already exists: {scratch_config_path}")

    scratch_report_dir = scratch_data_dir / "reports" / run_id
    shutil.copytree(source_report_dir, scratch_report_dir)
    (scratch_data_dir / "smtp-capture").mkdir(parents=True, exist_ok=True)

    scratch_cfg = dict(cfg)
    scratch_cfg["workspace_id"] = f"{cfg.get('workspace_id', 'local-capture')}-{stamp}"
    scratch_cfg["data_dir"] = _as_posix(scratch_data_dir)
    scratch_cfg["database_url"] = "sqlite:///" + _as_posix(scratch_data_dir / "radar.db")
    scratch_cfg["dry_run"] = False
    scratch_cfg.setdefault("email", {})["enabled"] = True
    scratch_cfg["email"]["preview_only"] = False
    scratch_cfg["email"]["smtp_host"] = host
    scratch_cfg["email"]["smtp_port"] = port
    scratch_cfg["email"]["use_tls"] = False
    scratch_cfg["email"]["attach_markdown"] = False
    if report_url:
        scratch_cfg["email"]["report_url"] = report_url
    scratch_config_path.write_text(yaml.safe_dump(scratch_cfg, sort_keys=False), encoding="utf-8")

    return {
        "status": "prepared",
        "source_config": str(source_config),
        "config_path": str(scratch_config_path),
        "data_dir": str(scratch_data_dir),
        "database_url_redacted": scratch_cfg["database_url"],
        "workspace_id": scratch_cfg["workspace_id"],
        "run_id": run_id,
        "report_dir": str(scratch_report_dir),
        "capture_output_dir": str(scratch_data_dir / "smtp-capture"),
        "smtp_host": host,
        "smtp_port": port,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = prepare_scratch(args.source_config, args.run_id, args.scratch_root, args.timestamp, args.host, args.port, args.report_url)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
