from __future__ import annotations

import re
from urllib.parse import urlsplit

from .config import AppConfig
from .discovery import discover_urls, is_excluded_url
from .urlsec import validate_public_http_url


_CATEGORY_SEGMENTS = {"category", "categories", "tag", "tags", "author", "authors", "topic", "topics"}
_LISTING_SEGMENTS = {"blog", "blogs", "resources", "resource", "articles", "news", "webinars", "events"}
_ARTICLE_HINT_RE = re.compile(r"/(?:19|20)\d{2}(?:/\d{1,2})?(?:/\d{1,2})?/")


def _warning(reason: str, url: str | None = None) -> dict:
    item = {"reason": reason}
    if url:
        item["url"] = url
    return item


def classify_url(url: str, source_allowed_paths: list[str]) -> tuple[str, str | None]:
    """Return (likely_article|likely_non_article, reason).

    This is URL-shape heuristic only. It intentionally does not fetch article
    bodies or titles so source-check remains app-state read-only and lightweight.
    """
    path = urlsplit(url).path or "/"
    segments = [segment for segment in path.strip("/").split("/") if segment]
    lower_segments = [segment.lower() for segment in segments]
    lower_path = path.lower()

    if any(segment in _CATEGORY_SEGMENTS for segment in lower_segments):
        return "likely_non_article", "category path segment"
    if lower_path.endswith(("/category", "/categories", "/tag", "/tags", "/author", "/authors")):
        return "likely_non_article", "taxonomy/listing path"
    if _ARTICLE_HINT_RE.search(path):
        return "likely_article", None

    # Treat exact allowed roots and one-level section paths as listings/resources.
    normalized_allowed = [p.rstrip("/") or "/" for p in source_allowed_paths]
    normalized_path = path.rstrip("/") or "/"
    if normalized_path in normalized_allowed:
        return "likely_non_article", "configured listing root"
    if lower_segments and lower_segments[-1] in _LISTING_SEGMENTS:
        return "likely_non_article", "listing/resource path"

    # If the URL is only one segment deeper than an allowed listing path, it is
    # often a topic/category page. If it has at least two extra slug segments, it
    # is more likely an article detail page.
    best_extra = None
    for allowed in normalized_allowed:
        if normalized_path.startswith(allowed.rstrip("/") + "/"):
            suffix = normalized_path[len(allowed.rstrip("/")) :].strip("/")
            extra = [segment for segment in suffix.split("/") if segment]
            if best_extra is None or len(extra) < best_extra:
                best_extra = len(extra)
    if best_extra == 0:
        return "likely_non_article", "configured listing root"
    if best_extra == 1 and segments[-1].lower() in _LISTING_SEGMENTS:
        return "likely_non_article", "listing/resource path"

    return "likely_article", None


def _apply_source_exclusions(urls: list[str], source, skipped: list[dict]) -> list[str]:
    kept = []
    for url in urls:
        reason = is_excluded_url(url, source)
        if reason:
            skipped.append(_warning(reason, url))
            continue
        kept.append(url)
    return kept


def _is_intentional_skip(reason: str) -> bool:
    return reason.startswith("excluded ")


def _quality_fields(urls: list[str], source) -> dict:
    likely_article_urls = []
    likely_non_article_urls = []
    non_article_reasons = []
    for url in urls:
        kind, reason = classify_url(url, source.allowed_paths)
        if kind == "likely_article":
            likely_article_urls.append(url)
        else:
            likely_non_article_urls.append(url)
            non_article_reasons.append({"url": url, "reason": reason or "non-article URL shape"})

    notes = {
        "likely_article_count": len(likely_article_urls),
        "likely_non_article_count": len(likely_non_article_urls),
        "article_ratio": round(len(likely_article_urls) / len(urls), 3) if urls else 0.0,
        "classification_basis": "URL-shape heuristic only; source-check does not fetch article bodies or titles.",
    }
    if getattr(source, "excluded_title_patterns", None):
        notes["excluded_title_patterns_note"] = "Configured but not applied by source-check because titles are not fetched."
    if urls and likely_non_article_urls:
        notes["recommendation"] = "Tighten allowed_paths or add excluded_paths/excluded_url_contains for recurring listing/category URLs."
    elif urls and not likely_non_article_urls:
        notes["recommendation"] = "Discovered URLs look article-like by URL shape."
    elif not urls:
        notes["recommendation"] = "No crawlable URLs discovered; inspect robots, allowed_paths, redirects, or source URL."
    return {
        "likely_article_urls": likely_article_urls,
        "likely_non_article_urls": likely_non_article_urls,
        "non_article_reasons": non_article_reasons,
        "source_quality_notes": notes,
    }


def check_sources(cfg: AppConfig) -> dict:
    """Read-only source configuration/crawl preview.

    This function intentionally does not open the application database, fetch article
    bodies, write articles/runs/outbox rows, call Hermes, or send email.
    """
    results = []
    total_discovered = 0
    total_skipped = 0
    total_warnings = 0
    for source in cfg.sources:
        warnings: list[dict] = []
        skipped: list[dict] = []
        would_crawl: list[str] = []
        start_url = source.monitor_url or source.url
        start_ok = False
        try:
            start_url = validate_public_http_url(start_url, source.allowed_domains, source.allowed_paths)
            start_ok = True
        except Exception as exc:
            warnings.append(_warning(str(exc), start_url))

        if start_ok:
            try:
                try:
                    urls, errors = discover_urls(source, cfg.crawl, report_exclusions=True)
                except TypeError:
                    urls, errors = discover_urls(source, cfg.crawl)
                would_crawl = _apply_source_exclusions(urls, source, skipped)
                for error in errors:
                    item = _warning(error)
                    if _is_intentional_skip(error):
                        skipped.append(item)
                    else:
                        warnings.append(item)
            except Exception as exc:
                warnings.append(_warning(str(exc), start_url))

        quality = _quality_fields(would_crawl, source)
        skipped_or_warnings = skipped + warnings
        total_discovered += len(would_crawl)
        total_skipped += len(skipped)
        total_warnings += len(warnings)
        results.append(
            {
                "source_id": source.id,
                "name": source.name,
                "start_url": start_url,
                "allowed_domains": source.allowed_domains,
                "allowed_paths": source.allowed_paths,
                "excluded_paths": source.excluded_paths,
                "excluded_url_contains": source.excluded_url_contains,
                "excluded_title_patterns": source.excluded_title_patterns,
                "seed_article": source.seed_article,
                "would_crawl_urls": would_crawl,
                "discovered_url_count": len(would_crawl),
                **quality,
                "skipped_urls": skipped,
                "skipped_count": len(skipped),
                "warnings": warnings,
                "warning_count": len(warnings),
                "skipped_or_warnings": skipped_or_warnings,
                "skipped_or_warning_count": len(skipped_or_warnings),
                "ok": start_ok and len(would_crawl) > 0 and not warnings,
            }
        )

    return {
        "status": "ok",
        "mode": "source_check_app_state_read_only_live_public_web_discovery",
        "mutates_state": False,
        "writes_articles": False,
        "calls_hermes": False,
        "sends_email": False,
        "source_count": len(cfg.sources),
        "total_discovered_urls": total_discovered,
        "total_skipped_urls": total_skipped,
        "total_warnings": total_warnings,
        "total_skipped_or_warnings": total_skipped + total_warnings,
        "sources": results,
    }
