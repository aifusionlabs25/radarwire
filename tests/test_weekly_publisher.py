from pathlib import Path


def test_weekly_publisher_has_clean_gates_resume_and_live_verification():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "windows" / "publish-weekly-report.ps1").read_text(encoding="utf-8")

    assert "publish-preflight" in script
    assert "--fail-on-source-errors" in script
    assert "source_error_count" in script
    assert "failed_sources" in script
    assert "pending_deploy" in script
    assert "pending_email" in script
    assert "failed_email" in script
    assert "duplicate_skipped" in script
    assert "no_changes" in script
    assert "report-site.json" in script
    assert "Invoke-NativeLogged" in script
    assert "@('deploy', '--prod', '--yes'" in script
    assert "Invoke-RestMethod" in script
    assert '"${MetadataUrl}?run=$RunId"' in script
    assert '"${ReportUrl}?run=$RunId"' in script
    assert "EnableEmailDelivery" in script
    assert "email-delivery-preflight" in script
    assert "'--expected-report-url', $ReportUrl" in script
    assert "deliver-report" in script
    assert "'--send'" in script
    assert "Import-SmtpCredential" in script
    assert "Clear-SmtpCredential" in script


def test_weekly_task_is_sunday_evening_resumable_headless_publisher():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "windows" / "install-weekly-publish-task.ps1").read_text(encoding="utf-8")

    assert "publish-weekly-report.ps1" in script
    assert "-DaysOfWeek Sunday -At 6:00PM" in script
    assert "StartWhenAvailable" in script
    assert "RestartCount 3" in script
    assert "-NonInteractive" in script
    assert "WhatIfOnly = $true" in script
    assert "EnableEmailDelivery" in script
    assert "sends_email = [bool]$EnableEmailDelivery" in script


def test_weekly_email_configurator_uses_dpapi_and_never_prints_credentials():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "windows" / "configure-weekly-email.ps1").read_text(encoding="utf-8")

    assert "Read-Host 'SMTP app password' -AsSecureString" in script
    assert "ConvertFrom-SecureString" in script
    assert "Windows DPAPI current user" in script
    assert "prepare-email-delivery-config" in script
    assert "deliver-report" not in script
    assert "Register-ScheduledTask" not in script


def test_smtp_credential_helper_is_hidden_dpapi_scoped_and_refuses_overwrite():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "windows" / "store-smtp-credential.ps1").read_text(encoding="utf-8")

    assert "Read-Host 'Paste the Gmail app password, then press Enter' -AsSecureString" in script
    assert "ConvertFrom-SecureString" in script
    assert "Windows DPAPI current user" in script
    assert "-not $Force" in script
    assert "-replace '\\s', ''" in script
    assert "exactly 16 non-space characters" in script
    assert "ZeroFreeBSTR" in script
    assert "No email was sent" in script
    assert "deliver-report" not in script
    assert "Register-ScheduledTask" not in script


def test_local_capture_runner_uses_clean_child_environment():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "run-local-capture-email-test.ps1").read_text(encoding="utf-8")

    assert "Start-CleanCaptureProcess" in script
    assert "System.Diagnostics.ProcessStartInfo" in script
    assert "Start-Process" not in script
    assert '"--report-url", $ReportUrl' in script
