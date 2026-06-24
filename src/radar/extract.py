from __future__ import annotations
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime
from dateutil import parser as dtparser
import hashlib, re
from html import unescape
@dataclass
class ExtractedArticle:
    canonical_url: str; title: str; author: str|None; published_at: datetime|None; sanitized_text: str; content_hash: str
def sanitize_text(text: str, max_chars: int = 12000) -> str:
    text=unescape(text or ""); text=re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", text); text=re.sub(r"<[^>]+>", " ", text)
    text=re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text); text=re.sub(r"\s+", " ", text).strip(); return text[:max_chars]
def hash_text(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().lower().encode("utf-8")).hexdigest()
def extract_article(html: str, url: str, max_chars: int=12000) -> ExtractedArticle:
    soup=BeautifulSoup(html, "html.parser")
    for tag in soup(["script","style","noscript","iframe","form"]): tag.decompose()
    m=soup.find("meta", property="og:title"); title=m.get("content") if m and m.get("content") else None
    if not title and soup.title: title=soup.title.get_text(" ", strip=True)
    if not title:
        h=soup.find(["h1","h2"]); title=h.get_text(" ", strip=True) if h else url
    author=None
    for attrs in [{"name":"author"},{"property":"article:author"}]:
        m=soup.find("meta", attrs)
        if m and m.get("content"): author=m.get("content"); break
    published=None
    for attrs in [{"property":"article:published_time"},{"name":"date"},{"name":"pubdate"}]:
        m=soup.find("meta", attrs)
        if m and m.get("content"):
            try: published=dtparser.parse(m.get("content")).replace(tzinfo=None)
            except Exception: pass
            break
    main=soup.find("article") or soup.find("main") or soup.body or soup
    text=sanitize_text(main.get_text(" ", strip=True), max_chars=max_chars)
    return ExtractedArticle(url, sanitize_text(title, 300), sanitize_text(author, 200) if author else None, published, text, hash_text(text))
