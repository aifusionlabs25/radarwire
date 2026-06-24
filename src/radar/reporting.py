from __future__ import annotations

import html
import json
from pathlib import Path

from .models import Analysis


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


def render_reports(run_id: str, report_dir: Path, analyses: list[Analysis], source_errors: dict | None = None) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    items = [a.result_json for a in analyses]
    articles = []
    for item, row in zip(items, analyses):
        article = dict(item["article"])
        article["content_hash"] = row.content_hash
        articles.append(article)
    summary_fields = warning_summary(source_errors, len(items))
    digest = {
        "schema_version": "radar.digest.v1",
        "run_id": run_id,
        "article_count": len(items),
        "cross_source_themes": derive_themes(items),
        "articles": articles,
        "source_errors": source_errors or {},
        **summary_fields,
    }
    manifest = {
        "run_id": run_id,
        "files": ["manifest.json", "analysis.json", "digest.json", "digest.html", "digest.txt", "digest.md", "run-summary.json"],
    }
    (report_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (report_dir / "analysis.json").write_text(json.dumps(items, indent=2), encoding="utf-8")
    (report_dir / "digest.json").write_text(json.dumps(digest, indent=2), encoding="utf-8")

    warnings_text = _warning_text(source_errors)
    txt = (
        "Competitor Content Radar\n\n"
        f"Warnings: {summary_fields['source_error_count']} across {len(summary_fields['failed_sources'])} source(s)\n"
        f"Analyzed articles: {summary_fields['analyzed_article_count']}\n\n"
        "Source warnings/errors:\n"
        f"{warnings_text}\n\n"
        + "\n\n".join(f"- {a['title']}\n  {a['url']}\n  {a['summary']}" for a in digest["articles"])
    )
    md = (
        "# Competitor Content Radar\n\n"
        f"- Warnings: **{summary_fields['source_error_count']}** across **{len(summary_fields['failed_sources'])}** source(s)\n"
        f"- Analyzed articles: **{summary_fields['analyzed_article_count']}**\n\n"
        "## Source warnings/errors\n\n"
        f"{warnings_text}\n\n"
        + "\n\n".join(f"## {a['title']}\n<{a['url']}>\n\n{a['summary']}" for a in digest["articles"])
    )
    warning_items = "".join(
        f"<li><strong>{html.escape(source)}</strong>: {html.escape(err)}</li>"
        for source, errors in sorted((source_errors or {}).items())
        for err in (errors or [])
    ) or "<li>None</li>"
    html_doc = (
        "<html><body><h1>Competitor Content Radar</h1>"
        f"<section><h2>Source warnings/errors</h2><p>Warnings: {summary_fields['source_error_count']} across {len(summary_fields['failed_sources'])} source(s). Analyzed articles: {summary_fields['analyzed_article_count']}.</p><ul>{warning_items}</ul></section>"
        + "".join(
            f"<article><h2>{html.escape(a['title'])}</h2><p><a href='{html.escape(a['url'], quote=True)}'>{html.escape(a['url'])}</a></p><p>{html.escape(a['summary'])}</p></article>"
            for a in digest["articles"]
        )
        + "</body></html>"
    )
    (report_dir / "digest.txt").write_text(txt, encoding="utf-8")
    (report_dir / "digest.md").write_text(md, encoding="utf-8")
    (report_dir / "digest.html").write_text(html_doc, encoding="utf-8")
    run_summary = {"run_id": run_id, "articles": len(items), "status": "ok", "source_errors": source_errors or {}, **summary_fields}
    (report_dir / "run-summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    return digest


def derive_themes(items):
    words = {}
    for i in items:
        for f in i.get("article", {}).get("observed_facts", []):
            for w in f.lower().split():
                if len(w) > 5:
                    words[w] = words.get(w, 0) + 1
    return [w for w, c in sorted(words.items(), key=lambda x: -x[1])[:5]]
