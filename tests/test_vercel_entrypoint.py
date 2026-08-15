from pathlib import Path

from bs4 import BeautifulSoup


def test_vercel_root_is_a_safe_client_review_workspace():
    root = Path(__file__).resolve().parents[1]
    page = BeautifulSoup((root / "index.html").read_text(encoding="utf-8"), "html.parser")

    assert page.title.string == "RadarWire Pilot Workspace"
    assert page.select_one('meta[name="viewport"]') is not None
    assert page.select_one('meta[name="robots"][content="noindex,nofollow,noarchive"]') is not None
    assert page.select_one("h1").get_text(strip=True) == "Client review workspace"
    assert len(page.select('a[href^="https://site-export-preview.vercel.app/"]')) == 4
    assert page.select_one('a[href="https://site-export-preview.vercel.app/reports/1099fire-radar/"]') is not None
    assert len(page.select('a[href^="https://site-export-preview.vercel.app/reports/1099fire-weekly-review"]')) == 3
    script = page.select_one("script")
    assert script is not None
    assert "report-site.json" in script.get_text()
    assert 'cache: "no-store"' in script.get_text()
    assert page.select_one('img[src^="https://site-export-preview.vercel.app/"]') is not None


def test_vercel_security_headers_are_part_of_every_deployment():
    root = Path(__file__).resolve().parents[1]
    config = (root / "vercel.json").read_text(encoding="utf-8")

    for header in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "X-Robots-Tag",
    ):
        assert header in config
