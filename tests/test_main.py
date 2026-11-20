"""The page at GET /. Run: pytest tests/test_main.py

The API routes are tested in tests/test_api.py and tests/contract/.
"""
from fastapi.testclient import TestClient

from app.main import DASHBOARD_DIR, DASHBOARD_PAGE, app

EXTERNAL_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com")


def test_index_answers_html():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    if DASHBOARD_PAGE.is_file():
        assert '<div id="root"' in response.text
    else:
        assert "Watchtower is running" in response.text


def test_dashboard_assets_are_served():
    if not DASHBOARD_PAGE.is_file():
        return
    bundles = sorted((DASHBOARD_DIR / "assets").glob("*.js"))
    assert bundles, "the built page has no JavaScript bundle"
    response = TestClient(app).get(f"/assets/{bundles[0].name}")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_dashboard_loads_nothing_from_the_internet():
    """The page ships in the image; it must not pull fonts or scripts from a CDN."""
    if not DASHBOARD_PAGE.is_file():
        return
    for path in [DASHBOARD_PAGE, *(DASHBOARD_DIR / "assets").glob("*.css")]:
        text = path.read_text(encoding="utf-8")
        for host in EXTERNAL_HOSTS:
            assert host not in text, f"{path.name} loads from {host}"
