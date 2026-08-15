from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .claim_verification import validate_claim_verification


class EditorialReviewError(RuntimeError):
    pass


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


def _markdown_blocks(markdown: str, article: dict[str, Any]) -> str:
    output: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    for raw_line in markdown.splitlines() + [""]:
        line = raw_line.strip()
        if line == "[[INLINE_VISUAL]]":
            flush_paragraph()
            close_list()
            output.append(
                "<figure class=\"article-visual\">"
                f"<img src=\"{html.escape(article['inline_image'], quote=True)}\" "
                f"alt=\"{html.escape(article['inline_alt'], quote=True)}\">"
                f"<figcaption>{html.escape(article['inline_caption'])}</figcaption></figure>"
            )
        elif line.startswith("### "):
            flush_paragraph()
            close_list()
            output.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            flush_paragraph()
            close_list()
            output.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            flush_paragraph()
            if list_type != "ul":
                close_list()
                output.append("<ul>")
                list_type = "ul"
            output.append(f"<li>{_inline(line[2:])}</li>")
        elif re.match(r"^\d+\.\s", line):
            flush_paragraph()
            if list_type != "ol":
                close_list()
                output.append("<ol>")
                list_type = "ol"
            item = re.sub(r"^\d+\.\s+", "", line)
            output.append(f"<li>{_inline(item)}</li>")
        elif not line:
            flush_paragraph()
            close_list()
        else:
            paragraph.append(line)
    return "\n".join(output)


def _sources(article: dict[str, Any]) -> str:
    items = "".join(
        f"<li><a href=\"{html.escape(url, quote=True)}\" target=\"_blank\" rel=\"noreferrer\">"
        f"{html.escape(label)}</a></li>"
        for label, url in article["sources"]
    )
    return f"<details class=\"sources\"><summary>Reviewer sources</summary><ul>{items}</ul></details>"


def _brand_wordmark(*, inverse: bool = False) -> str:
    inverse_class = " brand-inverse" if inverse else ""
    return (
        f'<span class="brand-lockup{inverse_class}"><span class="brand-check" aria-hidden="true">&#10003;</span>'
        '<span class="brand-type"><span class="brand-name"><b>1099</b><span class="brand-fire">FIRE</span></span>'
        '<small>Real People. Reliable Filing.</small></span></span>'
    )


def _review_url(package: dict[str, Any], path: str) -> str:
    base_url = str(package.get("review_base_url") or "").rstrip("/")
    return f"{base_url}/{path}" if base_url else path


def _verification_label(article: dict[str, Any]) -> str:
    summary = article["_verification_summary"]
    if summary["needs_review_count"]:
        return f"{summary['needs_review_count']} factual item(s) need review"
    if summary["verified_count"]:
        return f"{summary['verified_count']} factual item(s) verified"
    return "Editorial guidance only"


def _editorial_context(package: dict[str, Any], article: dict[str, Any]) -> dict[str, Any]:
    client_name = str(package.get("client_name") or "client")
    client_id = str(package.get("client_id") or re.sub(r"[^a-z0-9]+", "-", client_name.casefold())).strip("-")
    edition_id = str(package.get("edition_id") or package.get("delivery_id") or "draft-edition")
    return {
        "schema_version": 1,
        "client_id": client_id,
        "client_name": client_name,
        "edition_id": edition_id,
        "article_slug": str(article["slug"]),
        "article_title": str(article["title"]),
        "revision_api": str(package.get("revision_api") or "/api/editorial-revisions"),
        "download_basename": str(article["slug"]),
        "voice_library_name": str(package.get("voice_library_name") or f"{client_name} voice library"),
    }


def _editorial_workspace(package: dict[str, Any], article: dict[str, Any]) -> str:
    if not package.get("editorial_editing"):
        return ""
    context_json = json.dumps(_editorial_context(package, article), ensure_ascii=True).replace("</", "<\\/")
    return f"""
    <section class="editor-workspace" data-editorial-workspace aria-label="Draft editor">
      <div class="editor-state"><span class="editor-state-mark" aria-hidden="true"></span><div><strong>Draft workspace</strong><span data-editor-status>Original draft</span></div></div>
      <div class="editor-actions">
        <button type="button" class="editor-button editor-button-primary" data-editor-action="edit">Edit draft</button>
        <button type="button" class="editor-button" data-editor-action="undo" hidden>Undo</button>
        <button type="button" class="editor-button" data-editor-action="reset" hidden>Restore original</button>
        <button type="button" class="editor-button" data-editor-action="copy" hidden>Save &amp; copy</button>
        <button type="button" class="editor-button editor-button-primary" data-editor-action="download" hidden>Save &amp; download</button>
      </div>
    </section>
    <div class="editor-dialog-backdrop" data-editor-dialog hidden>
      <section class="editor-dialog" role="dialog" aria-modal="true" aria-labelledby="editor-dialog-title">
        <button type="button" class="editor-dialog-close" data-editor-cancel aria-label="Close">&times;</button>
        <div class="eyebrow">Private editorial workspace</div>
        <h2 id="editor-dialog-title">Save this revision</h2>
        <p>Your edited copy will be saved privately in RadarWire before it is copied or downloaded.</p>
        <label class="editor-field"><span>Private review code</span><input type="password" data-editor-token autocomplete="current-password" required></label>
        <label class="editor-consent"><input type="checkbox" data-editor-voice-consent><span><strong>Approved for future voice matching</strong>RadarWire may use this finished version as a writing example for future {html.escape(str(package.get('client_name') or 'client'))} drafts.</span></label>
        <div class="editor-dialog-actions"><button type="button" class="editor-button" data-editor-cancel>Cancel</button><button type="button" class="editor-button editor-button-primary" data-editor-submit>Save revision</button></div>
        <div class="editor-error" data-editor-error role="alert" hidden></div>
      </section>
    </div>
    <div class="editor-toast" data-editor-toast role="status" aria-live="polite" hidden></div>
    <script type="application/json" id="editorial-context">{context_json}</script>
    """


def _load_article_verification(root: Path, article: dict[str, Any]) -> dict:
    verification_file = str(article.get("verification_file") or "").strip()
    if not verification_file:
        raise EditorialReviewError(f"Article {article.get('rank')} is missing verification_file")
    verification_path = _safe_file(root / verification_file, root, "claim verification ledger")
    try:
        data = json.loads(verification_path.read_text(encoding="utf-8"))
        _, summary = validate_claim_verification(
            data,
            article_id=str(article["slug"]),
            allowed_source_urls={str(url) for _label, url in article.get("sources", [])},
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise EditorialReviewError(f"Article {article.get('rank')} has an invalid verification ledger: {exc}") from exc
    article["_verification_summary"] = summary
    return summary


def _verification_totals(articles: list[dict[str, Any]]) -> dict:
    summaries = [article["_verification_summary"] for article in articles]
    return {
        "claim_count": sum(item["claim_count"] for item in summaries),
        "verified_count": sum(item["verified_count"] for item in summaries),
        "needs_review_count": sum(item["needs_review_count"] for item in summaries),
        "editorial_count": sum(item["editorial_count"] for item in summaries),
    }


def _article_page(
    package: dict[str, Any],
    article: dict[str, Any],
    body: str,
    full_body: str | None,
    previous: dict[str, Any] | None,
    following: dict[str, Any] | None,
) -> str:
    prev_link = (
        f"<a class=\"article-nav-link\" href=\"{html.escape(previous['slug'], quote=True)}.html\">"
        f"<span>Previous concept</span><strong>{html.escape(previous['title'])}</strong></a>"
        if previous
        else "<span></span>"
    )
    next_link = (
        f"<a class=\"article-nav-link next\" href=\"{html.escape(following['slug'], quote=True)}.html\">"
        f"<span>Next concept</span><strong>{html.escape(following['title'])}</strong></a>"
        if following
        else "<span></span>"
    )
    if full_body is not None:
        full_read_time = article.get("full_read_time", "Full guide")
        reading_control = (
            '<div class="reading-mode-panel" aria-label="Reading length">'
            '<div><strong>Choose your depth</strong><span>Start concise or open the complete guide.</span></div>'
            '<div class="reading-toggle" role="group" aria-label="Article length">'
            f'<button type="button" data-reading-target="short" aria-pressed="true">Quick Read <span>{html.escape(article["read_time"])}</span></button>'
            f'<button type="button" data-reading-target="full" aria-pressed="false">Full Guide <span>{html.escape(full_read_time)}</span></button>'
            '</div></div>'
        )
        article_content = (
            f'<article class="article-copy reading-copy" data-reading-copy="short">{_markdown_blocks(body, article)}</article>'
            f'<article class="article-copy reading-copy" data-reading-copy="full" hidden>{_markdown_blocks(full_body, article)}</article>'
            f'{_sources(article)}'
        )
    else:
        reading_control = ""
        article_content = f'<article class="article-copy">{_markdown_blocks(body, article)}{_sources(article)}</article>'
    editorial_workspace = _editorial_workspace(package, article)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(article['meta_description'], quote=True)}">
  <title>{html.escape(article['meta_title'])}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="reading-progress" aria-hidden="true"><span></span></div>
  <header class="site-header">
    <a class="brand" href="index.html" aria-label="1099FIRE editorial concepts home">{_brand_wordmark()}</a>
    <nav><a href="index.html">All concepts</a><a href="https://www.1099fire.com/" target="_blank" rel="noreferrer">1099FIRE.com</a></nav>
  </header>
  <main>
    <section class="article-heading">
      <div class="eyebrow">Concept {article['rank']} of {len(package['articles'])} / {html.escape(article['label'])}</div>
      <h1>{html.escape(article['title'])}</h1>
      <p class="dek">{html.escape(article['dek'])}</p>
      <div class="article-meta"><span data-active-read-time>{html.escape(article['read_time'])}</span><span>{html.escape(_verification_label(article))}</span><span>Draft for discussion</span></div>
    </section>
    {reading_control}
    {editorial_workspace}
    <section class="article-hero">
      <img src="{html.escape(article['hero'], quote=True)}" alt="{html.escape(article['hero_alt'], quote=True)}">
      <a class="continue-link" href="#article-start" aria-label="Continue to article"><span aria-hidden="true">&darr;</span></a>
    </section>
    <div class="article-layout" id="article-start">
      <div class="article-reading-area">{article_content}</div>
      <aside class="article-aside">
        <div class="aside-section"><span class="aside-label">Built for</span><p>{html.escape(article['audience'])}</p></div>
        <div class="aside-section"><span class="aside-label">Search focus</span><p>{html.escape(article['primary_keyword'])}</p></div>
        <div class="aside-cta"><h2>{html.escape(article['cta_title'])}</h2><p>{html.escape(article['cta_body'])}</p><a href="{html.escape(article['cta_url'], quote=True)}" target="_blank" rel="noreferrer">Contact 1099FIRE <span aria-hidden="true">&rarr;</span></a></div>
      </aside>
    </div>
    <nav class="article-footer-nav">{prev_link}{next_link}</nav>
  </main>
  <footer><strong>1099FIRE editorial concept review</strong><span>Educational draft. Confirm current requirements before publication.</span></footer>
  <script src="review.js"></script>
</body>
</html>"""


def _index_page(package: dict[str, Any]) -> str:
    cards = "".join(
        f"<article class=\"concept-card accent-{article['rank']}\">"
        f"<a class=\"concept-image\" href=\"{html.escape(article['slug'], quote=True)}.html?view=quick\">"
        f"<img src=\"{html.escape(article['hero'], quote=True)}\" alt=\"{html.escape(article['hero_alt'], quote=True)}\"></a>"
        f"<div class=\"concept-body\"><div class=\"eyebrow\">Concept {article['rank']} / {html.escape(article['label'])}</div>"
        f"<div class=\"verification-status\">{html.escape(_verification_label(article))}</div>"
        f"<h2><a href=\"{html.escape(article['slug'], quote=True)}.html?view=quick\">{html.escape(article['title'])}</a></h2>"
        f"<p>{html.escape(article['dek'])}</p><div class=\"concept-actions\">"
        f"<a class=\"action-primary\" href=\"{html.escape(article['slug'], quote=True)}.html?view=quick\">Quick Read <span>{html.escape(article['read_time'])}</span></a>"
        f"<a class=\"action-secondary\" href=\"{html.escape(article['slug'], quote=True)}.html?view=full\">Full Guide <span>{html.escape(article.get('full_read_time', 'Complete guide'))}</span></a>"
        "</div></div></article>"
        for article in package["articles"]
    )
    supporting_report_url = package.get("supporting_report_url")
    supporting_link = (
        f'<a href="{html.escape(str(supporting_report_url), quote=True)}" target="_blank" rel="noreferrer">Open supporting competitor research <span aria-hidden="true">&rarr;</span></a>'
        if supporting_report_url
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(package['package_dek'], quote=True)}">
  <title>{html.escape(package['client_name'])} {html.escape(package['package_title'])}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="index.html" aria-label="1099FIRE editorial concepts home">{_brand_wordmark()}</a>
    <nav><a href="https://www.1099fire.com/" target="_blank" rel="noreferrer">1099FIRE.com</a></nav>
  </header>
  <main>
    <section class="review-intro"><div><div class="eyebrow">Weekly content shortlist / {html.escape(package['current_as_of'])}</div><h1>{html.escape(package['package_title'])}</h1><p>{html.escape(package['package_dek'])}</p></div><div class="review-count"><strong>{len(package['articles'])}</strong><span>drafts ready to review</span></div></section>
    <section class="start-here"><div><span>Start here</span><strong>Choose one direction that feels most useful to your customers.</strong></div><ol><li><b>1</b> Skim the three ideas</li><li><b>2</b> Open a Quick Read</li><li><b>3</b> Reply with your pick</li></ol></section>
    <section class="concept-grid" aria-label="Editorial concepts">{cards}</section>
    <section class="review-note"><strong>For review, not publication</strong><div><p>Each concept includes original copy, source-backed drafting, SEO framing, commissioned visual mockups, and primary-source review notes. Final factual, brand, and service-language approval remain publication gates.</p>{supporting_link}</div></section>
  </main>
  <footer><strong>1099FIRE editorial concept review</strong><span>Educational drafts. Confirm current requirements before publication.</span></footer>
</body>
</html>"""


def _email_preview_page(package: dict[str, Any]) -> str:
    concepts: list[str] = []
    accents = {1: "#0a8b88", 2: "#d89a17", 3: "#e85d45"}
    for article in package["articles"]:
        hero_url = _review_url(package, article["hero"])
        quick_url = _review_url(package, f"{article['slug']}.html?view=quick")
        full_url = _review_url(package, f"{article['slug']}.html?view=full")
        accent = accents.get(int(article["rank"]), "#078f24")
        concepts.append(
            '<table class="email-concept" role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin:0 0 16px;border-collapse:separate;border-spacing:0;border:1px solid #d8e1e7;border-left:5px solid {accent};border-radius:6px;background:#ffffff;"><tr>'
            f'<td class="concept-image-cell" style="padding:18px;width:174px;vertical-align:top;"><img src="{html.escape(hero_url, quote=True)}" '
            f'alt="{html.escape(article["hero_alt"], quote=True)}" width="156" style="display:block;width:156px;height:108px;object-fit:cover;border:0;border-radius:4px;"></td>'
            '<td class="concept-copy-cell" style="padding:18px 18px 18px 0;vertical-align:top;">'
            f'<div style="font:800 11px Arial,sans-serif;color:{accent};text-transform:uppercase;">Draft {article["rank"]} &nbsp;|&nbsp; {html.escape(article["label"])}</div>'
            f'<h2 style="margin:7px 0 8px;font:700 22px/1.2 Georgia,serif;color:#15243a;">{html.escape(article["title"])}</h2>'
            f'<p style="margin:0 0 14px;font:14px/1.5 Arial,sans-serif;color:#5e6b7c;">{html.escape(article["dek"])}</p>'
            f'<a href="{html.escape(quick_url, quote=True)}" target="_blank" rel="noreferrer" style="display:inline-block;margin:0 7px 6px 0;padding:10px 13px;background:#087b36;color:#fff;text-decoration:none;font:800 13px Arial,sans-serif;border-radius:4px;">Quick Read</a>'
            f'<a href="{html.escape(full_url, quote=True)}" target="_blank" rel="noreferrer" style="display:inline-block;margin:0 0 6px;padding:9px 12px;border:1px solid #8793a1;color:#15243a;text-decoration:none;font:800 13px Arial,sans-serif;border-radius:4px;">Full Guide</a>'
            '</td></tr></table>'
        )
    index_url = _review_url(package, "index.html")
    supporting_report_url = package.get("supporting_report_url")
    supporting_link = (
        f'<a href="{html.escape(str(supporting_report_url), quote=True)}" target="_blank" rel="noreferrer" style="color:#456276;font-weight:700;text-decoration:underline;">View the supporting competitor radar</a>'
        if supporting_report_url
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>1099FIRE weekly content shortlist</title><style>@media(max-width:620px){{.email-shell{{padding:0!important}}.email-card{{border-radius:0!important}}.email-pad{{padding-left:20px!important;padding-right:20px!important}}.concept-image-cell,.concept-copy-cell{{display:block!important;width:auto!important;padding:16px!important}}.concept-image-cell img{{width:100%!important;height:auto!important;max-height:210px!important}}}}</style></head>
<body style="margin:0;background:#e9f0ee;color:#15243a;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">Three blog drafts are ready. Start with a Quick Read and reply with your preferred direction.</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#e9f0ee;"><tr><td class="email-shell" style="padding:28px 12px;">
    <table class="email-card" role="presentation" width="700" align="center" cellpadding="0" cellspacing="0" style="width:100%;max-width:700px;margin:0 auto;border-collapse:separate;border-spacing:0;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 12px 30px rgba(21,36,58,.10);">
      <tr><td class="email-pad" style="padding:20px 34px;background:#078f24;color:#fff;">
        <div style="font:900 28px/1 Arial,sans-serif;">&#10003;1099FIRE</div>
        <div style="margin:5px 0 0 28px;font:700 10px Arial,sans-serif;">Real People. Reliable Filing.</div>
      </td></tr>
      <tr><td class="email-pad" style="padding:34px 34px 28px;background:#153858;color:#fff;">
        <div style="font:800 11px Arial,sans-serif;color:#9edbd5;text-transform:uppercase;">Weekly content shortlist &nbsp;|&nbsp; {html.escape(package['current_as_of'])}</div>
        <h1 style="margin:10px 0 12px;font:700 36px/1.08 Georgia,serif;color:#fff;">Three blog drafts ready for your review</h1>
        <p style="margin:0;font:16px/1.55 Arial,sans-serif;color:#dce8ed;">You do not need to read everything. Start with any Quick Read below, then reply with the direction that feels most useful to your customers.</p>
      </td></tr>
      <tr><td class="email-pad" style="padding:22px 34px 6px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:0;background:#fff7df;border:1px solid #ead18a;border-radius:6px;"><tr><td style="padding:15px 17px;font:14px/1.5 Arial,sans-serif;color:#5b4617;"><strong style="color:#15243a;">Start here:</strong>&nbsp; Skim the three ideas &rarr; open one Quick Read &rarr; reply with your favorite.</td></tr></table>
      </td></tr>
      <tr><td class="email-pad" style="padding:18px 34px 10px;">
        {''.join(concepts)}
        <div style="padding:12px 0 22px;text-align:center;"><a href="{html.escape(index_url, quote=True)}" target="_blank" rel="noreferrer" style="display:inline-block;padding:13px 19px;background:#15243a;color:#fff;text-decoration:none;font:800 14px Arial,sans-serif;border-radius:4px;">Open the 3-draft review hub</a></div>
      </td></tr>
      <tr><td class="email-pad" style="padding:20px 34px;background:#f2f6f6;font:13px/1.55 Arial,sans-serif;color:#5e6b7c;"><strong style="display:block;margin-bottom:5px;color:#15243a;">Want to see why these topics rose to the top?</strong>{supporting_link}<div style="margin-top:14px;padding-top:14px;border-top:1px solid #d8e1e7;font-size:11px;">Drafts for discussion, not publication. Confirm current requirements and approved service language before posting.</div></td></tr>
    </table>
  </td></tr></table>
</body>
</html>"""


def _email_preview_text(package: dict[str, Any]) -> str:
    lines = [
        "1099FIRE WEEKLY CONTENT SHORTLIST",
        "",
        "Three blog drafts are ready for review.",
        "Start here: skim the ideas, open one Quick Read, then reply with your favorite.",
        "",
    ]
    for article in package["articles"]:
        slug = str(article["slug"])
        lines.extend(
            [
                f"DRAFT {article['rank']}: {article['title']}",
                str(article["dek"]),
                f"Quick Read: {_review_url(package, f'{slug}.html?view=quick')}",
                f"Full Guide: {_review_url(package, f'{slug}.html?view=full')}",
                "",
            ]
        )
    lines.extend(["Review all three drafts:", _review_url(package, "index.html")])
    if package.get("supporting_report_url"):
        lines.extend(["", "Supporting competitor radar:", str(package["supporting_report_url"])])
    lines.extend(["", "Drafts for discussion, not publication."])
    return "\n".join(lines) + "\n"


def _email_preview_metadata(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "delivery_id": package.get("delivery_id"),
        "subject": package.get("email_subject") or f"{package['client_name']}: {len(package['articles'])} blog drafts ready for review",
        "concept_count": len(package["articles"]),
        "review_url": _review_url(package, "index.html"),
        "supporting_report_url": package.get("supporting_report_url"),
        "claim_verification": _verification_totals(package["articles"]),
        "html_artifact": "email-preview.html",
        "text_artifact": "email-preview.txt",
        "sends_email": False,
    }


STYLES = """:root{--ink:#15243a;--muted:#5e6b7c;--line:#d8e1e7;--paper:#ffffff;--wash:#f4f7f8;--navy:#153858;--teal:#0a8b88;--coral:#ed6549;--gold:#e7ad2f;--shadow:0 14px 36px rgba(21,36,58,.09)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.68 Aptos,"Segoe UI",Arial,sans-serif;letter-spacing:0}a{color:inherit}img{display:block;max-width:100%}.site-header{height:68px;padding:0 clamp(20px,5vw,72px);display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);background:#fff;position:relative;z-index:3}.brand{text-decoration:none;font-size:23px;font-weight:800;letter-spacing:0}.brand b{color:var(--navy)}.brand span{color:var(--coral)}.site-header nav{display:flex;gap:24px}.site-header nav a{text-decoration:none;color:var(--muted);font-size:14px;font-weight:700}.site-header nav a:hover{color:var(--teal)}main{min-height:calc(100vh - 136px)}.eyebrow{font-size:12px;font-weight:800;text-transform:uppercase;color:var(--teal);letter-spacing:.08em}.review-intro{min-height:300px;padding:64px clamp(20px,6vw,90px) 50px;background:var(--navy);color:#fff;display:grid;grid-template-columns:minmax(0,760px) 180px;gap:40px;align-items:end}.review-intro .eyebrow{color:#91ddd8}.review-intro h1{font:700 clamp(42px,6vw,74px)/1.02 Georgia,serif;letter-spacing:0;margin:14px 0 18px}.review-intro p{font-size:19px;color:#d9e8ee;margin:0;max-width:740px}.review-count{border-left:4px solid var(--coral);padding-left:20px}.review-count strong{display:block;font:700 64px/1 Georgia,serif;color:#fff}.review-count span{color:#cbdde5}.concept-grid{padding:42px clamp(20px,6vw,90px) 64px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px;background:var(--wash)}.concept-card{background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column;min-width:0}.concept-card.accent-1{border-top:5px solid var(--teal)}.concept-card.accent-2{border-top:5px solid var(--gold)}.concept-card.accent-3{border-top:5px solid var(--coral)}.concept-image{aspect-ratio:16/9;overflow:hidden;background:#e8eef1}.concept-image img{width:100%;height:100%;object-fit:cover;transition:transform .25s ease}.concept-image:hover img{transform:scale(1.015)}.concept-body{padding:22px;display:flex;flex-direction:column;flex:1}.concept-body h2{font:700 25px/1.16 Georgia,serif;letter-spacing:0;margin:10px 0 12px}.concept-body h2 a{text-decoration:none}.concept-body p{color:var(--muted);margin:0 0 22px}.concept-footer{margin-top:auto;padding-top:16px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;font-size:13px;color:var(--muted)}.concept-footer a{font-weight:800;color:var(--teal);text-decoration:none}.review-note{padding:36px clamp(20px,6vw,90px);display:grid;grid-template-columns:220px minmax(0,760px);gap:30px;border-top:1px solid var(--line)}.review-note strong{font:700 22px/1.2 Georgia,serif}.review-note p{margin:0;color:var(--muted)}.article-hero{aspect-ratio:16/6;max-height:620px;overflow:hidden;background:#e8eef1}.article-hero img{width:100%;height:100%;object-fit:cover}.article-heading{max-width:1100px;margin:0 auto;padding:50px 28px 40px;border-bottom:1px solid var(--line)}.article-heading h1{font:700 clamp(38px,6vw,68px)/1.03 Georgia,serif;letter-spacing:0;margin:12px 0 20px;max-width:1000px}.dek{font-size:20px;line-height:1.5;color:var(--muted);max-width:820px;margin:0}.article-meta{display:flex;flex-wrap:wrap;gap:10px 24px;margin-top:24px;font-size:13px;font-weight:700;color:var(--muted)}.article-layout{max-width:1100px;margin:0 auto;padding:46px 28px 70px;display:grid;grid-template-columns:minmax(0,720px) 260px;gap:72px;align-items:start}.article-copy>p:first-child{font-size:20px;color:#34475c}.article-copy h2{font:700 32px/1.18 Georgia,serif;letter-spacing:0;margin:48px 0 14px}.article-copy h3{font-size:19px;line-height:1.3;margin:30px 0 8px}.article-copy p{margin:0 0 20px}.article-copy li{margin:0 0 10px}.article-copy ul,.article-copy ol{padding-left:24px;margin:0 0 24px}.article-visual{margin:38px 0}.article-visual img{width:100%;aspect-ratio:3/2;object-fit:cover;border-radius:8px;border:1px solid var(--line)}.article-visual figcaption{font-size:13px;color:var(--muted);margin-top:10px}.article-aside{position:sticky;top:28px;border-top:5px solid var(--gold);padding-top:18px}.aside-section{padding:0 0 18px;margin-bottom:18px;border-bottom:1px solid var(--line)}.aside-section p{margin:5px 0 0;font-size:14px}.aside-label{font-size:11px;text-transform:uppercase;font-weight:800;color:var(--muted);letter-spacing:.08em}.aside-cta{background:var(--navy);color:#fff;padding:20px;border-radius:8px}.aside-cta h2{font:700 22px/1.15 Georgia,serif;margin:0 0 10px}.aside-cta p{font-size:14px;color:#d8e5eb;margin:0 0 16px}.aside-cta a{display:inline-flex;align-items:center;gap:8px;color:#fff;font-weight:800;text-decoration:none;border-bottom:2px solid var(--coral)}.sources{margin-top:50px;padding-top:22px;border-top:1px solid var(--line)}.sources summary{cursor:pointer;font-weight:800;color:var(--teal)}.sources ul{font-size:14px}.sources a{color:var(--navy)}.article-footer-nav{max-width:1100px;margin:0 auto 70px;padding:0 28px;display:grid;grid-template-columns:1fr 1fr;gap:22px}.article-nav-link{text-decoration:none;border-top:1px solid var(--line);padding-top:18px}.article-nav-link.next{text-align:right}.article-nav-link span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;font-weight:800}.article-nav-link strong{display:block;margin-top:5px;font:700 18px/1.25 Georgia,serif}.reading-progress{position:fixed;top:0;left:0;right:0;height:3px;z-index:10}.reading-progress span{display:block;width:0;height:100%;background:var(--coral)}footer{min-height:68px;padding:18px clamp(20px,5vw,72px);display:flex;justify-content:space-between;gap:20px;align-items:center;background:var(--navy);color:#fff;font-size:13px}footer span{color:#cbdde5}@media(max-width:920px){.concept-grid{grid-template-columns:1fr 1fr}.review-intro{grid-template-columns:1fr}.review-count{display:none}.article-layout{grid-template-columns:1fr;gap:35px}.article-aside{position:static;display:grid;grid-template-columns:1fr 1fr;gap:20px}.aside-cta{grid-column:1/-1}.article-hero{aspect-ratio:16/8}.review-note{grid-template-columns:1fr}}@media(max-width:620px){.site-header{height:60px}.site-header nav a:first-child{display:none}.concept-grid{grid-template-columns:1fr;padding-top:24px}.review-intro{min-height:260px;padding-top:45px}.review-intro h1{font-size:44px}.article-heading{padding-top:34px}.article-heading h1{font-size:39px}.article-layout{padding-top:30px}.article-copy h2{font-size:28px;margin-top:38px}.article-aside{grid-template-columns:1fr}.article-footer-nav{grid-template-columns:1fr}.article-nav-link.next{text-align:left}.article-hero{aspect-ratio:4/3}.review-note{padding-top:28px}footer{align-items:flex-start;flex-direction:column}}@media print{.site-header,.reading-progress,.article-aside,.article-footer-nav,footer{display:none}.article-layout{display:block;padding-top:20px}.article-hero{max-height:360px}.article-heading{padding-top:24px}.sources{display:block}.sources summary{display:none}}
"""
STYLES += """
.reading-mode-panel{max-width:1100px;margin:0 auto;padding:24px 28px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:24px}.reading-mode-panel>div:first-child{display:flex;flex-direction:column}.reading-mode-panel strong{font:700 18px/1.25 Georgia,serif}.reading-mode-panel>div:first-child span{font-size:14px;color:var(--muted)}.reading-toggle{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:8px;overflow:hidden;min-width:330px}.reading-toggle button{min-height:54px;padding:8px 18px;border:0;background:#fff;color:var(--ink);font:700 14px/1.2 Aptos,"Segoe UI",Arial,sans-serif;letter-spacing:0;cursor:pointer}.reading-toggle button+button{border-left:1px solid var(--line)}.reading-toggle button span{display:block;margin-top:3px;color:var(--muted);font-size:12px;font-weight:600}.reading-toggle button[aria-pressed="true"]{background:var(--navy);color:#fff}.reading-toggle button[aria-pressed="true"] span{color:#d9e8ee}.reading-toggle button:focus-visible{outline:3px solid var(--gold);outline-offset:-3px}.article-reading-area{min-width:0}.reading-copy[hidden]{display:none}.reading-copy{animation:reading-in .18s ease-out}@keyframes reading-in{from{opacity:.55}to{opacity:1}}@media(max-width:620px){.reading-mode-panel{align-items:stretch;flex-direction:column}.reading-toggle{min-width:0;width:100%}.reading-toggle button{padding-left:10px;padding-right:10px}}
"""
STYLES += """
:root{--brand-green:#078f24;--brand-green-dark:#087b36;--brand-black:#101820}.site-header{height:72px}.brand{display:inline-flex;align-items:center;text-decoration:none;font-size:inherit}.brand-lockup{display:inline-flex;align-items:center;gap:8px;color:var(--brand-black)}.brand-check{display:inline-flex;align-items:center;justify-content:center;width:30px;height:24px;color:var(--brand-green);font:900 30px/1 Arial,sans-serif}.brand-type{display:flex;flex-direction:column;align-items:flex-start}.brand-name{display:flex;align-items:baseline;font:900 25px/.88 Arial,sans-serif;letter-spacing:0}.brand .brand-name b{color:var(--brand-black)}.brand .brand-fire{color:var(--brand-green)}.brand-type small{margin-top:4px;color:#505b62;font:700 8px/1 Arial,sans-serif;letter-spacing:0}.brand-inverse,.brand-inverse .brand-name b,.brand-inverse .brand-fire,.brand-inverse .brand-check,.brand-inverse .brand-type small{color:#fff}.site-header nav a:hover,.eyebrow,.concept-footer a,.sources summary{color:var(--brand-green-dark)}.review-intro .eyebrow{color:#a7e4ba}.reading-toggle button[aria-pressed="true"]{background:var(--brand-green-dark)}.reading-progress span{background:var(--brand-green)}.article-heading{max-width:1100px;padding:34px 28px 28px}.article-heading h1{font-size:54px;line-height:1.03;margin:10px 0 14px;max-width:1020px}.dek{font-size:18px;max-width:900px}.article-meta{margin-top:18px}.reading-mode-panel{padding-top:18px;padding-bottom:18px}.article-hero{position:relative;height:360px;max-height:none;aspect-ratio:auto}.article-hero img{height:100%;object-fit:cover}.continue-link{position:absolute;left:50%;bottom:16px;display:flex;align-items:center;justify-content:center;width:44px;height:44px;transform:translateX(-50%);border:2px solid #fff;border-radius:50%;background:rgba(16,24,32,.72);color:#fff;text-decoration:none;font:700 24px/1 Arial,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.2)}.continue-link:hover{background:var(--brand-green-dark)}.continue-link:focus-visible{outline:3px solid var(--gold);outline-offset:3px}.article-layout{scroll-margin-top:16px}.aside-cta{border-top:5px solid var(--brand-green);padding-top:16px}.aside-cta a{border-bottom-color:var(--brand-green)}@media(max-width:920px){.article-heading h1{font-size:46px}.article-hero{height:300px}}@media(max-width:620px){.site-header{height:66px}.brand-type small{display:none}.brand-name{font-size:21px}.brand-check{width:25px;font-size:25px}.article-heading{padding:28px 20px 22px}.article-heading h1{font-size:38px}.dek{font-size:17px}.article-meta{gap:8px 16px}.reading-mode-panel{padding:16px 20px}.article-hero{height:220px}.continue-link{bottom:12px;width:38px;height:38px;font-size:20px}}
"""
STYLES += ".brand .brand-check{color:var(--brand-green)}.brand .brand-inverse .brand-check{color:#fff}\n"
STYLES += """
.start-here{padding:22px clamp(20px,6vw,90px);display:flex;align-items:center;justify-content:space-between;gap:30px;border-bottom:1px solid var(--line);background:#fff7df}.start-here>div{display:flex;flex-direction:column}.start-here>div span{font-size:11px;font-weight:800;text-transform:uppercase;color:#8a5d00}.start-here>div strong{font:700 20px/1.3 Georgia,serif}.start-here ol{display:flex;gap:22px;list-style:none;margin:0;padding:0;color:#4f5f70;font-size:13px}.start-here li{display:flex;align-items:center;gap:7px;white-space:nowrap}.start-here li b{display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;border-radius:50%;background:var(--navy);color:#fff;font-size:12px}.concept-actions{margin-top:auto;padding-top:17px;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 1fr;gap:8px}.concept-actions a{min-height:52px;padding:9px 10px;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:5px;text-align:center;text-decoration:none;font-size:13px;font-weight:800}.concept-actions a span{display:block;font-size:10px;font-weight:600}.action-primary{background:var(--brand-green-dark);color:#fff}.action-primary span{color:#dff4e6}.action-secondary{border:1px solid var(--line);color:var(--ink);background:#fff}.action-secondary span{color:var(--muted)}.review-note>div a{display:inline-block;margin-top:12px;color:var(--brand-green-dark);font-weight:800;text-decoration:none;border-bottom:2px solid var(--gold)}@media(max-width:920px){.start-here{align-items:flex-start;flex-direction:column}.start-here ol{width:100%;justify-content:space-between}}@media(max-width:620px){.start-here ol{align-items:flex-start;flex-direction:column;gap:10px}.start-here li{white-space:normal}.concept-actions{grid-template-columns:1fr}}
"""
STYLES += ".verification-status{margin-top:10px;color:#765000;font-size:12px;font-weight:800}.article-meta .verification-status{margin:0}\n"
STYLES += """
.editor-workspace{max-width:1100px;margin:0 auto;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:1px solid var(--line);background:#eef8f0}.editor-state{display:flex;align-items:center;gap:11px;min-width:0}.editor-state-mark{width:10px;height:10px;flex:0 0 auto;border-radius:50%;background:var(--brand-green);box-shadow:0 0 0 4px rgba(7,143,36,.11)}.editor-state>div{display:flex;flex-direction:column;min-width:0}.editor-state strong{font:700 16px/1.2 Georgia,serif}.editor-state span:last-child{overflow:hidden;color:var(--muted);font-size:12px;text-overflow:ellipsis;white-space:nowrap}.editor-actions{display:flex;align-items:center;justify-content:flex-end;gap:7px;flex-wrap:wrap}.editor-button{min-height:38px;padding:8px 12px;border:1px solid #9cafb5;border-radius:5px;background:#fff;color:var(--ink);font:800 12px/1 Aptos,"Segoe UI",Arial,sans-serif;letter-spacing:0;cursor:pointer}.editor-button:hover{border-color:var(--brand-green-dark);color:var(--brand-green-dark)}.editor-button:focus-visible{outline:3px solid var(--gold);outline-offset:2px}.editor-button-primary{border-color:var(--brand-green-dark);background:var(--brand-green-dark);color:#fff}.editor-button-primary:hover{background:#056b2d;color:#fff}.editor-button[disabled]{cursor:wait;opacity:.65}.article-copy.is-editing{min-height:280px;padding:26px;border:2px solid var(--brand-green);background:#fbfffc;box-shadow:inset 0 0 0 4px rgba(7,143,36,.06);outline:0}.article-copy.is-editing:focus{border-color:var(--teal);box-shadow:inset 0 0 0 4px rgba(10,139,136,.08)}.editor-dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:20px;background:rgba(16,24,32,.68)}.editor-dialog-backdrop[hidden]{display:none!important}.editor-dialog{position:relative;width:min(100%,560px);max-height:calc(100vh - 40px);overflow:auto;padding:30px;border-radius:8px;background:#fff;box-shadow:0 24px 70px rgba(0,0,0,.28)}.editor-dialog h2{margin:7px 0 8px;font:700 31px/1.12 Georgia,serif}.editor-dialog>p{margin:0 0 22px;color:var(--muted)}.editor-dialog-close{position:absolute;top:10px;right:12px;width:36px;height:36px;border:0;background:transparent;color:var(--muted);font-size:28px;line-height:1;cursor:pointer}.editor-field{display:grid;gap:7px}.editor-field span{font-size:12px;font-weight:800}.editor-field input{width:100%;min-height:45px;padding:10px 12px;border:1px solid #9cafb5;border-radius:5px;font:16px/1 Aptos,"Segoe UI",Arial,sans-serif}.editor-field input:focus{border-color:var(--teal);outline:3px solid rgba(10,139,136,.16)}.editor-consent{display:grid;grid-template-columns:20px 1fr;gap:10px;margin:20px 0;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);cursor:pointer}.editor-consent input{width:18px;height:18px;margin:2px 0 0;accent-color:var(--brand-green-dark)}.editor-consent span{display:flex;flex-direction:column;color:var(--muted);font-size:13px}.editor-consent strong{margin-bottom:3px;color:var(--ink);font-size:14px}.editor-dialog-actions{display:flex;justify-content:flex-end;gap:8px}.editor-error{margin-top:14px;padding:10px 12px;border-left:4px solid var(--coral);background:#fff2ef;color:#7a2e20;font-size:13px;font-weight:700}.editor-toast{position:fixed;right:20px;bottom:20px;z-index:50;max-width:380px;padding:13px 16px;border-radius:6px;background:var(--navy);color:#fff;box-shadow:var(--shadow);font-size:13px;font-weight:800}.editor-toast[hidden],.editor-error[hidden],.editor-button[hidden]{display:none!important}.editor-unsaved .editor-state-mark{background:var(--gold);box-shadow:0 0 0 4px rgba(231,173,47,.16)}body.editor-dialog-open{overflow:hidden}@media(max-width:760px){.editor-workspace{align-items:flex-start;flex-direction:column;padding:14px 20px}.editor-actions{width:100%;justify-content:flex-start}.editor-button{flex:1 1 auto}.article-copy.is-editing{padding:18px}.editor-dialog{padding:25px 20px}.editor-dialog-actions{display:grid;grid-template-columns:1fr 1fr}.editor-toast{left:16px;right:16px;bottom:16px;max-width:none}}@media print{.editor-workspace,.editor-dialog-backdrop,.editor-toast{display:none!important}.article-copy.is-editing{padding:0;border:0;background:transparent;box-shadow:none}}
"""
STYLES = STYLES.replace("letter-spacing:.08em", "letter-spacing:0")


SCRIPT = """(() => { const bar = document.querySelector('.reading-progress span'); if (!bar) return; const update = () => { const max = document.documentElement.scrollHeight - innerHeight; bar.style.width = `${max > 0 ? (scrollY / max) * 100 : 0}%`; }; addEventListener('scroll', update, {passive:true}); addEventListener('resize', update); update(); })();\n"""
SCRIPT += """(() => { const buttons = [...document.querySelectorAll('[data-reading-target]')]; if (!buttons.length) return; const copies = [...document.querySelectorAll('[data-reading-copy]')]; const time = document.querySelector('[data-active-read-time]'); const activate = (mode) => { buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.readingTarget === mode))); copies.forEach((copy) => { copy.hidden = copy.dataset.readingCopy !== mode; }); const active = buttons.find((button) => button.dataset.readingTarget === mode); const activeTime = active?.querySelector('span')?.textContent; if (time && activeTime) time.textContent = activeTime; document.documentElement.dataset.readingMode = mode; dispatchEvent(new Event('resize')); }; buttons.forEach((button) => button.addEventListener('click', () => activate(button.dataset.readingTarget))); activate('short'); })();\n"""
SCRIPT += """(() => { const buttons = [...document.querySelectorAll('[data-reading-target]')]; if (!buttons.length) return; const requested = new URLSearchParams(location.search).get('view'); const initialMode = requested === 'full' ? 'full' : 'short'; const initial = buttons.find((button) => button.dataset.readingTarget === initialMode); if (initialMode === 'full') initial?.click(); buttons.forEach((button) => button.addEventListener('click', () => { const url = new URL(location.href); url.searchParams.set('view', button.dataset.readingTarget === 'full' ? 'full' : 'quick'); history.replaceState({}, '', url); })); })();\n"""
SCRIPT += r"""(() => {
  const workspace = document.querySelector('[data-editorial-workspace]');
  const contextNode = document.getElementById('editorial-context');
  if (!workspace || !contextNode) return;
  const context = JSON.parse(contextNode.textContent);
  const copies = Object.fromEntries([...document.querySelectorAll('[data-reading-copy]')].map((node) => [node.dataset.readingCopy, node]));
  if (!Object.keys(copies).length) {
    const single = document.querySelector('.article-copy');
    if (single) copies.short = single;
  }
  const originals = Object.fromEntries(Object.entries(copies).map(([mode, node]) => [mode, node.innerHTML]));
  const status = workspace.querySelector('[data-editor-status]');
  const actions = Object.fromEntries([...workspace.querySelectorAll('[data-editor-action]')].map((node) => [node.dataset.editorAction, node]));
  const dialog = document.querySelector('[data-editor-dialog]');
  const tokenInput = dialog?.querySelector('[data-editor-token]');
  const voiceConsent = dialog?.querySelector('[data-editor-voice-consent]');
  const submit = dialog?.querySelector('[data-editor-submit]');
  const error = dialog?.querySelector('[data-editor-error]');
  const toast = document.querySelector('[data-editor-toast]');
  const storageKey = `radarwire:draft:${context.client_id}:${context.edition_id}:${context.article_slug}`;
  const tokenKey = `radarwire:editor-token:${context.client_id}`;
  let editing = false;
  let pendingAction = null;
  let toastTimer = null;

  const activeMode = () => document.documentElement.dataset.readingMode === 'full' && copies.full ? 'full' : 'short';
  const activeCopy = () => copies[activeMode()];
  const safeStorage = (storage, operation, fallback = null) => { try { return operation(storage); } catch (_) { return fallback; } };
  const savedDrafts = safeStorage(localStorage, (store) => JSON.parse(store.getItem(storageKey) || '{}'), {});
  Object.entries(savedDrafts || {}).forEach(([mode, value]) => { if (copies[mode] && typeof value === 'string') copies[mode].innerHTML = value; });

  const hasChanges = () => Object.entries(copies).some(([mode, node]) => node.innerHTML !== originals[mode]);
  const announce = (message) => {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4200);
  };
  const updateStatus = (message) => {
    const changed = hasChanges();
    workspace.classList.toggle('editor-unsaved', changed);
    status.textContent = message || (changed ? 'Changes saved in this browser' : 'Original draft');
  };
  const persistLocal = () => {
    const values = Object.fromEntries(Object.entries(copies).map(([mode, node]) => [mode, node.innerHTML]));
    safeStorage(localStorage, (store) => store.setItem(storageKey, JSON.stringify(values)));
    updateStatus();
  };
  const setEditing = (enabled) => {
    editing = enabled;
    Object.values(copies).forEach((node) => {
      node.contentEditable = enabled ? 'true' : 'false';
      node.classList.toggle('is-editing', enabled);
      node.setAttribute('spellcheck', enabled ? 'true' : 'false');
    });
    actions.edit.textContent = enabled ? 'Finish editing' : 'Edit draft';
    ['undo', 'reset', 'copy', 'download'].forEach((name) => { actions[name].hidden = !enabled; });
    if (enabled) activeCopy()?.focus();
    updateStatus(enabled ? `Editing ${activeMode() === 'full' ? 'Full Guide' : 'Quick Read'}` : null);
  };
  const sanitize = (node) => {
    const clone = node.cloneNode(true);
    clone.querySelectorAll('script,style,iframe,object,embed,form,input,button').forEach((item) => item.remove());
    clone.querySelectorAll('*').forEach((item) => [...item.attributes].forEach((attribute) => {
      if (attribute.name.toLowerCase().startsWith('on')) item.removeAttribute(attribute.name);
      if (attribute.name === 'contenteditable' || attribute.name === 'spellcheck') item.removeAttribute(attribute.name);
    }));
    clone.querySelectorAll('img[src]').forEach((image) => { image.src = new URL(image.getAttribute('src'), location.href).href; });
    return clone;
  };
  const plainText = (node) => node.innerText.replace(/\n{3,}/g, '\n\n').trim();
  const wordDocument = (cleanCopy) => `<!doctype html><html><head><meta charset="utf-8"><title>${context.article_title}</title><style>body{max-width:720px;margin:48px auto;color:#15243a;font:11.5pt/1.6 Georgia,serif}h1{font-size:25pt;line-height:1.15}h2{margin-top:28px;font-size:17pt}h3{font-size:13pt}img{max-width:100%;height:auto}figcaption{color:#5e6b7c;font-size:9pt}li{margin-bottom:6px}.note{margin-bottom:30px;padding-bottom:14px;border-bottom:2px solid #078f24;color:#5e6b7c;font:9pt/1.4 Arial,sans-serif}</style></head><body><div class="note">${context.client_name} editorial revision | ${new Date().toLocaleDateString()}</div><h1>${context.article_title}</h1>${cleanCopy.innerHTML}</body></html>`;
  const downloadCopy = (cleanCopy) => {
    const blob = new Blob([wordDocument(cleanCopy)], { type: 'application/msword;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${context.download_basename}-${activeMode() === 'full' ? 'full-guide' : 'quick-read'}.doc`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  };
  const copyToClipboard = async (cleanCopy) => {
    const text = plainText(cleanCopy);
    if (navigator.clipboard && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({
        'text/plain': new Blob([text], { type: 'text/plain' }),
        'text/html': new Blob([cleanCopy.innerHTML], { type: 'text/html' }),
      })]);
      return;
    }
    await navigator.clipboard.writeText(text);
  };
  const closeDialog = () => {
    if (!dialog) return;
    dialog.hidden = true;
    document.body.classList.remove('editor-dialog-open');
    if (error) error.hidden = true;
  };
  const openDialog = (action) => {
    pendingAction = action;
    dialog.hidden = false;
    document.body.classList.add('editor-dialog-open');
    if (error) error.hidden = true;
    const existing = safeStorage(sessionStorage, (store) => store.getItem(tokenKey), '');
    tokenInput.value = existing || '';
    voiceConsent.checked = false;
    tokenInput.focus();
  };
  const saveRevision = async () => {
    const token = tokenInput.value.trim();
    if (!token) throw new Error('Enter the private review code.');
    const mode = activeMode();
    const cleanCopy = sanitize(copies[mode]);
    const originalHolder = document.createElement('div');
    originalHolder.innerHTML = originals[mode];
    const cleanOriginal = sanitize(originalHolder);
    const payload = {
      schema_version: 1,
      client_id: context.client_id,
      client_name: context.client_name,
      edition_id: context.edition_id,
      article_slug: context.article_slug,
      article_title: context.article_title,
      reading_mode: mode,
      original_html: cleanOriginal.innerHTML,
      original_text: plainText(cleanOriginal),
      edited_html: cleanCopy.innerHTML,
      edited_text: plainText(cleanCopy),
      approval_status: voiceConsent.checked ? 'approved_final' : 'submitted',
      voice_library_consent: voiceConsent.checked,
      consent_notice: 'Saved privately in RadarWire; approved versions may be used for future client voice matching.',
      source_url: location.href,
    };
    const response = await fetch(context.revision_api, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) safeStorage(sessionStorage, (store) => store.removeItem(tokenKey));
      throw new Error(result.error || `RadarWire could not save this revision (${response.status}).`);
    }
    safeStorage(sessionStorage, (store) => store.setItem(tokenKey, token));
    closeDialog();
    updateStatus(`Saved to RadarWire at ${new Date(result.saved_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`);
    if (pendingAction === 'download') downloadCopy(cleanCopy);
    if (pendingAction === 'copy') await copyToClipboard(cleanCopy);
    announce(pendingAction === 'download' ? 'Saved to RadarWire and downloaded.' : 'Saved to RadarWire and copied.');
  };

  Object.values(copies).forEach((node) => node.addEventListener('input', persistLocal));
  actions.edit.addEventListener('click', () => setEditing(!editing));
  actions.undo.addEventListener('click', () => { activeCopy()?.focus(); document.execCommand('undo'); persistLocal(); });
  actions.reset.addEventListener('click', () => {
    if (!confirm(`Restore the original ${activeMode() === 'full' ? 'Full Guide' : 'Quick Read'}?`)) return;
    copies[activeMode()].innerHTML = originals[activeMode()];
    persistLocal();
    announce('Original draft restored.');
  });
  actions.copy.addEventListener('click', () => openDialog('copy'));
  actions.download.addEventListener('click', () => openDialog('download'));
  dialog?.querySelectorAll('[data-editor-cancel]').forEach((button) => button.addEventListener('click', closeDialog));
  dialog?.addEventListener('click', (event) => { if (event.target === dialog) closeDialog(); });
  submit?.addEventListener('click', async () => {
    submit.disabled = true;
    if (error) error.hidden = true;
    try { await saveRevision(); }
    catch (problem) { if (error) { error.textContent = problem.message; error.hidden = false; } }
    finally { submit.disabled = false; }
  });
  tokenInput?.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit?.click(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && dialog && !dialog.hidden) closeDialog(); });
  updateStatus();
})();
"""


def _safe_file(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise EditorialReviewError(f"{label} must stay inside the review-kit directory")
    if not resolved.is_file():
        raise EditorialReviewError(f"Missing {label}: {path}")
    return resolved


def build_editorial_review_kit(manifest_path: Path, output_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    output_dir = output_dir.resolve()
    if not manifest_path.is_file():
        raise EditorialReviewError(f"Missing review manifest: {manifest_path}")
    package = json.loads(manifest_path.read_text(encoding="utf-8"))
    articles = package.get("articles") or []
    if not 1 <= len(articles) <= 6:
        raise EditorialReviewError("Review kit requires between 1 and 6 articles")
    package["articles"] = sorted(articles, key=lambda item: int(item["rank"]))
    body_root = manifest_path.parent
    for article in package["articles"]:
        _load_article_verification(body_root, article)

    targets = [output_dir / "index.html", output_dir / "styles.css", output_dir / "review.js"]
    targets += [output_dir / f"{article['slug']}.html" for article in package["articles"]]
    if package.get("email_preview"):
        targets.extend(
            [
                output_dir / "email-preview.html",
                output_dir / "email-preview.txt",
                output_dir / "email-preview.json",
            ]
        )
    targets.append(output_dir / "review-kit-manifest.json")
    existing = [path.name for path in targets if path.exists()]
    if existing and not overwrite:
        raise EditorialReviewError(f"Refusing to overwrite existing review-kit files: {existing}")

    bodies: list[tuple[str, str | None]] = []
    for article in package["articles"]:
        body_path = _safe_file(body_root / article["body"], body_root, "article body")
        _safe_file(output_dir / article["hero"], output_dir, "hero image")
        _safe_file(output_dir / article["inline_image"], output_dir, "inline image")
        body = body_path.read_text(encoding="utf-8")
        if "[VERIFY]" in body or "[[INLINE_VISUAL]]" not in body:
            raise EditorialReviewError(f"Article {article['rank']} is not ready for review rendering")
        full_body = None
        if article.get("full_body"):
            full_body_path = _safe_file(body_root / article["full_body"], body_root, "full article body")
            full_body = full_body_path.read_text(encoding="utf-8")
            if "[VERIFY]" in full_body or "[[INLINE_VISUAL]]" not in full_body:
                raise EditorialReviewError(f"Article {article['rank']} full guide is not ready for review rendering")
        bodies.append((body, full_body))

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "styles.css").write_text(STYLES, encoding="utf-8")
    (output_dir / "review.js").write_text(SCRIPT, encoding="utf-8")
    (output_dir / "index.html").write_text(_index_page(package), encoding="utf-8")
    if package.get("email_preview"):
        (output_dir / "email-preview.html").write_text(_email_preview_page(package), encoding="utf-8")
        (output_dir / "email-preview.txt").write_text(_email_preview_text(package), encoding="utf-8")
        (output_dir / "email-preview.json").write_text(
            json.dumps(_email_preview_metadata(package), indent=2),
            encoding="utf-8",
        )
    for index, (article, body_pair) in enumerate(zip(package["articles"], bodies, strict=True)):
        body, full_body = body_pair
        previous = package["articles"][index - 1] if index else None
        following = package["articles"][index + 1] if index + 1 < len(package["articles"]) else None
        (output_dir / f"{article['slug']}.html").write_text(
            _article_page(package, article, body, full_body, previous, following),
            encoding="utf-8",
        )

    result = {
        "status": "generated",
        "article_count": len(package["articles"]),
        "email_preview": bool(package.get("email_preview")),
        "editorial_editing": bool(package.get("editorial_editing")),
        "files": [path.name for path in targets],
        "sends_email": False,
        "publishes": False,
        "deploys": False,
        "runs_discovery": False,
        "uses_sqlite": False,
        "claim_verification": _verification_totals(package["articles"]),
        "output_dir": str(output_dir),
    }
    (output_dir / "review-kit-manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def validate_editorial_review_kit(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    output_dir = output_dir.resolve()
    if not manifest_path.is_file():
        raise EditorialReviewError(f"Missing review manifest: {manifest_path}")
    package = json.loads(manifest_path.read_text(encoding="utf-8"))
    articles = sorted(package.get("articles") or [], key=lambda item: int(item["rank"]))
    if not articles:
        raise EditorialReviewError("Review manifest has no articles")
    for article in articles:
        _load_article_verification(manifest_path.parent, article)

    index_path = _safe_file(output_dir / "index.html", output_dir, "review index")
    index = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    if len(index.select(".concept-card")) != len(articles):
        raise EditorialReviewError("Review index card count does not match article count")
    if len(index.select(".verification-status")) != len(articles):
        raise EditorialReviewError("Review index is missing claim-verification status")
    if (
        index.select_one(".start-here") is None
        or len(index.select('.concept-actions a[href*="?view=quick"]')) != len(articles)
        or len(index.select('.concept-actions a[href*="?view=full"]')) != len(articles)
    ):
        raise EditorialReviewError("Review index is missing client orientation or reading actions")

    email_links_checked = 0
    if package.get("email_preview"):
        email_path = _safe_file(output_dir / "email-preview.html", output_dir, "email preview")
        email_text_path = _safe_file(output_dir / "email-preview.txt", output_dir, "email text preview")
        email_metadata_path = _safe_file(output_dir / "email-preview.json", output_dir, "email preview metadata")
        email_page = BeautifulSoup(email_path.read_text(encoding="utf-8"), "html.parser")
        if len(email_page.select(".email-concept")) != len(articles) or email_page.select_one("script") is not None:
            raise EditorialReviewError("Email preview has an invalid article count or contains JavaScript")
        if len(email_page.select('a[href*="?view=quick"]')) != len(articles):
            raise EditorialReviewError("Email preview is missing Quick Read links")
        if len(email_page.select('a[href*="?view=full"]')) != len(articles):
            raise EditorialReviewError("Email preview is missing Full Guide links")
        for link in email_page.select("a[href]"):
            href = link["href"]
            if href.startswith("https://"):
                if link.get("target") != "_blank" or "noreferrer" not in link.get("rel", []):
                    raise EditorialReviewError("Email preview contains an unsafe external link")
            else:
                _safe_file(output_dir / href.split("?", 1)[0], output_dir, "email preview link")
            email_links_checked += 1
        for image in email_page.select("img[src]"):
            source = image["src"]
            if source.startswith("https://"):
                continue
            _safe_file(output_dir / source, output_dir, "email preview image")
        email_text = email_text_path.read_text(encoding="utf-8")
        if any(article["title"] not in email_text for article in articles):
            raise EditorialReviewError("Email text preview is missing an article title")
        email_metadata = json.loads(email_metadata_path.read_text(encoding="utf-8"))
        if (
            email_metadata.get("concept_count") != len(articles)
            or not email_metadata.get("subject")
            or email_metadata.get("sends_email") is not False
        ):
            raise EditorialReviewError("Email preview metadata is incomplete or unsafe")

    images_checked = 0
    links_checked = 0
    for article in articles:
        page_path = _safe_file(output_dir / f"{article['slug']}.html", output_dir, "article page")
        raw = page_path.read_text(encoding="utf-8")
        if "[VERIFY]" in raw or "â" in raw or "Ã" in raw:
            raise EditorialReviewError(f"Article {article['rank']} contains unresolved or damaged text")
        page = BeautifulSoup(raw, "html.parser")
        copies = page.select(".article-copy")
        expected_copy_count = 2 if article.get("full_body") else 1
        if len(page.select("h1")) != 1 or len(copies) != expected_copy_count:
            raise EditorialReviewError(f"Article {article['rank']} has an incomplete heading structure")
        if any(len(copy.select("h2")) < 5 for copy in copies):
            raise EditorialReviewError(f"Article {article['rank']} has an incomplete heading structure")
        if page.select_one('meta[name="viewport"]') is None:
            raise EditorialReviewError(f"Article {article['rank']} is missing responsive viewport metadata")
        if package.get("editorial_editing"):
            if (
                page.select_one("[data-editorial-workspace]") is None
                or page.select_one("#editorial-context") is None
                or page.select_one('[data-editor-action="download"]') is None
                or page.select_one("[data-editor-voice-consent]") is None
            ):
                raise EditorialReviewError(f"Article {article['rank']} is missing the private editorial workspace")
        if any(
            re.search(
                r"TaxBandits|Tax1099|BoomTax|eFileMyForms|Sovos|Avalara",
                copy.get_text(" "),
                flags=re.IGNORECASE,
            )
            for copy in copies
        ):
            raise EditorialReviewError(f"Article {article['rank']} contains competitor branding in client prose")
        if article.get("full_body"):
            mode_buttons = page.select("[data-reading-target]")
            short_copy = page.select_one('[data-reading-copy="short"]')
            full_copy = page.select_one('[data-reading-copy="full"]')
            if (
                len(mode_buttons) != 2
                or short_copy is None
                or short_copy.has_attr("hidden")
                or full_copy is None
                or not full_copy.has_attr("hidden")
            ):
                raise EditorialReviewError(f"Article {article['rank']} has an invalid reading-mode control")
        page_images = page.select("img")
        image_sources = {image.get("src", "") for image in page_images}
        if len(image_sources) != 2:
            raise EditorialReviewError(f"Article {article['rank']} must render one hero and one inline image")
        for image in page_images:
            source = image.get("src", "")
            if not image.get("alt", "").strip() or "rejected" in source.casefold():
                raise EditorialReviewError(f"Article {article['rank']} contains an unapproved image reference")
            _safe_file(output_dir / source, output_dir, "article image")
        images_checked += len(image_sources)
        for link in page.select('a[href$=".html"]:not([href^="http"])'):
            _safe_file(output_dir / link["href"], output_dir, "internal review link")
            links_checked += 1
        for link in page.select('a[href^="https://"]'):
            if link.get("target") != "_blank" or "noreferrer" not in link.get("rel", []):
                raise EditorialReviewError(f"Article {article['rank']} contains an unsafe external link")
            links_checked += 1

    styles = _safe_file(output_dir / "styles.css", output_dir, "review styles").read_text(encoding="utf-8")
    if "@media(max-width:920px)" not in styles or "@media(max-width:620px)" not in styles:
        raise EditorialReviewError("Review styles are missing required responsive breakpoints")
    if "letter-spacing:-" in styles or "gradient(" in styles:
        raise EditorialReviewError("Review styles contain prohibited typography or gradient treatment")
    script = _safe_file(output_dir / "review.js", output_dir, "review script").read_text(encoding="utf-8")
    if any(article.get("full_body") for article in articles) and "URLSearchParams" not in script:
        raise EditorialReviewError("Review script is missing direct reading-mode link support")

    build_manifest = json.loads(
        _safe_file(output_dir / "review-kit-manifest.json", output_dir, "review build manifest").read_text(
            encoding="utf-8"
        )
    )
    side_effect_keys = ("sends_email", "publishes", "deploys", "runs_discovery", "uses_sqlite")
    if any(build_manifest.get(key) for key in side_effect_keys):
        raise EditorialReviewError("Review build manifest contains an unsafe side-effect declaration")
    return {
        "status": "ok",
        "article_count": len(articles),
        "page_count": len(articles) + 1,
        "images_checked": images_checked,
        "links_checked": links_checked,
        "responsive_breakpoints": [920, 620],
        "dual_length_articles": sum(1 for article in articles if article.get("full_body")),
        "email_preview": bool(package.get("email_preview")),
        "email_links_checked": email_links_checked,
        "claim_verification": _verification_totals(articles),
        "side_effect_flags": {key: False for key in side_effect_keys},
    }
