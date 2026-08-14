from __future__ import annotations
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field, field_validator
import os, re, yaml
from urllib.parse import urlsplit
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
class HermesConfig(BaseModel):
    profile: str = "amy-radar"; skill: str = "competitor-content-radar"; command: str = "hermes"
    one_shot_flag: str = "-z"; profile_flag: str = "-p"; skill_flag: str = "-s"; toolsets_flag: str = "-t"
    toolsets: str | None = "safe"; timeout_seconds: int = 180; enabled: bool = True; max_chars: int = 12000
class EmailConfig(BaseModel):
    enabled: bool = False; preview_only: bool = True; smtp_host: str = "localhost"; smtp_port: int = 1025
    smtp_username_env: str = "RADAR_SMTP_USERNAME"; smtp_password_env: str = "RADAR_SMTP_PASSWORD"; use_tls: bool = False
    sender_email: str; recipient_email: str; reply_to_email: str; subject_prefix: str = "[Competitor Radar]"; attach_markdown: bool = True
    report_url: str | None = None
    @field_validator("report_url")
    @classmethod
    def _https_report_url(cls, value):
        if value is None or value == "": return None
        parts=urlsplit(value)
        if parts.scheme != "https" or not parts.netloc: raise ValueError("email.report_url must be an absolute HTTPS URL")
        return value
    def invalid_addresses(self) -> list[str]:
        bad=[]
        for name in ("sender_email","recipient_email","reply_to_email"):
            val=getattr(self,name)
            if "#" in val or not EMAIL_RE.match(val): bad.append(f"{name}={val}")
        return bad
    def placeholder_addresses(self) -> list[str]:
        return [value for value in (self.sender_email, self.recipient_email, self.reply_to_email) if value.lower().endswith("@example.com")]
    def assert_live_send_allowed(self) -> None:
        bad=self.invalid_addresses()
        if bad: raise ValueError("Invalid email address(es); live send blocked: "+", ".join(bad))
        if not self.enabled or self.preview_only: raise ValueError("Email live delivery is disabled/preview_only")
class CrawlConfig(BaseModel):
    user_agent: str = "CompetitorContentRadar/0.2"; timeout_seconds: int = 20; max_articles_per_source: int = 10
    min_update_delta: float = 0.08; respect_robots: bool = True; fetch_retries: int = 0; fetch_retry_backoff_seconds: float = 0.0
class SourceConfig(BaseModel):
    id: str; name: str; url: str; allowed_domains: list[str]; allowed_paths: list[str]; seed_article: bool = False; seed_only: bool = False; monitor_url: str | None = None
    feed_urls: list[str] = Field(default_factory=list); sitemap_urls: list[str] = Field(default_factory=list)
    disable_feed_discovery: bool = False; disable_sitemap_discovery: bool = False; disable_listing_discovery: bool = False
    excluded_paths: list[str] = Field(default_factory=list); excluded_url_contains: list[str] = Field(default_factory=list); excluded_title_patterns: list[str] = Field(default_factory=list)
class ClientContextConfig(BaseModel):
    name: str = ""; website: str = ""; audience: str = ""
    offerings: list[str] = Field(default_factory=list); differentiators: list[str] = Field(default_factory=list)
    content_priorities: list[str] = Field(default_factory=list); deprioritize_topics: list[str] = Field(default_factory=list)
class AppConfig(BaseModel):
    workspace_id: str = "local-pilot"; data_dir: Path = Path(".radar-data"); database_url: str = "sqlite:///.radar-data/radar.db"; dry_run: bool = True
    log_level: str = "INFO"; client: ClientContextConfig = Field(default_factory=ClientContextConfig); hermes: HermesConfig; email: EmailConfig; crawl: CrawlConfig = Field(default_factory=CrawlConfig); sources: list[SourceConfig]

    @field_validator("data_dir", mode="before")
    @classmethod
    def _path(cls, v): return Path(v)
    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True); (self.data_dir/"reports").mkdir(parents=True, exist_ok=True); (self.data_dir/"logs").mkdir(parents=True, exist_ok=True); (self.data_dir/"tmp").mkdir(parents=True, exist_ok=True)
def load_config(path: str | Path | None = None, *, ensure_dirs: bool = True) -> AppConfig:
    import yaml
    path = Path(path or os.getenv("RADAR_CONFIG", "config.v0.2.example.yaml"))
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if os.getenv("RADAR_DATABASE_URL"): data["database_url"] = os.getenv("RADAR_DATABASE_URL")
    if os.getenv("RADAR_DATA_DIR"): data["data_dir"] = os.getenv("RADAR_DATA_DIR")
    if os.getenv("RADAR_DRY_RUN") is not None: data["dry_run"] = os.getenv("RADAR_DRY_RUN","true").lower() in {"1","true","yes"}
    if os.getenv("RADAR_HERMES_COMMAND"): data.setdefault("hermes",{})["command"] = os.getenv("RADAR_HERMES_COMMAND")
    cfg=AppConfig.model_validate(data)
    if ensure_dirs:
        cfg.ensure_dirs()
    return cfg
