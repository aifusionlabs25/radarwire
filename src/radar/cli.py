from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich import print

from .config import AppConfig, load_config
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
