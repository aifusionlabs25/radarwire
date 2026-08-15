from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import typer
import yaml
from rich import print

from .config import AppConfig, load_config
from .content_studio import BriefSet, ContentStudioError, generate_content_studio, generate_content_studio_drafts
from .publication_history import (
    PublicationHistoryError,
    load_publication_history,
    sync_publication_history,
)
from .voice_library import VoiceLibraryError, load_voice_examples, sync_voice_library
from .editorial_review import EditorialReviewError, build_editorial_review_kit, validate_editorial_review_kit
from .emailer import (
    deliver_editorial_review,
    deliver_existing_report,
    delivery_preflight,
    editorial_delivery_preflight,
    load_existing_report,
)
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


def _review_route_key(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/index.html"):
        normalized = normalized[: -len("/index.html")]
    return normalized


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


@app.command("email-delivery-preflight")
def email_delivery_preflight(
    config: str = "config.pilot.local.yaml",
    run_id: str = typer.Option(..., "--run-id", help="Existing clean run/report ID to validate for automatic delivery"),
    expected_report_url: str | None = typer.Option(None, "--expected-report-url", help="Require the configured report link to match the verified published route"),
    allow_local_smtp: bool = typer.Option(False, "--allow-local-smtp", help="Permit loopback SMTP only for an explicit local-capture test"),
):
    c = cfg(config, ensure_dirs=False)
    _report_dir, digest = load_existing_report(c, run_id)
    username_set = bool(os.getenv(c.email.smtp_username_env)) if c.email.smtp_username_env else False
    password_set = bool(os.getenv(c.email.smtp_password_env)) if c.email.smtp_password_env else False
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    smtp_host_allowed = allow_local_smtp or c.email.smtp_host.lower() not in local_hosts
    invalid_addresses = c.email.invalid_addresses()
    placeholder_addresses = c.email.placeholder_addresses()
    report_url_matches_expected = (
        expected_report_url is None
        or (
            c.email.report_url is not None
            and c.email.report_url.rstrip("/") == expected_report_url.rstrip("/")
        )
    )
    clean_report = (
        digest.get("article_count", 0) > 0
        and digest.get("source_error_count", 0) == 0
        and not digest.get("failed_sources", [])
        and not digest.get("has_warnings", False)
    )
    live_config = (not c.dry_run) and c.email.enabled and (not c.email.preview_only)
    ok = all(
        (
            live_config,
            not invalid_addresses,
            not placeholder_addresses,
            username_set,
            password_set,
            smtp_host_allowed,
            0 < c.email.smtp_port < 65536,
            c.email.use_tls,
            bool(c.email.report_url),
            report_url_matches_expected,
            clean_report,
        )
    )
    payload = {
        "ok": ok,
        "run_id": run_id,
        "article_count": digest.get("article_count", 0),
        "source_error_count": digest.get("source_error_count", 0),
        "failed_source_count": len(digest.get("failed_sources", [])),
        "has_warnings": digest.get("has_warnings", False),
        "live_config": live_config,
        "invalid_address_count": len(invalid_addresses),
        "placeholder_address_count": len(placeholder_addresses),
        "smtp_username_env_set": username_set,
        "smtp_password_env_set": password_set,
        "smtp_host_allowed": smtp_host_allowed,
        "smtp_port_allowed": 0 < c.email.smtp_port < 65536,
        "smtp_tls_enabled": c.email.use_tls,
        "report_url_set": bool(c.email.report_url),
        "report_url_matches_expected": report_url_matches_expected,
        "attach_markdown": c.email.attach_markdown,
        "sends_email": False,
    }
    typer.echo(json.dumps(payload, indent=2))
    if not ok:
        raise typer.Exit(2)


@app.command("prepare-email-delivery-config")
def prepare_email_delivery_config(
    source_config: str = typer.Option(..., "--source-config", help="Existing reviewed pilot config to copy"),
    output_config: str = typer.Option(..., "--output-config", help="New local live-delivery config path"),
    smtp_host: str = typer.Option("smtp.gmail.com", "--smtp-host"),
    smtp_port: int = typer.Option(587, "--smtp-port"),
    report_url: str = typer.Option(..., "--report-url", help="Stable HTTPS report URL included in the email"),
    sender_email: str | None = typer.Option(None, "--sender-email"),
    recipient_email: str | None = typer.Option(None, "--recipient-email"),
    reply_to_email: str | None = typer.Option(None, "--reply-to-email"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing delivery config only after review"),
):
    source_path = Path(source_config)
    output_path = Path(output_config)
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    email = data.setdefault("email", {})
    address_overrides = {
        "sender_email": sender_email,
        "recipient_email": recipient_email,
        "reply_to_email": reply_to_email,
    }
    for key, value in address_overrides.items():
        if value:
            email[key] = value
    candidate = AppConfig.model_validate(data)
    if candidate.email.invalid_addresses() or candidate.email.placeholder_addresses():
        typer.echo(json.dumps({"status": "refused_addresses", "sends_email": False}, indent=2))
        raise typer.Exit(2)
    if smtp_host.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise typer.BadParameter("Automatic delivery config requires a non-loopback SMTP host.")
    if output_path.exists() and not overwrite:
        typer.echo(json.dumps({"status": "refused_existing_config", "output_config": str(output_path), "sends_email": False}, indent=2))
        raise typer.Exit(2)

    data["dry_run"] = False
    email.update(
        {
            "enabled": True,
            "preview_only": False,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_username_env": "RADAR_SMTP_USERNAME",
            "smtp_password_env": "RADAR_SMTP_PASSWORD",
            "use_tls": True,
            "report_url": report_url,
            "attach_markdown": False,
        }
    )
    AppConfig.model_validate(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    typer.echo(
        json.dumps(
            {
                "status": "prepared_live_delivery_config",
                "output_config": str(output_path),
                "live_capable": True,
                "credentials_written": False,
                "sends_email": False,
            },
            indent=2,
        )
    )


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
    if result.get("delivery", {}).get("status") == "failed":
        raise typer.Exit(1)


@app.command("editorial-email-preflight")
def editorial_email_preflight(
    config: str = "config.v0.2.example.yaml",
    review_dir: str = typer.Option(..., "--review-dir", help="Generated editorial review-kit directory"),
    expected_review_url: str | None = typer.Option(None, "--expected-review-url", help="Require the email review link to match the verified hosted route"),
):
    c = cfg(config, ensure_dirs=False)
    preflight = editorial_delivery_preflight(c, Path(review_dir))
    username_set = bool(os.getenv(c.email.smtp_username_env)) if c.email.smtp_username_env else False
    password_set = bool(os.getenv(c.email.smtp_password_env)) if c.email.smtp_password_env else False
    live_config = (not c.dry_run) and c.email.enabled and (not c.email.preview_only)
    invalid_addresses = c.email.invalid_addresses()
    placeholder_addresses = c.email.placeholder_addresses()
    smtp_host_allowed = c.email.smtp_host.lower() not in {"localhost", "127.0.0.1", "::1"}
    review_url_matches_expected = (
        expected_review_url is None
        or _review_route_key(preflight["review_url"]) == _review_route_key(expected_review_url)
    )
    ok = all(
        (
            live_config,
            not invalid_addresses,
            not placeholder_addresses,
            username_set,
            password_set,
            smtp_host_allowed,
            0 < c.email.smtp_port < 65536,
            c.email.use_tls,
            review_url_matches_expected,
            preflight["concept_count"] > 0,
        )
    )
    payload = {
        "ok": ok,
        "delivery_id": preflight["delivery_id"],
        "concept_count": preflight["concept_count"],
        "live_config": live_config,
        "invalid_address_count": len(invalid_addresses),
        "placeholder_address_count": len(placeholder_addresses),
        "smtp_username_env_set": username_set,
        "smtp_password_env_set": password_set,
        "smtp_host_allowed": smtp_host_allowed,
        "smtp_port_allowed": 0 < c.email.smtp_port < 65536,
        "smtp_tls_enabled": c.email.use_tls,
        "review_url": preflight["review_url"],
        "review_url_matches_expected": review_url_matches_expected,
        "supporting_report_url_set": bool(preflight.get("supporting_report_url")),
        "sends_email": False,
    }
    typer.echo(json.dumps(payload, indent=2))
    if not ok:
        raise typer.Exit(2)


@app.command("deliver-editorial-review")
def deliver_editorial_review_command(
    config: str = "config.v0.2.example.yaml",
    review_dir: str = typer.Option(..., "--review-dir", help="Generated editorial review-kit directory"),
    send: bool = typer.Option(False, "--send", help="Actually send live email when live config gates pass"),
):
    c = cfg(config)
    live_config = (not c.dry_run) and c.email.enabled and (not c.email.preview_only)
    if live_config and not send:
        typer.echo(json.dumps({"status": "refused", "error": "Refusing live-send-capable config without --send"}, indent=2))
        raise typer.Exit(2)
    Session, _ = make_session_factory(c.database_url)
    with Session.begin() as session:
        result = deliver_editorial_review(
            RadarRepository(session, c.workspace_id),
            c,
            Path(review_dir),
            send=send,
        )
    typer.echo(json.dumps(result, indent=2))
    if result.get("delivery", {}).get("status") == "failed":
        raise typer.Exit(1)


@app.command("content-studio")
def content_studio(
    config: str = "config.v0.2.example.yaml",
    run_id: str = typer.Option(..., "--run-id", help="Existing clean report ID to use as research"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="New review-artifact directory"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow replacing existing Content Studio files"),
    voice_corpus: str | None = typer.Option(None, "--voice-corpus", help="Approved client voice-corpus JSONL"),
    publication_history: str | None = typer.Option(None, "--publication-history", help="Published-content JSONL exclusion list"),
):
    c = cfg(config, ensure_dirs=False)
    report_dir, digest = load_existing_report(c, run_id)
    destination = Path(output_dir) if output_dir else report_dir / "content-studio"
    try:
        voice_examples = load_voice_examples(Path(voice_corpus)) if voice_corpus else []
        published_items = load_publication_history(Path(publication_history)) if publication_history else []
        result = generate_content_studio(
            c,
            run_id,
            digest,
            destination,
            overwrite=overwrite,
            voice_examples=voice_examples,
            publication_history=published_items,
        )
    except (ContentStudioError, PublicationHistoryError, VoiceLibraryError, OSError, ValueError, json.JSONDecodeError) as exc:
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
    voice_corpus: str | None = typer.Option(None, "--voice-corpus", help="Approved client voice-corpus JSONL"),
):
    c = cfg(config, ensure_dirs=False)
    _, digest = load_existing_report(c, run_id)
    try:
        requested = [int(item.strip()) for item in ranks.split(",") if item.strip()]
        brief_set = BriefSet.model_validate_json(Path(briefs_path).read_text(encoding="utf-8"))
        voice_examples = load_voice_examples(Path(voice_corpus)) if voice_corpus else []
        result = generate_content_studio_drafts(
            c,
            run_id,
            digest,
            brief_set,
            Path(output_dir),
            ranks=requested,
            overwrite=overwrite,
            voice_examples=voice_examples,
        )
    except (ContentStudioError, VoiceLibraryError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(json.dumps({"status": "refused", "error": str(exc)}, indent=2))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command("voice-library-sync")
def voice_library_sync(
    endpoint: str = typer.Option(..., "--endpoint", help="Hosted RadarWire editorial-revisions API URL"),
    client_id: str = typer.Option(..., "--client-id", help="Client library identifier"),
    output_dir: str = typer.Option(..., "--output-dir", help="Ignored local voice-library directory"),
    token_env: str = typer.Option("RADAR_EDITORIAL_SAVE_TOKEN", "--token-env", help="Environment variable containing the private review token"),
):
    try:
        result = sync_voice_library(endpoint, client_id, Path(output_dir), token_env=token_env)
    except (VoiceLibraryError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(json.dumps({"status": "refused", "error": str(exc)}, indent=2))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command("publication-history-sync")
def publication_history_sync(
    endpoint: str = typer.Option(..., "--endpoint", help="Hosted RadarWire editorial-status API URL"),
    client_id: str = typer.Option(..., "--client-id", help="Client publication-history identifier"),
    output_dir: str = typer.Option(..., "--output-dir", help="Ignored local publication-history directory"),
    token_env: str = typer.Option("RADAR_EDITORIAL_SAVE_TOKEN", "--token-env", help="Environment variable containing the private review token"),
):
    try:
        result = sync_publication_history(endpoint, client_id, Path(output_dir), token_env=token_env)
    except (PublicationHistoryError, OSError, ValueError, json.JSONDecodeError) as exc:
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
