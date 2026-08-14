from __future__ import annotations

import urllib.robotparser
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from .config import CrawlConfig, SourceConfig
from .urlsec import canonicalize_url, safe_join, validate_public_http_url


class SourceFailure(Exception):
    pass


def feed_urls(base_url: str) -> list[str]:
    return [urljoin(base_url, x) for x in ("feed.xml", "rss.xml", "atom.xml", "feed/", "rss/")]


def sitemap_urls(base_url: str) -> list[str]:
    root = urljoin(base_url, "/")
    return [urljoin(root, "sitemap.xml")]


def candidate_feed_urls(base_url: str) -> list[str]:
    return feed_urls(base_url) + sitemap_urls(base_url)


def _robots_timeout(crawl: CrawlConfig) -> float:
    return max(1.0, min(float(getattr(crawl, "timeout_seconds", 5)), 5.0))


def _excluded_path_matches(path: str, prefix: str) -> bool:
    normalized = prefix or "/"
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if normalized == "/":
        return True
    if normalized.endswith("/"):
        return path.startswith(normalized)
    return path == normalized or path.startswith(normalized + "/")


def is_excluded_url(url: str, source: SourceConfig) -> str | None:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    for prefix in getattr(source, "excluded_paths", []) or []:
        if _excluded_path_matches(path, prefix):
            return f"excluded_paths:{prefix}"
    lower_url = url.lower()
    for needle in getattr(source, "excluded_url_contains", []) or []:
        if needle.lower() in lower_url:
            return f"excluded_url_contains:{needle}"
    return None


def _append_if_allowed(found: list[str], url: str | None, source: SourceConfig, errors: list[str] | None = None, *, report_exclusions: bool = False) -> None:
    if not url:
        return
    reason = is_excluded_url(url, source)
    if reason:
        if errors is not None and report_exclusions:
            errors.append(f"excluded {url}: {reason}")
        return
    found.append(url)


def _dedupe_limit(found: list[str], crawl: CrawlConfig) -> list[str]:
    dedup = []
    seen = set()
    for u in found:
        c = canonicalize_url(u)
        if c not in seen:
            seen.add(c)
            dedup.append(c)
        if len(dedup) >= crawl.max_articles_per_source:
            break
    return dedup


def robots_allowed(url: str, source: SourceConfig, crawl: CrawlConfig, cache: dict | None = None) -> bool:
    if not crawl.respect_robots:
        return True
    cache = cache if cache is not None else {}
    parsed = urlsplit(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        robots_url = validate_public_http_url(robots_url, source.allowed_domains, ["/"])
    except Exception:
        return False

    if robots_url not in cache:
        try:
            response = httpx.get(
                robots_url,
                timeout=_robots_timeout(crawl),
                follow_redirects=True,
                headers={"User-Agent": crawl.user_agent},
            )
            response.raise_for_status()
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.parse(response.text.splitlines())
            cache[robots_url] = rp
        except Exception:
            # Conservative MVP behavior: if robots cannot be read/parsed quickly, do not crawl that host.
            cache[robots_url] = None

    parser = cache.get(robots_url)
    if parser is None:
        return False
    try:
        return bool(parser.can_fetch(crawl.user_agent, url))
    except Exception:
        return False


def _add_seed_url(source: SourceConfig, crawl: CrawlConfig, robots_cache: dict, found: list[str], errors: list[str], *, report_exclusions: bool) -> None:
    try:
        seed = validate_public_http_url(source.url, source.allowed_domains, source.allowed_paths)
        if robots_allowed(seed, source, crawl, cache=robots_cache):
            _append_if_allowed(found, seed, source, errors, report_exclusions=report_exclusions)
        else:
            errors.append(f"robots disallow seed {seed}")
    except Exception as e:
        errors.append(str(e))


def discover_urls(source: SourceConfig, crawl: CrawlConfig, *, report_exclusions: bool = False) -> tuple[list[str], list[str]]:
    robots_cache = {}
    start = validate_public_http_url(source.monitor_url or source.url, source.allowed_domains, source.allowed_paths)
    found = []
    errors = []
    headers = {"User-Agent": crawl.user_agent}
    if not robots_allowed(start, source, crawl, cache=robots_cache):
        return [], [f"robots disallow or unavailable for listing {start}"]

    if source.seed_article:
        _add_seed_url(source, crawl, robots_cache, found, errors, report_exclusions=report_exclusions)

    feed_enabled = not getattr(source, "disable_feed_discovery", False)
    sitemap_enabled = not getattr(source, "disable_sitemap_discovery", False)
    listing_enabled = not getattr(source, "disable_listing_discovery", False)

    if getattr(source, "seed_only", False) or not (feed_enabled or sitemap_enabled or listing_enabled):
        return _dedupe_limit(found, crawl), errors

    with httpx.Client(timeout=crawl.timeout_seconds, follow_redirects=True, headers=headers) as client:
        feed_candidates = []
        if feed_enabled:
            feed_candidates.extend(source.feed_urls or feed_urls(start))
        if sitemap_enabled:
            feed_candidates.extend(source.sitemap_urls or sitemap_urls(start))
        for fu in feed_candidates:
            try:
                # Discovery endpoints may live outside article paths (for example,
                # a site-wide /feed/ that links to articles under /blog/). Links
                # extracted from them are still constrained to allowed_paths below.
                u = safe_join(start, fu, source.allowed_domains, ["/"])
                if not u or not robots_allowed(u, source, crawl, cache=robots_cache):
                    continue
                r = client.get(u)
                if r.status_code >= 400:
                    continue
                parsed = feedparser.parse(r.text)
                for e in parsed.entries[: crawl.max_articles_per_source * 2]:
                    lu = safe_join(u, getattr(e, "link", None), source.allowed_domains, source.allowed_paths)
                    if lu and robots_allowed(lu, source, crawl, cache=robots_cache):
                        _append_if_allowed(found, lu, source, errors, report_exclusions=report_exclusions)
                if "urlset" in r.text[:1000].lower():
                    soup = BeautifulSoup(r.text, "xml")
                    for loc in soup.find_all("loc")[: crawl.max_articles_per_source * 4]:
                        lu = safe_join(u, loc.get_text(strip=True), source.allowed_domains, source.allowed_paths)
                        if lu and robots_allowed(lu, source, crawl, cache=robots_cache):
                            _append_if_allowed(found, lu, source, errors, report_exclusions=report_exclusions)
            except Exception as e:
                errors.append(f"feed/sitemap {fu}: {e}")

        if listing_enabled:
            try:
                r = client.get(start)
                if r.status_code >= 400:
                    raise SourceFailure(f"HTTP {r.status_code}")
                final = validate_public_http_url(str(r.url), source.allowed_domains, source.allowed_paths)
                if not robots_allowed(final, source, crawl, cache=robots_cache):
                    raise SourceFailure(f"robots disallow redirected listing {final}")
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    lu = safe_join(final, a["href"], source.allowed_domains, source.allowed_paths)
                    if lu and lu != start and robots_allowed(lu, source, crawl, cache=robots_cache):
                        _append_if_allowed(found, lu, source, errors, report_exclusions=report_exclusions)
            except Exception as e:
                errors.append(f"listing {start}: {e}")

    return _dedupe_limit(found, crawl), errors


def fetch_html(url: str, source: SourceConfig, crawl: CrawlConfig) -> tuple[str, str]:
    robots_cache = {}
    url = validate_public_http_url(url, source.allowed_domains, source.allowed_paths)
    if not robots_allowed(url, source, crawl, cache=robots_cache):
        raise SourceFailure(f"robots disallow {url}")
    with httpx.Client(timeout=crawl.timeout_seconds, follow_redirects=True, headers={"User-Agent": crawl.user_agent}) as client:
        r = client.get(url)
        r.raise_for_status()
        final = validate_public_http_url(str(r.url), source.allowed_domains, source.allowed_paths)
        if not robots_allowed(final, source, crawl, cache=robots_cache):
            raise SourceFailure(f"robots disallow redirected URL {final}")
        ctype = r.headers.get("content-type", "").lower()
        if ctype and "text/html" not in ctype and "xml" not in ctype:
            raise SourceFailure(f"unsupported content-type {ctype}")
        return final, r.text
