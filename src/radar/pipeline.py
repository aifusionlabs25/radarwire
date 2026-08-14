from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


from sqlalchemy import desc, select

from .analysis import DeterministicAnalysisAdapter, HermesCliAnalysisAdapter
from .discovery import discover_urls, fetch_html
from .emailer import deliver_or_preview
from .extract import extract_article
from .models import Analysis, Run, make_session_factory
from .reporting import render_reports, warning_summary
from .repository import RadarRepository

log = logging.getLogger("radar")


def _is_transient_fetch_exception(exc: Exception) -> bool:
    try:
        import httpx
    except Exception:
        httpx = None
    if httpx is not None:
        transient_types = (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.TransportError,
        )
        if isinstance(exc, httpx.HTTPStatusError):
            response = getattr(exc, "response", None)
            return response is not None and 500 <= response.status_code < 600
        if isinstance(exc, transient_types):
            return True
    msg = str(exc).lower()
    transient_markers = (
        "timed out",
        "timeout",
        "server disconnected",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
    )
    return any(marker in msg for marker in transient_markers)


def fetch_article_with_retries(url: str, src, crawl):
    attempts = max(1, int(getattr(crawl, "fetch_retries", 0)) + 1)
    backoff = max(0.0, float(getattr(crawl, "fetch_retry_backoff_seconds", 0.0)))
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return fetch_html(url, src, crawl)
        except Exception as exc:
            last_exc = exc
            if not _is_transient_fetch_exception(exc) or attempt >= attempts:
                raise
            log.warning(
                "transient article fetch error for source=%s url=%s attempt=%s/%s: %s",
                getattr(src, "id", "unknown"),
                url,
                attempt,
                attempts,
                exc,
            )
            if backoff:
                time.sleep(backoff * attempt)
    raise last_exc


def redact_database_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if not parts.password:
            return url
        user = parts.username or ""
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{user}:***@{host}{port}" if user else f"***@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "[REDACTED_DATABASE_URL]"


def _configure_run_logging(cfg, run_id: str) -> tuple[Path, logging.Handler]:
    log_dir = cfg.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"pipeline-{run_id}.log"
    logger = logging.getLogger("radar")
    logger.setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return log_path, handler


def _close_run_logging(handler: logging.Handler) -> None:
    logger = logging.getLogger("radar")
    logger.removeHandler(handler)
    handler.close()


def _fixture_articles(cfg):
    for src in cfg.sources:
        url = src.monitor_url or src.url
        html = f"""
        <html><title>{src.name} fixture article</title>
        <article>
        Offline deterministic fixture for {src.name}. This local article exercises the pipeline without network access.
        It includes a safe observed call to action and content opportunity for fixture validation.
        </article></html>
        """
        yield src, url, html


def run_pipeline(cfg, baseline: bool = False, use_hermes: bool = True, fixture: bool = False) -> dict:
    Session, _ = make_session_factory(cfg.database_url)
    run_id = uuid.uuid4().hex[:12]
    source_errors = {}
    discovered = 0
    changed = 0
    hermes_calls = 0
    log_path, log_handler = _configure_run_logging(cfg, run_id)

    with Session.begin() as s:
        repo = RadarRepository(s, cfg.workspace_id)
        if not repo.acquire_lock("radar-run", run_id):
            _close_run_logging(log_handler)
            raise RuntimeError("Another radar run is active")
        run = repo.create_run(run_id)
        try:
            log.info("run %s started fixture=%s baseline=%s use_hermes=%s", run_id, fixture, baseline, use_hermes)
            repo.set_stage(run, "discover")
            if fixture:
                for src, url, html in _fixture_articles(cfg):
                    repo.upsert_source(src)
                    source_errors[src.id] = []
                    discovered += 1
                    try:
                        art = extract_article(html, url, cfg.hermes.max_chars)
                        _, status = repo.upsert_article(
                            src.id,
                            art,
                            baseline=baseline,
                            min_update_delta=cfg.crawl.min_update_delta,
                        )
                        changed += int(status in {"new", "updated"})
                    except Exception as e:
                        source_errors.setdefault(src.id, []).append(f"fixture article {url}: {e}")
            else:
                for src in cfg.sources:
                    repo.upsert_source(src)
                    errs = []
                    try:
                        urls, errs = discover_urls(src, cfg.crawl)
                    except Exception as e:
                        urls = []
                        errs = [str(e)]
                    source_errors[src.id] = errs
                    discovered += len(urls)
                    for url in urls:
                        try:
                            final, html = fetch_article_with_retries(url, src, cfg.crawl)
                            art = extract_article(html, final, cfg.hermes.max_chars)
                            _, status = repo.upsert_article(
                                src.id,
                                art,
                                baseline=baseline,
                                min_update_delta=cfg.crawl.min_update_delta,
                            )
                            changed += int(status in {"new", "updated"})
                        except Exception as e:
                            source_errors.setdefault(src.id, []).append(f"article {url}: {e}")

            repo.set_stage(run, "analysis")
            pending = repo.pending_articles()
            if pending and use_hermes and cfg.hermes.enabled and not fixture:
                adapter = HermesCliAnalysisAdapter(cfg)
            else:
                adapter = DeterministicAnalysisAdapter()
            for art in pending:
                try:
                    result, meta = adapter.analyze(art)
                    hermes_calls += int(not isinstance(adapter, DeterministicAnalysisAdapter))
                    repo.add_analysis(
                        run_id,
                        art,
                        result.model_dump(),
                        meta.get("stdout", ""),
                        meta.get("stderr", ""),
                        meta.get("exit_code", 0),
                        meta.get("duration_ms", 0),
                    )
                    repo.mark_analyzed(art)
                except Exception as e:
                    source_errors.setdefault(art.source_id, []).append(f"analysis {art.canonical_url}: {e}")

            repo.set_stage(run, "report")
            analyses = list(
                s.execute(
                    select(Analysis).where(Analysis.workspace_id == cfg.workspace_id, Analysis.run_id == run_id)
                ).scalars()
            )
            report_dir = cfg.data_dir / "reports" / run_id
            digest = render_reports(run_id, report_dir, analyses, source_errors, cfg.client.model_dump())

            repo.set_stage(run, "delivery")
            delivery = deliver_or_preview(repo, cfg, run_id, report_dir, digest)
            warnings = warning_summary(source_errors, len(analyses))
            summary = {
                "status": "ok",
                "run_id": run_id,
                "fixture": fixture,
                "discovered": discovered,
                "changed": changed,
                "pending_analyzed": len(analyses),
                "hermes_calls": hermes_calls,
                "report_dir": str(report_dir),
                "delivery": delivery,
                "source_errors": source_errors,
                "log_path": str(log_path),
                **warnings,
            }
            repo.finish_run(run, "ok", summary)
            log.info("run %s completed", run_id)
            return summary
        except Exception as e:
            warnings = warning_summary(source_errors, 0)
            summary = {
                "status": "failed",
                "run_id": run_id,
                "fixture": fixture,
                "discovered": discovered,
                "changed": changed,
                "pending_analyzed": 0,
                "hermes_calls": hermes_calls,
                "source_errors": source_errors,
                "last_error": str(e),
                "failed_stage": run.stage,
                "log_path": str(log_path),
                **warnings,
            }
            repo.finish_run(run, "failed", summary)
            log.exception("run %s failed at stage %s", run_id, run.stage)
            return summary
        finally:
            repo.release_lock("radar-run")
            _close_run_logging(log_handler)


def backup(cfg, out: Path | None = None) -> Path:
    out = out or cfg.data_dir / (f"backup-{uuid.uuid4().hex[:8]}.zip")
    shutil.make_archive(str(out).removesuffix(".zip"), "zip", cfg.data_dir)
    return out if str(out).endswith(".zip") else Path(str(out) + ".zip")


def restore(cfg, archive: Path) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(archive), cfg.data_dir)


def _latest_run_payload(latest: Run | None):
    if not latest:
        return None
    summary = latest.summary_json or {}
    return {
        "id": latest.id,
        "status": latest.status,
        "stage": latest.stage,
        "started_at": latest.started_at.isoformat() if latest.started_at else None,
        "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
        "last_error": summary.get("last_error"),
        "source_errors": summary.get("source_errors", {}),
        "has_warnings": summary.get("has_warnings", False),
        "source_error_count": summary.get("source_error_count", 0),
        "failed_sources": summary.get("failed_sources", []),
        "analyzed_article_count": summary.get("analyzed_article_count", summary.get("pending_analyzed", 0)),
        "log_path": summary.get("log_path"),
    }


def status(cfg) -> dict:
    Session, _ = make_session_factory(cfg.database_url)
    with Session() as s:
        from .models import Article, Lock, Outbox, Source

        latest = s.execute(
            select(Run).where(Run.workspace_id == cfg.workspace_id).order_by(desc(Run.started_at)).limit(1)
        ).scalar_one_or_none()
        return {
            "workspace_id": cfg.workspace_id,
            "sources": s.query(Source).count(),
            "articles": s.query(Article).count(),
            "runs": s.query(Run).count(),
            "outbox": s.query(Outbox).count(),
            "active_locks": s.query(Lock).count(),
            "data_dir": str(cfg.data_dir),
            "latest_run": _latest_run_payload(latest),
        }


def state_audit(cfg) -> dict:
    Session, _ = make_session_factory(cfg.database_url)
    with Session() as s:
        from .models import Article, Lock, Outbox

        latest = s.execute(
            select(Run).where(Run.workspace_id == cfg.workspace_id).order_by(desc(Run.started_at)).limit(1)
        ).scalar_one_or_none()
        fixture_articles = s.execute(
            select(Article).where(
                Article.workspace_id == cfg.workspace_id,
                (
                    Article.canonical_url.like("%fixture%")
                    | Article.source_id.like("%fixture%")
                    | Article.title.like("%fixture%")
                    | Article.sanitized_text.like("%Offline deterministic fixture%")
                ),
            )
        ).scalars().all()
        return {
            "workspace_id": cfg.workspace_id,
            "data_dir": str(cfg.data_dir),
            "database_url_redacted": redact_database_url(cfg.database_url),
            "article_count": s.query(Article).filter(Article.workspace_id == cfg.workspace_id).count(),
            "run_count": s.query(Run).filter(Run.workspace_id == cfg.workspace_id).count(),
            "outbox_count": s.query(Outbox).filter(Outbox.workspace_id == cfg.workspace_id).count(),
            "sent_email_count": s.query(Outbox).filter(Outbox.workspace_id == cfg.workspace_id, Outbox.sent_at.isnot(None)).count(),
            "active_locks": s.query(Lock).filter(Lock.workspace_id == cfg.workspace_id).count(),
            "fixture_looking_article_count": len(fixture_articles),
            "fixture_looking_articles": [a.canonical_url for a in fixture_articles[:25]],
            "latest_run": _latest_run_payload(latest),
            "cleanup_plan": "Read-only audit only. To reset pilot state, archive/copy the data_dir and create a fresh config pointing at a new data_dir/database; delete nothing without operator approval.",
        }
