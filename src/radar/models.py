from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text, JSON, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)
class Base(DeclarativeBase): pass
class Source(Base):
    __tablename__="sources"; id: Mapped[str] = mapped_column(String, primary_key=True); workspace_id: Mapped[str] = mapped_column(String, nullable=False); name: Mapped[str] = mapped_column(String, nullable=False); url: Mapped[str] = mapped_column(String, nullable=False); config_json: Mapped[dict] = mapped_column(JSON, nullable=False); created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False); updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
class Article(Base):
    __tablename__="articles"; __table_args__=(UniqueConstraint("workspace_id","canonical_url", name="uq_article_workspace_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True); workspace_id: Mapped[str] = mapped_column(String, nullable=False); source_id: Mapped[str] = mapped_column(String, nullable=False); canonical_url: Mapped[str] = mapped_column(String, nullable=False); title: Mapped[str] = mapped_column(String, nullable=False); author: Mapped[str|None] = mapped_column(String); published_at: Mapped[datetime|None] = mapped_column(DateTime); content_hash: Mapped[str] = mapped_column(String, nullable=False); sanitized_text: Mapped[str] = mapped_column(Text, nullable=False); status: Mapped[str] = mapped_column(String, nullable=False, default="pending"); first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False); last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False); last_analyzed_hash: Mapped[str|None] = mapped_column(String)
class Run(Base):
    __tablename__="runs"; id: Mapped[str] = mapped_column(String, primary_key=True); workspace_id: Mapped[str] = mapped_column(String, nullable=False); status: Mapped[str] = mapped_column(String, nullable=False); stage: Mapped[str] = mapped_column(String, nullable=False); started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False); finished_at: Mapped[datetime|None] = mapped_column(DateTime); summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
class Analysis(Base):
    __tablename__="analysis"; id: Mapped[int] = mapped_column(Integer, primary_key=True); workspace_id: Mapped[str] = mapped_column(String, nullable=False); run_id: Mapped[str] = mapped_column(String, nullable=False); article_id: Mapped[int] = mapped_column(Integer, nullable=False); content_hash: Mapped[str] = mapped_column(String, nullable=False); result_json: Mapped[dict] = mapped_column(JSON, nullable=False); stdout: Mapped[str|None] = mapped_column(Text); stderr: Mapped[str|None] = mapped_column(Text); exit_code: Mapped[int|None] = mapped_column(Integer); duration_ms: Mapped[int|None] = mapped_column(Integer); created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
class Outbox(Base):
    __tablename__="outbox"; __table_args__=(UniqueConstraint("workspace_id","message_key", name="uq_outbox_workspace_message"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True); workspace_id: Mapped[str] = mapped_column(String, nullable=False); message_key: Mapped[str] = mapped_column(String, nullable=False); status: Mapped[str] = mapped_column(String, nullable=False); recipient: Mapped[str] = mapped_column(String, nullable=False); subject: Mapped[str] = mapped_column(String, nullable=False); provider_response: Mapped[str|None] = mapped_column(Text); attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0); created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False); sent_at: Mapped[datetime|None] = mapped_column(DateTime)
class Lock(Base):
    __tablename__="locks"; name: Mapped[str] = mapped_column(String, primary_key=True); workspace_id: Mapped[str] = mapped_column(String, nullable=False); owner: Mapped[str] = mapped_column(String, nullable=False); acquired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False); expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
def make_engine(url: str):
    kwargs={"future": True}
    if url.startswith("sqlite"): kwargs["connect_args"]={"check_same_thread": False}
    return create_engine(url, **kwargs)
def make_session_factory(url: str):
    engine=make_engine(url); Base.metadata.create_all(engine); return sessionmaker(engine, expire_on_commit=False, future=True), engine
