from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from .models import Analysis


THEME_KEYWORDS = {
    "Sales tax compliance": ["sales tax", "nexus", "resale certificate", "tax permit", "taxjar"],
    "1099 and W-9 filing": ["1099", "w-9", "w9", "1099-nec", "1099-misc"],
    "AI compliance automation": ["agentic", "ai", "automation", "avi", "dashboard"],
    "Small-business finance": ["bookkeeping", "accounting", "profitability", "payroll", "cash flow"],
    "Audit and risk readiness": ["audit", "penalty", "risk", "compliance", "amnesty"],
}

THEME_FILTER_TERMS = {
    "AI compliance automation": ["agentic", "automation", "automated", "avi", "dashboard", "workflow"],
    "Audit and risk readiness": ["audit", "penalty", "risk", "amnesty", "liability", "exposure"],
}


def warning_summary(source_errors: dict | None, analyzed_article_count: int) -> dict:
    source_errors = source_errors or {}
    failed_sources = sorted([source for source, errors in source_errors.items() if errors])
    source_error_count = sum(len(errors or []) for errors in source_errors.values())
    return {
        "has_warnings": source_error_count > 0,
        "source_error_count": source_error_count,
        "failed_sources": failed_sources,
        "analyzed_article_count": analyzed_article_count,
    }


def _warning_text(source_errors: dict | None) -> str:
    source_errors = source_errors or {}
    lines = []
    for source, errors in sorted(source_errors.items()):
        for err in errors or []:
            lines.append(f"- {source}: {err}")
    return "\n".join(lines) if lines else "None"


def _article_source(article: dict) -> str:
    host = urlparse(article.get("url", "")).netloc.lower().removeprefix("www.")
    if "blog.taxbandits.com" in host:
        return "TaxBandits"
    if "tax1099.com" in host:
        return "Tax1099"
    if "blog.boomtax.com" in host:
        return "BoomTax"
    if "efilemyforms.com" in host:
        return "eFileMyForms"
    if "sovos.com" in host:
        return "Sovos"
    if "avalara.com" in host:
        return "Avalara"
    if "bench.co" in host:
        return "Bench"
    if "patriotsoftware.com" in host:
        return "Patriot"
    if "taxjar.com" in host:
        return "TaxJar"
    return host or "Unknown"


def _as_list(article: dict, key: str, limit: int | None = None) -> list[str]:
    values = article.get(key) or []
    if not isinstance(values, list):
        return []
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    return cleaned[:limit] if limit is not None else cleaned


def _clip(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _source_counts(articles: list[dict]) -> dict[str, int]:
    counts = Counter(_article_source(article) for article in articles)
    return dict(sorted(counts.items()))


def _opportunity_highlights(articles: list[dict], limit: int = 6) -> list[dict]:
    by_source: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    ranked_articles = sorted(articles, key=lambda article: float(article.get("client_relevance", 0.5)), reverse=True)
    for article in ranked_articles:
        source = _article_source(article)
        for opportunity in _as_list(article, "content_opportunities", 2):
            key = re.sub(r"\W+", " ", opportunity.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            by_source[source].append(
                {
                    "source": source,
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "opportunity": opportunity,
                    "client_relevance": float(article.get("client_relevance", 0.5)),
                    "relevance_reason": article.get("relevance_reason", ""),
                }
            )
    highlights = []
    sources = sorted(
        by_source,
        key=lambda source: (-max(item["client_relevance"] for item in by_source[source]), source),
    )
    index = 0
    while len(highlights) < limit and any(index < len(by_source[source]) for source in sources):
        for source in sources:
            if index < len(by_source[source]):
                highlights.append(by_source[source][index])
                if len(highlights) >= limit:
                    return highlights
        index += 1
    return highlights


def _group_articles(articles: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for article in articles:
        grouped[_article_source(article)].append(article)
    return dict(sorted(grouped.items()))


def _md_bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "- None noted"


def _txt_bullets(values: list[str], indent: str = "  - ") -> str:
    return "\n".join(f"{indent}{value}" for value in values) if values else f"{indent}None noted"


def _html_list(values: list[str]) -> str:
    if not values:
        return "<li>None noted</li>"
    return "".join(f"<li>{html.escape(value)}</li>" for value in values)


def _theme_query(theme: str) -> str:
    return "|".join(THEME_FILTER_TERMS.get(theme, THEME_KEYWORDS.get(theme, [theme]))).lower()


def _theme_button(theme: str) -> str:
    query = html.escape(_theme_query(theme), quote=True)
    label = html.escape(theme)
    return f'<button class="pill theme-filter" type="button" data-query="{query}">{label}</button>'


def _email_intro(themes: list[str], source_counts: dict[str, int], client_context: dict | None = None) -> str:
    lead_themes = ", ".join(themes[:3]) if themes else "repeatable compliance education"
    client_name = (client_context or {}).get("name") or "the client"
    return (
        f"Competitors are leaning into {lead_themes}. For {client_name}, the strongest opportunities "
        "turn dense filing and compliance topics into accurate next steps, practical tools, and "
        "clear paths to software or expert filing help."
    )


def _client_lens(opportunity: str) -> str:
    text = opportunity.lower()
    if any(term in text for term in ["sales tax", "nexus", "permit", "resale"]):
        return "Frame it as an owner-friendly decision path: do I need to register, where, and what do I do next?"
    if any(term in text for term in ["1099", "w-9", "w9"]):
        return "Make filing season feel manageable: deadlines, who gets which form, and what records to collect."
    if any(term in text for term in ["payroll", "cost", "cash", "living", "salary"]):
        return "Tie it back to owner decisions: pricing, payroll, hiring, and cash-flow planning."
    if any(term in text for term in ["automation", "ai", "dashboard", "workflow"]):
        return "Show how automation saves time without asking owners to become compliance experts."
    if any(term in text for term in ["audit", "risk", "penalty", "liability"]):
        return "Lead with risk avoidance: what to document now to stay out of trouble later."
    return "Turn it into a plain-English checklist or calculator a busy owner can act on."


def _article_md(article: dict) -> str:
    implications = _as_list(article, "inferred_implications", 2)
    ctas = _as_list(article, "offers_or_ctas", 2)
    opportunities = _as_list(article, "content_opportunities", 3)
    evidence = _as_list(article, "evidence_quotes", 2)
    return (
        f"### {article['title']}\n"
        f"<{article['url']}>\n\n"
        f"{article['summary']}\n\n"
        "**Why it matters**\n"
        f"{_md_bullets(implications)}\n\n"
        "**Observed offers / CTAs**\n"
        f"{_md_bullets(ctas)}\n\n"
        "**Content opportunities**\n"
        f"{_md_bullets(opportunities)}\n\n"
        "**Evidence**\n"
        f"{_md_bullets(evidence)}"
    )


def _article_txt(article: dict) -> str:
    return (
        f"{article['title']}\n"
        f"{article['url']}\n"
        f"{article['summary']}\n\n"
        "Why it matters:\n"
        f"{_txt_bullets(_as_list(article, 'inferred_implications', 2))}\n\n"
        "Observed offers / CTAs:\n"
        f"{_txt_bullets(_as_list(article, 'offers_or_ctas', 2))}\n\n"
        "Content opportunities:\n"
        f"{_txt_bullets(_as_list(article, 'content_opportunities', 3))}\n"
    )


def _article_html(article: dict) -> str:
    source = html.escape(_article_source(article))
    title = html.escape(article.get("title", "Untitled"))
    url = html.escape(article.get("url", ""), quote=True)
    summary = html.escape(article.get("summary", ""))
    search_text = html.escape(
        " ".join(
            [
                _article_source(article),
                article.get("title", ""),
                article.get("url", ""),
                article.get("summary", ""),
                " ".join(_as_list(article, "inferred_implications")),
                " ".join(_as_list(article, "content_opportunities")),
                " ".join(_as_list(article, "offers_or_ctas")),
            ]
        ).lower(),
        quote=True,
    )
    opportunity_count = len(_as_list(article, "content_opportunities"))
    relevance = round(float(article.get("client_relevance", 0.5)) * 100)
    return (
        f"<details class=\"article-card\" data-source=\"{source}\" data-search=\"{search_text}\">"
        "<summary>"
        "<span class=\"summary-main\">"
        f"<span class=\"source-label\">{source}</span>"
        f"<span class=\"article-title\">{title}</span>"
        f"<span class=\"summary-preview\">{summary}</span>"
        "</span>"
        f"<span class=\"op-count\">{relevance}% fit - {opportunity_count} opps</span>"
        "</summary>"
        "<div class=\"article-body\">"
        f"<p class=\"url\"><a href=\"{url}\">{url}</a></p>"
        "<div class=\"article-grid\">"
        "<section><h4>Why It Matters</h4><ul>"
        f"{_html_list(_as_list(article, 'inferred_implications', 2))}"
        "</ul></section>"
        "<section><h4>Opportunities</h4><ul>"
        f"{_html_list(_as_list(article, 'content_opportunities', 3))}"
        "</ul></section>"
        "<section><h4>Observed CTAs</h4><ul>"
        f"{_html_list(_as_list(article, 'offers_or_ctas', 2))}"
        "</ul></section>"
        "<section><h4>Evidence</h4><ul>"
        f"{_html_list(_as_list(article, 'evidence_quotes', 2))}"
        "</ul></section>"
        "</div>"
        "</div>"
        "</details>"
    )


def _email_html(
    run_id: str,
    summary_fields: dict,
    source_counts: dict[str, int],
    themes: list[str],
    opportunities: list[dict],
    articles: list[dict],
    warnings_text: str,
    client_context: dict | None = None,
) -> str:
    source_items = "".join(
        f"<span style=\"display:inline-block;margin:0 6px 8px 0;padding:7px 10px;border-radius:999px;"
        f"background:#eaf7f6;border:1px solid #a8d6d1;color:#075b61;font-weight:700;font-size:13px;\">"
        f"{html.escape(source)} <span style=\"color:#172033;\">{count}</span></span>"
        for source, count in source_counts.items()
    ) or "<span>None</span>"
    theme_items = "".join(
        f"<span style=\"display:inline-block;margin:0 6px 8px 0;padding:7px 10px;border-radius:999px;"
        f"background:#fff4df;border:1px solid #efcf91;color:#704308;font-weight:700;font-size:13px;\">"
        f"{html.escape(theme)}</span>"
        for theme in themes[:5]
    ) or "<span>None noted</span>"
    intro = html.escape(_email_intro(themes, source_counts, client_context))
    opportunity_items = "".join(
        "<tr><td style=\"padding:0 0 12px;\">"
        "<div style=\"border:1px solid #d8e2e5;border-left:5px solid #ef5d3d;border-radius:8px;"
        "padding:12px 14px;background:#ffffff;\">"
        f"<div style=\"color:#a3540a;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;\">"
        f"{html.escape(item['source'])}</div>"
        f"<div style=\"font-size:16px;line-height:1.35;font-weight:800;color:#172033;margin:3px 0 8px;\">"
        f"{html.escape(item['opportunity'])}</div>"
        f"<div style=\"background:#fff8ea;border:1px solid #efcf91;border-radius:7px;padding:8px 10px;"
        f"color:#593b0b;margin:0 0 9px;font-size:14px;line-height:1.4;\">"
        f"<strong>Client lens:</strong> {html.escape(_client_lens(item['opportunity']))}</div>"
        f"<div style=\"color:#637084;font-size:12px;margin:0 0 8px;\">"
        f"Client fit: {round(item['client_relevance'] * 100)}%"
        f"{(' - ' + html.escape(_clip(item['relevance_reason'], 160))) if item.get('relevance_reason') else ''}</div>"
        f"<a href=\"{html.escape(item.get('url', ''), quote=True)}\" "
        "style=\"display:inline-block;color:#075b61;font-weight:800;text-decoration:none;"
        "border-bottom:2px solid #f2b705;\">"
        f"Open source article: {html.escape(_clip(item['title'], 82))}</a>"
        "</div></td></tr>"
        for item in opportunities[:3]
    ) or "<tr><td>None noted</td></tr>"
    article_items = "".join(
        "<tr><td style=\"padding:0 0 12px;\">"
        "<div style=\"border:1px solid #d8e2e5;border-radius:8px;padding:12px 14px;background:#fbfdfe;\">"
        f"<div style=\"color:#008a92;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;\">"
        f"{html.escape(_article_source(article))}</div>"
        f"<div style=\"font-size:15px;line-height:1.35;font-weight:800;color:#172033;margin:3px 0 6px;\">"
        f"{html.escape(article.get('title', 'Untitled'))}</div>"
        f"<div style=\"color:#4e5f71;margin-bottom:8px;\">{html.escape(_clip(article.get('summary', ''), 260))}</div>"
        f"<a href=\"{html.escape(article.get('url', ''), quote=True)}\" "
        "style=\"color:#075b61;font-weight:800;text-decoration:none;\">Read article</a>"
        "</div></td></tr>"
        for article in articles[:3]
    ) or "<tr><td>None noted</td></tr>"
    warning_section = (
        "<section><h2>Warnings / Errors</h2>"
        f"<pre>{html.escape(warnings_text)}</pre></section>"
        if summary_fields["source_error_count"]
        else ""
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Competitor Content Radar Email Digest</title>"
        "</head>"
        "<body style=\"margin:0;background:#eef3f6;color:#172033;font-family:Aptos,Segoe UI,sans-serif;line-height:1.5;\">"
        "<main style=\"max-width:760px;margin:0 auto;background:#ffffff;\">"
        "<div style=\"background:#10233f;color:#ffffff;padding:24px 26px;border-bottom:6px solid #ef5d3d;\">"
        "<p style=\"margin:0 0 8px;color:#9ed7d6;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.12em;\">RadarWire Brief</p>"
        "<h1 style=\"margin:0 0 10px;font-size:30px;line-height:1.12;\">Competitor moves worth acting on</h1>"
        f"<p style=\"margin:0;color:#d7e5eb;\">{summary_fields['analyzed_article_count']} article(s) across "
        f"{len(source_counts)} source(s). {summary_fields['source_error_count']} warning(s). Run {html.escape(run_id)}.</p>"
        "</div>"
        "<div style=\"padding:22px 24px;\">"
        "<section style=\"border:1px solid #d8e2e5;border-radius:8px;padding:14px 16px;margin-bottom:18px;"
        "background:#fbfdfe;\">"
        "<h2 style=\"margin:0 0 8px;font-size:19px;line-height:1.2;color:#172033;\">Executive read</h2>"
        f"<p style=\"margin:0;color:#3c4f63;font-size:15px;\">{intro}</p>"
        "</section>"
        "<section style=\"margin-bottom:18px;\">"
        "<h2 style=\"margin:0 0 10px;font-size:19px;line-height:1.2;color:#172033;\">Top themes</h2>"
        f"<div>{theme_items}</div>"
        "</section>"
        "<section style=\"margin-bottom:18px;\">"
        "<h2 style=\"margin:0 0 10px;font-size:19px;line-height:1.2;color:#172033;\">Priority content opportunities</h2>"
        f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\">{opportunity_items}</table>"
        "</section>"
        "<section style=\"margin-bottom:18px;\">"
        "<h2 style=\"margin:0 0 10px;font-size:19px;line-height:1.2;color:#172033;\">Source mix</h2>"
        f"<div>{source_items}</div>"
        "</section>"
        "<section style=\"margin-bottom:18px;\">"
        "<h2 style=\"margin:0 0 10px;font-size:19px;line-height:1.2;color:#172033;\">Article highlights</h2>"
        f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\">{article_items}</table>"
        "</section>"
        f"{warning_section}"
        "<p style=\"margin:20px 0 0;color:#637084;font-size:13px;border-top:1px solid #d8e2e5;padding-top:12px;\">"
        "For drill-down, use the interactive report page generated with this run."
        "</p>"
        "</div></main></body></html>"
    )


def _email_txt(
    run_id: str,
    summary_fields: dict,
    source_counts: dict[str, int],
    themes: list[str],
    opportunities: list[dict],
    articles: list[dict],
    warnings_text: str,
    client_context: dict | None = None,
) -> str:
    source_mix = "\n".join(f"- {source}: {count}" for source, count in source_counts.items()) or "- None"
    theme_lines = "\n".join(f"- {theme}" for theme in themes[:5]) or "- None noted"
    intro = _email_intro(themes, source_counts, client_context)
    opportunity_lines = "\n".join(
        f"{idx}. {item['opportunity']}\n"
        f"   Client lens: {_client_lens(item['opportunity'])}\n"
        f"   Client fit: {round(item['client_relevance'] * 100)}%"
        f"{(' - ' + item['relevance_reason']) if item.get('relevance_reason') else ''}\n"
        f"   Source: {item['source']} - {item['title']}\n"
        f"   Link: {item.get('url', '')}"
        for idx, item in enumerate(opportunities[:3], start=1)
    ) or "None noted"
    article_lines = "\n\n".join(
        f"{idx}. {_article_source(article)}: {article.get('title', 'Untitled')}\n"
        f"{article.get('summary', '')}\n{article.get('url', '')}"
        for idx, article in enumerate(articles[:3], start=1)
    ) or "None noted"
    warning_block = (
        "\nWarnings / Errors\n"
        "-----------------\n"
        f"{warnings_text}\n"
        if summary_fields["source_error_count"]
        else ""
    )
    return (
        "Competitor Content Radar\n"
        "Weekly competitor content brief\n\n"
        f"Run: {run_id}\n"
        f"Analyzed articles: {summary_fields['analyzed_article_count']}\n"
        f"Sources: {len(source_counts)}\n"
        f"Warnings: {summary_fields['source_error_count']}\n\n"
        "Executive read\n"
        "--------------\n"
        f"{intro}\n\n"
        "Top themes\n"
        "----------\n"
        f"{theme_lines}\n\n"
        "Priority content opportunities\n"
        "------------------------------\n"
        f"{opportunity_lines}\n\n"
        "Source mix\n"
        "----------\n"
        f"{source_mix}\n\n"
        "Article highlights\n"
        "------------------\n"
        f"{article_lines}\n"
        f"{warning_block}\n"
        "For drill-down, use the interactive report page generated with this run.\n"
    )


def render_reports(run_id: str, report_dir: Path, analyses: list[Analysis], source_errors: dict | None = None, client_context: dict | None = None) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    items = [a.result_json for a in analyses]
    articles = []
    for item, row in zip(items, analyses):
        article = dict(item["article"])
        article["content_hash"] = row.content_hash
        article["confidence"] = item.get("confidence", 0.7)
        article["client_relevance"] = item.get("client_relevance", 0.5)
        article["relevance_reason"] = item.get("relevance_reason", "")
        articles.append(article)
    articles.sort(key=lambda article: float(article.get("client_relevance", 0.5)), reverse=True)
    summary_fields = warning_summary(source_errors, len(items))
    source_counts = _source_counts(articles)
    opportunity_highlights = _opportunity_highlights(articles)
    digest = {
        "schema_version": "radar.digest.v1",
        "run_id": run_id,
        "client": client_context or {},
        "article_count": len(items),
        "cross_source_themes": derive_themes(items),
        "source_counts": source_counts,
        "opportunity_highlights": opportunity_highlights,
        "articles": articles,
        "source_errors": source_errors or {},
        **summary_fields,
    }
    manifest = {
        "run_id": run_id,
        "files": [
            "manifest.json",
            "analysis.json",
            "digest.json",
            "digest.html",
            "digest.txt",
            "digest.md",
            "digest_email.html",
            "digest_email.txt",
            "run-summary.json",
        ],
    }
    (report_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (report_dir / "analysis.json").write_text(json.dumps(items, indent=2), encoding="utf-8")
    (report_dir / "digest.json").write_text(json.dumps(digest, indent=2), encoding="utf-8")

    warnings_text = _warning_text(source_errors)
    source_mix_txt = "\n".join(f"- {source}: {count}" for source, count in source_counts.items()) or "- None"
    source_mix_md = source_mix_txt
    themes_txt = "\n".join(f"- {theme}" for theme in digest["cross_source_themes"]) or "- None"
    opps_txt = "\n".join(
        f"- {item['source']}: {item['opportunity']} ({item['title']})" for item in opportunity_highlights
    ) or "- None"
    grouped = _group_articles(digest["articles"])
    txt_sections = []
    md_sections = []
    for source, source_articles in grouped.items():
        txt_sections.append(
            f"{source}\n"
            + "=" * len(source)
            + "\n\n"
            + "\n\n".join(_article_txt(article) for article in source_articles)
        )
        md_sections.append(
            f"## {source}\n\n"
            + "\n\n".join(_article_md(article) for article in source_articles)
        )
    txt = (
        "Competitor Content Radar\n"
        f"Run: {run_id}\n\n"
        "Snapshot\n"
        "--------\n"
        f"Analyzed articles: {summary_fields['analyzed_article_count']}\n"
        f"Warnings: {summary_fields['source_error_count']} across {len(summary_fields['failed_sources'])} source(s)\n\n"
        "Source mix\n"
        "----------\n"
        f"{source_mix_txt}\n\n"
        "Top themes\n"
        "----------\n"
        f"{themes_txt}\n\n"
        "Priority content opportunities\n"
        "------------------------------\n"
        f"{opps_txt}\n\n"
        "Source warnings/errors\n"
        "----------------------\n"
        f"{warnings_text}\n\n"
        "Article detail\n"
        "--------------\n\n"
        + "\n\n".join(txt_sections)
    )
    md = (
        "# Competitor Content Radar\n\n"
        f"Run `{run_id}` analyzed **{summary_fields['analyzed_article_count']}** articles "
        f"with **{summary_fields['source_error_count']}** warnings across "
        f"**{len(summary_fields['failed_sources'])}** source(s).\n\n"
        "## Source Mix\n\n"
        f"{source_mix_md}\n\n"
        "## Top Themes\n\n"
        f"{themes_txt}\n\n"
        "## Priority Content Opportunities\n\n"
        f"{opps_txt}\n\n"
        "## Source Warnings / Errors\n\n"
        f"{warnings_text}\n\n"
        "## Article Detail\n\n"
        + "\n\n".join(md_sections)
    )
    warning_items = "".join(
        f"<li><strong>{html.escape(source)}</strong>: {html.escape(err)}</li>"
        for source, errors in sorted((source_errors or {}).items())
        for err in (errors or [])
    )
    warning_panel = (
        "<section class=\"panel warnings warning-alert\"><h2>Source Warnings / Errors</h2>"
        f"<ul>{warning_items}</ul></section>"
        if warning_items
        else ""
    )
    footer_warning = (
        f"{summary_fields['source_error_count']} warning(s) across {len(summary_fields['failed_sources'])} source(s)"
        if warning_items
        else "Source warnings/errors: none"
    )
    client_name = (client_context or {}).get("name") or "Competitor"
    status_label = (
        f"{summary_fields['source_error_count']} warning(s)"
        if summary_fields["source_error_count"]
        else "All sources clean"
    )
    theme_pills = "".join(_theme_button(theme) for theme in digest["cross_source_themes"])
    theme_pills_html = theme_pills or '<span class="pill">None</span>'
    opportunity_items = "".join(
        "<li>"
        f"<span>{html.escape(item['source'])}</span>"
        f"<strong>{html.escape(item['opportunity'])}</strong>"
        f"<a class=\"opp-link\" href=\"{html.escape(item.get('url', ''), quote=True)}\">{html.escape(item['title'])}</a>"
        "</li>"
        for item in opportunity_highlights
    ) or "<li><strong>None noted</strong></li>"
    source_filter_buttons = (
        "<button class=\"filter active\" type=\"button\" data-source=\"all\">All</button>"
        + "".join(
            f"<button class=\"filter\" type=\"button\" data-source=\"{html.escape(source, quote=True)}\">"
            f"{html.escape(source)} <span>{count}</span></button>"
            for source, count in source_counts.items()
        )
    )
    article_stack = "".join(_article_html(article) for article in digest["articles"])
    report_script = (
        "<script>"
        "const cards=[...document.querySelectorAll('.article-card')];"
        "const buttons=[...document.querySelectorAll('.filter')];"
        "const sourceCards=[...document.querySelectorAll('.source-stat')];"
        "const themeButtons=[...document.querySelectorAll('.theme-filter')];"
        "const search=document.querySelector('#report-search');"
        "const shown=document.querySelector('#shown-count');"
        "const reviewPane=document.querySelector('.review-pane');"
        "let active='all';"
        "function applyFilters(){"
        "const themeQuery=search.dataset.themeQuery||'';"
        "const raw=(themeQuery||search.value||'').trim().toLowerCase();"
        "const terms=themeQuery?raw.split('|').filter(Boolean):raw.split(/\\s+/).filter(Boolean);"
        "let visible=0;"
        "cards.forEach(card=>{"
        "const searchable=card.dataset.search||'';"
        "const sourceOk=active==='all'||card.dataset.source===active;"
        "const searchOk=!terms.length||(themeQuery?terms.some(term=>searchable.includes(term)):terms.every(term=>searchable.includes(term)));"
        "const keep=sourceOk&&searchOk;"
        "card.hidden=!keep;"
        "if(keep) visible++;"
        "});"
        "shown.textContent=visible+' shown';"
        "}"
        "function activateSource(source){"
        "buttons.forEach(b=>b.classList.remove('active'));"
        "const match=buttons.find(b=>b.dataset.source===source)||buttons[0];"
        "if(match)match.classList.add('active');"
        "active=source;"
        "applyFilters();"
        "}"
        "buttons.forEach(button=>button.addEventListener('click',()=>activateSource(button.dataset.source)));"
        "sourceCards.forEach(button=>button.addEventListener('click',()=>{"
        "search.value='';"
        "delete search.dataset.themeQuery;"
        "activateSource(button.dataset.sourceJump);"
        "reviewPane.scrollIntoView({block:'start',behavior:'smooth'});"
        "}));"
        "themeButtons.forEach(button=>button.addEventListener('click',()=>{"
        "search.value=button.textContent;"
        "search.dataset.themeQuery=button.dataset.query||button.textContent;"
        "activateSource('all');"
        "themeButtons.forEach(b=>b.classList.remove('active'));"
        "button.classList.add('active');"
        "reviewPane.scrollIntoView({block:'start',behavior:'smooth'});"
        "}));"
        "search.addEventListener('input',()=>{delete search.dataset.themeQuery;themeButtons.forEach(b=>b.classList.remove('active'));applyFilters();});"
        "document.querySelector('#expand-all').addEventListener('click',()=>cards.forEach(card=>{if(!card.hidden) card.open=true;}));"
        "document.querySelector('#collapse-all').addEventListener('click',()=>cards.forEach(card=>card.open=false));"
        "applyFilters();"
        "</script>"
    )
    html_doc = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(client_name)} Content Radar</title>"
        "<style>"
        ":root{color-scheme:light;--ink:#172033;--muted:#57687b;--line:#cbd9e1;--panel:#ffffff;--soft:#eaf7f6;--accent:#008a92;--coral:#ef5d3d;--gold:#d89216;--bg:#eef3f6;--ok:#237255;--storm:#10233f}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 'Aptos','Segoe UI',sans-serif}"
        "body:before{content:'';position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(90deg,rgba(0,138,146,.08) 1px,transparent 1px),linear-gradient(rgba(239,93,61,.06) 1px,transparent 1px);background-size:54px 54px;opacity:.45}"
        "button,input{font:inherit}button{cursor:pointer}"
        ".wrap{max-width:1440px;margin:0 auto;padding:24px 22px 42px;position:relative}"
        "header{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;background:var(--storm);color:#fff;border:1px solid #1e415f;border-left:8px solid var(--coral);border-radius:8px;padding:20px 22px;margin-bottom:18px;box-shadow:0 18px 40px rgba(16,35,63,.16)}"
        "h1{font-size:33px;line-height:1.08;margin:0 0 8px;letter-spacing:0;color:#fff}h2{font-size:18px;margin:0 0 10px;color:var(--ink)}h3{font-size:16px;line-height:1.25;margin:0}h4{font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin:0 0 6px;color:var(--muted)}"
        "p{margin:0 0 10px}.meta{color:#d7e5eb}"
        ".status-chip{border:1px solid #f2b705;color:#10233f;background:#f2b705;border-radius:999px;padding:7px 11px;font-weight:800;font-size:12px;white-space:nowrap;box-shadow:0 7px 20px rgba(242,183,5,.25)}"
        ".layout{display:grid;grid-template-columns:minmax(315px,360px) minmax(600px,1fr);gap:18px;align-items:start}.rail{position:sticky;top:14px;display:grid;gap:12px}.panel{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:14px;box-shadow:0 10px 22px rgba(16,35,63,.06)}"
        ".stats{display:grid;grid-template-columns:1fr 1fr;gap:8px}.stat{border:0;background:var(--storm);color:#fff;padding:11px;border-radius:8px;box-shadow:0 10px 22px rgba(16,35,63,.12)}.stat span{display:block;color:#9ed7d6;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.stat strong{font-size:24px;color:#fff}"
        ".source-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.source-stat{width:100%;text-align:left;background:#fff;border:1px solid var(--line);border-top:4px solid var(--accent);border-radius:8px;padding:8px 10px;color:var(--ink);box-shadow:0 8px 16px rgba(16,35,63,.05)}.source-stat:hover,.theme-filter:hover{border-color:#87c8c5;background:#f0fbfa;transform:translateY(-1px)}.source-stat span{display:block;color:var(--muted);font-size:11px}.source-stat strong{font-size:19px;color:var(--coral)}"
        ".pill-row{display:flex;flex-wrap:wrap;gap:7px}.pill,.source-label{display:inline-block;border:1px solid #a8d6d1;color:#075b61;background:#eaf7f6;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:800}.theme-filter.active{background:#fff4df;border-color:#d89216;color:#704308}"
        ".opps{padding-left:18px;margin:0}.opps li{margin:0 0 12px}.opps span{display:block;color:#a3540a;font-weight:800;font-size:11px;text-transform:uppercase;letter-spacing:.04em}.opps strong{display:block;font-size:13px;line-height:1.35}.opp-link{display:block;color:#075b61;line-height:1.35;text-decoration:none;border-bottom:1px solid #f2b705;width:fit-content;margin-top:4px;font-size:12px;font-weight:700}"
        ".toolbar{position:sticky;top:0;z-index:2;background:rgba(255,255,255,.97);backdrop-filter:blur(8px);border:1px solid var(--line);border-top:4px solid var(--coral);border-radius:8px;padding:12px;margin-bottom:12px;box-shadow:0 12px 24px rgba(16,35,63,.08)}"
        ".search-row{display:flex;gap:8px;align-items:center;margin-bottom:10px}.search-row input{width:100%;border:1px solid var(--line);border-radius:8px;padding:9px 10px;color:var(--ink);background:#fff}.shown{color:var(--muted);font-size:12px;min-width:70px;text-align:right}"
        ".filters{display:flex;flex-wrap:wrap;gap:7px}.filter,.action{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:999px;padding:6px 10px;font-size:12px}.filter.active{border-color:#87c8c5;background:#eaf7f6;color:#075b61;font-weight:800}.filter span{color:var(--muted)}.actions{margin-left:auto;display:flex;gap:7px}"
        ".article-stack{display:grid;gap:10px}.article-card{border:1px solid var(--line);border-left:5px solid var(--accent);border-radius:8px;background:#fff;overflow:hidden;box-shadow:0 8px 20px rgba(16,35,63,.06)}.article-card[hidden]{display:none}.article-card summary{list-style:none;display:flex;justify-content:space-between;gap:14px;align-items:center;padding:13px 14px}.article-card summary::-webkit-details-marker{display:none}.article-card summary:hover{background:var(--soft)}"
        ".summary-main{min-width:0;display:grid;gap:5px}.article-title{font-weight:800;font-size:15px;color:#10233f}.summary-preview{color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.op-count{white-space:nowrap;color:#704308;background:#fff4df;border:1px solid #efcf91;border-radius:999px;padding:4px 8px;font-size:11px;font-weight:800}"
        ".article-body{border-top:1px solid var(--line);padding:14px}.url{font-size:12px;word-break:break-word}.url a{color:var(--accent)}.article-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:12px}.article-grid ul{margin:0;padding-left:18px}.article-grid li{margin-bottom:6px}"
        ".warnings ul{margin:0;padding-left:18px}.warning-alert{border-color:#e4c47e;background:#fff8ea}.report-foot{margin-top:16px;border-top:1px solid var(--line);padding-top:10px;color:var(--muted);font-size:12px}"
        "@media(max-width:920px){.layout{grid-template-columns:1fr}.rail,.toolbar{position:static}.actions{width:100%;margin-left:0}.article-grid{grid-template-columns:1fr}header{display:block}.status-chip{display:inline-block;margin-top:8px}}"
        "</style></head><body><main class=\"wrap\">"
        "<header>"
        f"<div><h1>{html.escape(client_name)} Content Radar</h1>"
        f"<p class=\"meta\">Run {html.escape(run_id)}. {summary_fields['analyzed_article_count']} articles analyzed across {len(source_counts)} sources.</p></div>"
        f"<div class=\"status-chip\">{html.escape(status_label)}</div>"
        "</header>"
        "<section class=\"layout\">"
        "<aside class=\"rail\">"
        "<section class=\"stats\">"
        f"<div class=\"stat\"><span>Analyzed</span><strong>{summary_fields['analyzed_article_count']}</strong></div>"
        f"<div class=\"stat\"><span>Warnings</span><strong>{summary_fields['source_error_count']}</strong></div>"
        "</section>"
        f"{warning_panel}"
        "<section class=\"panel\"><h2>Source Mix</h2><div class=\"source-grid\">"
        + "".join(
            f"<button class=\"source-stat\" type=\"button\" data-source-jump=\"{html.escape(source, quote=True)}\"><span>{html.escape(source)}</span><strong>{count}</strong></button>"
            for source, count in source_counts.items()
        )
        + "</div></section>"
        "<div class=\"panel\"><h2>Top Themes</h2><div class=\"pill-row\">"
        f"{theme_pills_html}"
        "</div></div>"
        "<div class=\"panel\"><h2>Priority Content Opportunities</h2><ol class=\"opps\">"
        f"{opportunity_items}</ol></div>"
        "</aside>"
        "<section class=\"review-pane\">"
        "<div class=\"toolbar\">"
        "<div class=\"search-row\">"
        "<input id=\"report-search\" type=\"search\" placeholder=\"Search articles, themes, CTAs, opportunities\">"
        "<span id=\"shown-count\" class=\"shown\"></span>"
        "</div>"
        "<div class=\"filters\">"
        f"{source_filter_buttons}"
        "<div class=\"actions\"><button id=\"expand-all\" class=\"action\" type=\"button\">Expand all</button><button id=\"collapse-all\" class=\"action\" type=\"button\">Collapse all</button></div>"
        "</div>"
        "</div>"
        f"<div class=\"article-stack\">{article_stack}</div>"
        f"<p class=\"report-foot\">{html.escape(footer_warning)}</p>"
        "</section>"
        "</section>"
        f"{report_script}"
        "</main></body></html>"
    )
    (report_dir / "digest.txt").write_text(txt, encoding="utf-8")
    (report_dir / "digest.md").write_text(md, encoding="utf-8")
    (report_dir / "digest.html").write_text(html_doc, encoding="utf-8")
    (report_dir / "digest_email.html").write_text(
        _email_html(
            run_id,
            summary_fields,
            source_counts,
            digest["cross_source_themes"],
            opportunity_highlights,
            digest["articles"],
            warnings_text,
            client_context,
        ),
        encoding="utf-8",
    )
    (report_dir / "digest_email.txt").write_text(
        _email_txt(
            run_id,
            summary_fields,
            source_counts,
            digest["cross_source_themes"],
            opportunity_highlights,
            digest["articles"],
            warnings_text,
            client_context,
        ),
        encoding="utf-8",
    )
    run_summary = {"run_id": run_id, "articles": len(items), "status": "ok", "source_errors": source_errors or {}, **summary_fields}
    (report_dir / "run-summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    return digest


def derive_themes(items):
    relevant_items = [item for item in items if float(item.get("client_relevance", 0.5)) >= 0.6]
    theme_items = relevant_items or items
    text_parts = []
    for item in theme_items:
        article = item.get("article", {})
        text_parts.extend(
            [
                article.get("title", ""),
                article.get("summary", ""),
                " ".join(article.get("observed_facts", [])),
                " ".join(article.get("inferred_implications", [])),
                " ".join(article.get("content_opportunities", [])),
            ]
        )
    text = " ".join(text_parts).lower()
    scored = []
    for theme, keywords in THEME_KEYWORDS.items():
        score = sum(text.count(keyword) for keyword in keywords)
        if score:
            scored.append((theme, score))
    return [theme for theme, _ in sorted(scored, key=lambda item: (-item[1], item[0]))[:5]]
