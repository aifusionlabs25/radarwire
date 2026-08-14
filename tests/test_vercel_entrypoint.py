from pathlib import Path

from bs4 import BeautifulSoup


def test_vercel_root_is_a_safe_client_review_workspace():
    root = Path(__file__).resolve().parents[1]
    page = BeautifulSoup((root / "index.html").read_text(encoding="utf-8"), "html.parser")

    assert page.title.string == "RadarWire Pilot Workspace"
    assert page.select_one('meta[name="viewport"]') is not None
    assert page.select_one("h1").get_text(strip=True) == "Client review workspace"
    assert len(page.select('a[href^="https://site-export-preview.vercel.app/"]')) == 4
    assert page.select_one('a[href="https://site-export-preview.vercel.app/reports/1099fire-radar/"]') is not None
    script = page.select_one("script")
    assert script is not None
    assert "report-site.json" in script.get_text()
    assert 'cache: "no-store"' in script.get_text()
    assert page.select_one('img[src^="https://site-export-preview.vercel.app/"]') is not None
