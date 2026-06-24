from __future__ import annotations

import json
import smtplib
import socket
import subprocess
import sys
import time
from email.message import EmailMessage
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_listening(port: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2) as sock:
                sock.recv(200)
                sock.sendall(b"QUIT\r\n")
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f"port {port} did not start listening: {last_error}")


def _assert_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))


def test_local_smtp_capture_exits_after_one_message_and_frees_port(tmp_path):
    port = _free_port()
    out_dir = tmp_path / "capture"
    cmd = [
        sys.executable,
        "scripts/local_smtp_capture.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--run-id",
        "test-run",
        "--output-dir",
        str(out_dir),
        "--timeout-seconds",
        "10",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_until_listening(port)
        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Reply-To"] = "reply@example.com"
        msg["Subject"] = "Local capture smoke"
        msg.set_content("hello")
        with smtplib.SMTP("127.0.0.1", port, timeout=5) as smtp:
            smtp.send_message(msg)
        stdout, stderr = proc.communicate(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    assert proc.returncode == 0, stderr
    _assert_port_free(port)
    eml = out_dir / "test-run.eml"
    meta = out_dir / "test-run.json"
    assert eml.exists()
    assert meta.exists()
    metadata = json.loads(meta.read_text(encoding="utf-8"))
    assert metadata["message_count"] == 1
    assert metadata["message_size_bytes"] == eml.stat().st_size
    assert "Local capture smoke" in eml.read_text(encoding="utf-8")
    assert '"status": "captured"' in stdout


def test_local_smtp_capture_timeout_exits_nonzero_and_frees_port(tmp_path):
    port = _free_port()
    out_dir = tmp_path / "capture-timeout"
    cmd = [
        sys.executable,
        "scripts/local_smtp_capture.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--run-id",
        "timeout-run",
        "--output-dir",
        str(out_dir),
        "--timeout-seconds",
        "1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _wait_until_listening(port)
    stdout, stderr = proc.communicate(timeout=5)
    assert proc.returncode != 0
    _assert_port_free(port)
    assert not (out_dir / "timeout-run.eml").exists()
    assert '"status": "timeout"' in stdout
