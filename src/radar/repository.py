from __future__ import annotations

from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Analysis, Article, Lock, Outbox, Run, Source, utcnow


class RadarRepository:
    def __init__(self, session: Session, workspace_id: str):
        self.s = session
        self.workspace_id = workspace_id

    def upsert_source(self, src):
        obj = self.s.get(Source, src.id)
        if obj is None:
            obj = Source(
                id=src.id,
                workspace_id=self.workspace_id,
                name=src.name,
                url=src.url,
                config_json=src.model_dump(),
            )
            self.s.add(obj)
        else:
            obj.name = src.name
            obj.url = src.url
            obj.config_json = src.model_dump()
            obj.updated_at = utcnow()
        return obj

    def upsert_article(self, source_id: str, extracted, baseline: bool = False, min_update_delta: float = 0.0) -> tuple[Article, str]:
        obj = self.s.execute(
            select(Article).where(
                Article.workspace_id == self.workspace_id,
                Article.canonical_url == extracted.canonical_url,
            )
        ).scalar_one_or_none()
        now = utcnow()
        if obj is None:
            obj = Article(
                workspace_id=self.workspace_id,
                source_id=source_id,
                canonical_url=extracted.canonical_url,
                title=extracted.title,
                author=extracted.author,
                published_at=extracted.published_at,
                content_hash=extracted.content_hash,
                sanitized_text=extracted.sanitized_text,
                status="baseline" if baseline else "pending",
                first_seen_at=now,
                last_seen_at=now,
            )
            if baseline:
                obj.last_analyzed_hash = extracted.content_hash
            self.s.add(obj)
            return obj, "baseline" if baseline else "new"

        old_text = obj.sanitized_text or ""
        new_text = extracted.sanitized_text or ""
        obj.last_seen_at = now
        obj.title = extracted.title
        obj.author = extracted.author
        obj.published_at = extracted.published_at

        if obj.content_hash != extracted.content_hash:
            delta = 1.0 - SequenceMatcher(None, old_text, new_text).ratio()
            obj.content_hash = extracted.content_hash
            obj.sanitized_text = extracted.sanitized_text
            if delta < min_update_delta:
                return obj, "minor_update"
            obj.status = "pending"
            return obj, "updated"

        obj.sanitized_text = extracted.sanitized_text
        return obj, "unchanged"

    def pending_articles(self):
        return list(
            self.s.execute(
                select(Article).where(Article.workspace_id == self.workspace_id, Article.status == "pending")
            ).scalars()
        )

    def mark_analyzed(self, article: Article):
        article.last_analyzed_hash = article.content_hash
        article.status = "analyzed"

    def add_analysis(self, run_id, article, result, stdout="", stderr="", exit_code=0, duration_ms=0):
        a = Analysis(
            workspace_id=self.workspace_id,
            run_id=run_id,
            article_id=article.id,
            content_hash=article.content_hash,
            result_json=result,
            stdout=stdout[-4000:],
            stderr=stderr[-4000:],
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        self.s.add(a)
        return a

    def create_run(self, run_id):
        r = Run(id=run_id, workspace_id=self.workspace_id, status="running", stage="start", summary_json={})
        self.s.add(r)
        return r

    def set_stage(self, run: Run, stage: str):
        run.stage = stage
        self.s.flush()

    def finish_run(self, run: Run, status: str, summary: dict):
        run.status = status
        run.stage = "finished" if status == "ok" else "failed"
        run.finished_at = utcnow()
        run.summary_json = summary

    def acquire_lock(self, name: str, owner: str, ttl_seconds=3600) -> bool:
        now = utcnow()
        self.s.execute(delete(Lock).where(Lock.name == name, Lock.expires_at < now))
        self.s.flush()
        if self.s.get(Lock, name):
            return False
        self.s.add(
            Lock(
                name=name,
                workspace_id=self.workspace_id,
                owner=owner,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
        )
        return True

    def release_lock(self, name: str):
        self.s.execute(delete(Lock).where(Lock.name == name))
        self.s.flush()

    def outbox_get_or_create(self, key, recipient, subject):
        obj = self.s.execute(
            select(Outbox).where(Outbox.workspace_id == self.workspace_id, Outbox.message_key == key)
        ).scalar_one_or_none()
        if obj:
            return obj, False
        obj = Outbox(
            workspace_id=self.workspace_id,
            message_key=key,
            status="pending",
            recipient=recipient,
            subject=subject,
            attempt_count=0,
        )
        self.s.add(obj)
        return obj, True
