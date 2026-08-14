from pathlib import Path


def test_weekly_publisher_has_clean_gates_resume_and_live_verification():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "windows" / "publish-weekly-report.ps1").read_text(encoding="utf-8")

    assert "publish-preflight" in script
    assert "--fail-on-source-errors" in script
    assert "source_error_count" in script
    assert "failed_sources" in script
    assert "pending_deploy" in script
    assert "no_changes" in script
    assert "report-site.json" in script
    assert "Invoke-NativeLogged" in script
    assert "@('deploy', '--prod', '--yes'" in script
    assert "Invoke-RestMethod" in script
    assert "deliver-report" not in script
    assert "--send" not in script


def test_weekly_task_is_sunday_evening_resumable_headless_publisher():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "windows" / "install-weekly-publish-task.ps1").read_text(encoding="utf-8")

    assert "publish-weekly-report.ps1" in script
    assert "-DaysOfWeek Sunday -At 6:00PM" in script
    assert "StartWhenAvailable" in script
    assert "RestartCount 3" in script
    assert "-NonInteractive" in script
    assert "WhatIfOnly = $true" in script
