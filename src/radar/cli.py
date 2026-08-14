from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich import print

from .config import AppConfig, load_config
from .content_studio import BriefSet, ContentStudioError, generate_content_studio, generate_content_studio_drafts
from .editorial_review import EditorialReviewError, build_editorial_review_kit, validate_editorial_review_kit
from .emailer import deliver_existing_report, delivery_preflight, load_existing_report
from .hermes_install import install as install_hermes
from .models import make_session_factory
from .pipeline import backup as do_backup
from .pipeline import restore as do_restore
from .pipeline import run_pipeline, state_audit as do_state_audit, status as do_status
from .repository import RadarRepository
from .source_check import check_sources

app = typer.Typer()


def cfg(path: str | None, *, ensure_dirs: bool = True):
    return load_config(path, ensure_dirs=ensure_dirs)


def fixture_config(base_cfg: AppConfig, fixture_data_dir: str | None = None) -> AppConfig:
    fixture_dir = Path(fixture_data_dir or os.getenv("RADAR_FIXTURE_DATA_DIR") or (base_cfg.data_dir / "fixture"))
    fixture_db = fixture_dir / "radar.fixture.db"
    isolated = base_cfg.model_copy(
        update={
            "data_dir": fixture_dir,
            "database_url": "sqlite:///" + str(fixture_db).replace("\\", "/"),
        },
        deep=True,
    )
    isolated.ensure_dirs()
    return isolated


def _should_fail_for_warnings(summary: dict, fail_on_source_errors: bool) -> bool:
    return bool(fail_on_source_errors and summary.get("source_error_count", 0) > 0)


@app.command()
def doctor(config: str = "config.v0.2.example.yaml"):
    c = cfg(config)
    bad = c.email.invalid_addresses()
    print(
        {
            "ok": not bad,
            "invalid_email_addresses": bad,
            "dry_run": c.dry_run,
            "hermes_command": f"{c.hermes.command} {c.hermes.profile_flag} {c.hermes.profile} {c.hermes.skill_flag} {c.hermes.skill} {c.hermes.one_shot_flag} <instruction>",
        }
    )


@app.command()
def scan(
    config: str = "config.v0.2.example.yaml",
    baseline: bool = False,
    no_hermes: bool = False,
    fixture: bool = False,
    fixture_data_dir: str | None = None,
    fail_on_source_errors: bool = False,
):
    c = cfg(config)
    if fixture:
        c = fixture_config(c, fixture_data_dir=fixture_data_dir)
    summary = run_pipeline(c, baseline=baseline, use_hermes=not no_hermes, fixture=fixture)
    typer.echo(json.dumps(summary, indent=2))
    if summary.get("status") == "failed":
        raise typer.Exit(1)
    if _should_fail_for_warnings(summary, fail_on_source_errors):
        raise typer.Exit(2)


@app.command()
def status(config: str = "config.v0.2.example.yaml"):
    typer.echo(json.dumps(do_status(cfg(config)), indent=2))


@app.command("health-json")
def health_json(config: str = "config.v0.2.example.yaml"):
    typer.echo(json.dumps({"status": "ok", **do_status(cfg(config))}, indent=2))


@app.command("source-check")
def source_check(config: str = "config.pilot.local.yaml"):
    typer.echo(json.dumps(check_sources(cfg(config, ensure_dirs=False)), indent=2))


@app.command("state-audit")
def state_audit(config: str = "config.v0.2.example.yaml"):
    typer.echo(json.dumps(do_state_audit(cfg(config)), indent=2))


@app.command("publish-preflight")
def publish_preflight(config: str = "config.pilot.local.yaml"):
    c = cfg(config, ensure_dirs=False)
    safe = c.dry_run and not c.email.enabled and c.email.preview_only
    payload = {
        "ok": safe,
        "dry_run": c.dry_run,
        "email_enabled": c.email.enabled,
        "email_preview_only": c.email.preview_only,
        "hermes_enabled": c.hermes.enabled,
        "source_count": len(c.sources),
    }
    typer.echo(json.dumps(payload, indent=2))
    if not safe:
        raise typer.Exit(2)


@app.command()
def backup(config: str = "config.v0.2.example.yaml"):
    print({"backup": str(do_backup(cfg(config)))})


@app.command()
def restore(archive: str, config: str = "config.v0.2.example.yaml"):
    do_restore(cfg(config), Path(archive))
    print({"restored": archive})


@app.command("report-list")
def report_list(config: str = "config.v0.2.example.yaml"):
    c = cfg(config)
    reports = sorted((c.data_dir / "reports").glob("*"))
    print([str(p) for p in reports])


@app.command("export-report-site")
def export_report_site(
    config: str = "config.v0.2.example.yaml",
    run_id: str = typer.Option(..., "--run-id", help="Existing run/report ID to export"),
    output_dir: str = typer.Option(".radar-data/site-export", "--output-dir", help="Static site export root"),
    base_url: str | None = typer.Option(None, "--base-url", help="Optional hosted base URL for suggested report link"),
    route_name: str | None = typer.Option(None, "--route-name", help="Stable public route segment; defaults to the run ID"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow replacing files in an existing export folder"),
):
    c = cfg(config)
    report_dir, digest = load_existing_report(c, run_id)
    export_root = Path(output_dir)
    route_segment = route_name or run_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", route_segment):
        raise typer.BadParameter("Route name must be a single safe URL segment containing only letters, numbers, dot, underscore, or hyphen.")
    destination = export_root / "reports" / route_segment
    if destination.exists() and any(destination.iterdir()) and not overwrite:
        typer.echo(
            json.dumps(
                {
                    "status": "refused_existing_export",
                    "destination": str(destination),
                    "hint": "Pass --overwrite only after reviewing the existing export.",
                },
                indent=2,
            )
        )
        raise typer.Exit(2)
    destination.mkdir(parents=True, exist_ok=True)
    copies = {
        "digest.html": "index.html",
        "digest.json": "digest.json",
        "digest.md": "digest.md",
        "digest.txt": "digest.txt",
        "digest_email.html": "digest_email.html",
        "digest_email.txt": "digest_email.txt",
        "run-summary.json": "run-summary.json",
    }
    copied = []
    for source_name, target_name in copies.items():
        source = report_dir / source_name
        if source.exists():
            shutil.copy2(source, destination / target_name)
            copied.append(target_name)
    route = f"/reports/{route_segment}/"
    hosted_url = None
    if base_url:
        hosted_url = base_url.rstrip("/") + route
    metadata = {
        "status": "exported",
        "run_id": run_id,
        "route_name": route_segment,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "article_count": digest.get("article_count", 0),
        "source_error_count": digest.get("source_error_count", 0),
        "source_report_dir": f"reports/{run_id}",
        "destination": route,
        "route": route,
        "hosted_url": hosted_url,
        "files": copied + ["report-site.json"],
        "sends_email": False,
        "deploys": False,
    }
    (destination / "report-site.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    typer.echo(json.dumps(metadata, indent=2))


@app.command("deliver-report")
def deliver_report(
    config: str = "config.v0.2.example.yaml",
    run_id: str = typer.Option(..., "--run-id", help="Existing run/report ID to deliver"),
    send: bool = typer.Option(False, "--send", help="Actually send live email when live config gates pass"),
):
    c = cfg(config)
    report_dir, digest = load_existing_report(c, run_id)
    preflight = delivery_preflight(c, run_id, report_dir, digest)
    payload = {"preflight": preflight, "send_requested": send}
    live_config = (not c.dry_run) and c.email.enabled and (not c.email.preview_only)
    if live_config and not send:
        payload["refused"] = "Refusing live-send-capable config without --send"
        typer.echo(json.dumps(payload, indent=2))
        raise typer.Exit(2)
    Session, _ = make_session_factory(c.database_url)
    with Session.begin() as s:
        repo = RadarRepository(s, c.workspace_id)
        result = deliver_existing_report(repo, c, run_id, send=send)
    typer.echo(json.dumps(result, indent=2))


@app.command("content-studio")
def content_studio(
    config: str = "config.v0.2.example.yaml",
    run_id: str = typer.Option(..., "--run-id", help="Existing clean report ID to use as research"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="New review-artifact directory"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow replacing existing Content Studio files"),
):
    c = cfg(config, ensure_dirs=False)
    report_dir, digest = load_existing_report(c, run_id)
    destination = Path(output_dir) if output_dir else report_dir / "content-studio"
    try:
        result = generate_content_studio(c, run_id, digest, destination, overwrite=overwrite)
    except ContentStudioError as exc:
        typer.echo(json.dumps({"status": "refused", "error": str(exc)}, indent=2))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command("content-studio-expand")
def content_studio_expand(
    config: str = "config.v0.2.example.yaml",
    run_id: str = typer.Option(..., "--run-id", help="Existing clean report ID to use as research"),
    briefs_path: str = typer.Option(..., "--briefs", help="Existing approved Content Studio briefs.json"),
    ranks: str = typer.Option("1,2,3", "--ranks", help="Comma-separated brief ranks to draft"),
    output_dir: str = typer.Option(..., "--output-dir", help="New draft-artifact directory"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow replacing existing draft-set files"),
):
    c = cfg(config, ensure_dirs=False)
    _, digest = load_existing_report(c, run_id)
    try:
        requested = [int(item.strip()) for item in ranks.split(",") if item.strip()]
        brief_set = BriefSet.model_validate_json(Path(briefs_path).read_text(encoding="utf-8"))
        result = generate_content_studio_drafts(
            c,
            run_id,
            digest,
            brief_set,
            Path(output_dir),
            ranks=requested,
            overwrite=overwrite,
        )
    except (ContentStudioError, OSError, ValueError) as exc:
        typer.echo(json.dumps({"status": "refused", "error": str(exc)}, indent=2))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command("editorial-review-kit")
def editorial_review_kit(
    manifest: str = typer.Option(..., "--manifest", help="Review-kit article manifest JSON"),
    output_dir: str = typer.Option(..., "--output-dir", help="Local static review-kit directory"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow replacing generated review HTML/CSS/JS"),
):
    try:
        result = build_editorial_review_kit(Path(manifest), Path(output_dir), overwrite=overwrite)
    except (EditorialReviewError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(json.dumps({"status": "refused", "error": str(exc)}, indent=2))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command("editorial-review-validate")
def editorial_review_validate(
    manifest: str = typer.Option(..., "--manifest", help="Review-kit article manifest JSON"),
    output_dir: str = typer.Option(..., "--output-dir", help="Generated local review-kit directory"),
):
    try:
        result = validate_editorial_review_kit(Path(manifest), Path(output_dir))
    except (EditorialReviewError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(json.dumps({"status": "refused", "error": str(exc)}, indent=2))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command("install-hermes-profile")
def install_hermes_profile(profile: str = "amy-radar", skill: str = "competitor-content-radar"):
    print(install_hermes(profile, skill))


@app.command()
def retry(config: str = "config.v0.2.example.yaml", fail_on_source_errors: bool = False):
    summary = run_pipeline(cfg(config), baseline=False, use_hermes=True)
    typer.echo(json.dumps(summary, indent=2))
    if summary.get("status") == "failed":
        raise typer.Exit(1)
    if _should_fail_for_warnings(summary, fail_on_source_errors):
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
