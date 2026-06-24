from __future__ import annotations

import argparse
import json
import socketserver
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class OneMessageSMTPHandler(socketserver.StreamRequestHandler):
    def send_line(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("utf-8"))
        self.wfile.flush()

    def handle(self) -> None:
        self.send_line("220 localhost local-capture-smtp")
        data_mode = False
        message_lines: list[str] = []
        mail_from: str | None = None
        rcpt_to: list[str] = []

        while True:
            try:
                raw = self.rfile.readline()
            except (ConnectionResetError, OSError):
                return
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")

            if data_mode:
                if line == ".":
                    self.server.capture_message(mail_from, rcpt_to, message_lines)  # type: ignore[attr-defined]
                    self.send_line("250 OK captured")
                    return
                if line.startswith(".."):
                    line = line[1:]
                message_lines.append(line)
                continue

            command = line.upper()
            if command.startswith("EHLO") or command.startswith("HELO"):
                self.send_line("250-localhost")
                self.send_line("250 SIZE 10485760")
            elif command.startswith("MAIL FROM:"):
                mail_from = line[10:].strip()
                self.send_line("250 OK")
            elif command.startswith("RCPT TO:"):
                rcpt_to.append(line[8:].strip())
                self.send_line("250 OK")
            elif command == "DATA":
                data_mode = True
                self.send_line("354 End data with <CR><LF>.<CR><LF>")
            elif command == "RSET":
                data_mode = False
                message_lines = []
                mail_from = None
                rcpt_to = []
                self.send_line("250 OK")
            elif command == "NOOP":
                self.send_line("250 OK")
            elif command == "QUIT":
                self.send_line("221 Bye")
                return
            else:
                self.send_line("250 OK")


class OneMessageSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_cls, *, output_dir: Path, run_id: str):
        super().__init__(server_address, handler_cls)
        self.output_dir = output_dir
        self.run_id = run_id
        self.message_count = 0
        self.captured = False
        self.eml_path = output_dir / f"{run_id}.eml"
        self.meta_path = output_dir / f"{run_id}.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def capture_message(self, mail_from: str | None, rcpt_to: list[str], message_lines: list[str]) -> None:
        raw = "\r\n".join(message_lines) + "\r\n"
        payload = raw.encode("utf-8", "replace")
        self.eml_path.write_bytes(payload)
        self.message_count += 1
        self.captured = True
        metadata = {
            "status": "captured",
            "run_id": self.run_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "mail_from": mail_from,
            "rcpt_to": rcpt_to,
            "message_count": self.message_count,
            "message_size_bytes": len(payload),
            "eml_path": str(self.eml_path),
        }
        self.meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture exactly one SMTP message locally, then exit.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1025)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    deadline = time.monotonic() + args.timeout_seconds
    try:
        with OneMessageSMTPServer((args.host, args.port), OneMessageSMTPHandler, output_dir=args.output_dir, run_id=args.run_id) as server:
            server.timeout = 0.25
            print(
                json.dumps(
                    {
                        "status": "listening",
                        "host": args.host,
                        "port": args.port,
                        "run_id": args.run_id,
                        "eml_path": str(server.eml_path),
                        "meta_path": str(server.meta_path),
                        "timeout_seconds": args.timeout_seconds,
                    }
                ),
                flush=True,
            )
            while not server.captured and time.monotonic() < deadline:
                server.handle_request()
            server.server_close()
            if server.captured:
                print(
                    json.dumps(
                        {
                            "status": "captured",
                            "message_count": server.message_count,
                            "eml_path": str(server.eml_path),
                            "meta_path": str(server.meta_path),
                        }
                    ),
                    flush=True,
                )
                return 0
            print(
                json.dumps(
                    {
                        "status": "timeout",
                        "message_count": server.message_count,
                        "run_id": args.run_id,
                        "timeout_seconds": args.timeout_seconds,
                    }
                ),
                flush=True,
            )
            return 1
    except OSError as exc:
        print(json.dumps({"status": "bind_failed", "host": args.host, "port": args.port, "error": str(exc)}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
