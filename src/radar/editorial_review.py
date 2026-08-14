from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


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
      <div class="article-meta"><span data-active-read-time>{html.escape(article['read_time'])}</span><span>Reviewed {html.escape(package['current_as_of'])}</span><span>Draft for discussion</span></div>
    </section>
    {reading_control}
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
    <section class="review-note"><strong>For review, not publication</strong><div><p>Each concept includes original copy, compliance-reviewed language, SEO framing, commissioned visual mockups, and primary-source notes. Final brand and service-language approval remain publication gates.</p>{supporting_link}</div></section>
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
STYLES = STYLES.replace("letter-spacing:.08em", "letter-spacing:0")


SCRIPT = """(() => { const bar = document.querySelector('.reading-progress span'); if (!bar) return; const update = () => { const max = document.documentElement.scrollHeight - innerHeight; bar.style.width = `${max > 0 ? (scrollY / max) * 100 : 0}%`; }; addEventListener('scroll', update, {passive:true}); addEventListener('resize', update); update(); })();\n"""
SCRIPT += """(() => { const buttons = [...document.querySelectorAll('[data-reading-target]')]; if (!buttons.length) return; const copies = [...document.querySelectorAll('[data-reading-copy]')]; const time = document.querySelector('[data-active-read-time]'); const activate = (mode) => { buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.readingTarget === mode))); copies.forEach((copy) => { copy.hidden = copy.dataset.readingCopy !== mode; }); const active = buttons.find((button) => button.dataset.readingTarget === mode); const activeTime = active?.querySelector('span')?.textContent; if (time && activeTime) time.textContent = activeTime; document.documentElement.dataset.readingMode = mode; dispatchEvent(new Event('resize')); }; buttons.forEach((button) => button.addEventListener('click', () => activate(button.dataset.readingTarget))); activate('short'); })();\n"""
SCRIPT += """(() => { const buttons = [...document.querySelectorAll('[data-reading-target]')]; if (!buttons.length) return; const requested = new URLSearchParams(location.search).get('view'); const initialMode = requested === 'full' ? 'full' : 'short'; const initial = buttons.find((button) => button.dataset.readingTarget === initialMode); if (initialMode === 'full') initial?.click(); buttons.forEach((button) => button.addEventListener('click', () => { const url = new URL(location.href); url.searchParams.set('view', button.dataset.readingTarget === 'full' ? 'full' : 'quick'); history.replaceState({}, '', url); })); })();\n"""


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

    body_root = manifest_path.parent
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
        "files": [path.name for path in targets],
        "sends_email": False,
        "publishes": False,
        "deploys": False,
        "runs_discovery": False,
        "uses_sqlite": False,
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

    index_path = _safe_file(output_dir / "index.html", output_dir, "review index")
    index = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    if len(index.select(".concept-card")) != len(articles):
        raise EditorialReviewError("Review index card count does not match article count")
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
        "side_effect_flags": {key: False for key in side_effect_keys},
    }
