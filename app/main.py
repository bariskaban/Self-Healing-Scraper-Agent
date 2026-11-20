"""Watchtower web app. For now only a placeholder page at GET /.

The API routes and the dashboard come later (CONVENTIONS.md, project layout).
Run: uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Watchtower")

PLACEHOLDER_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Watchtower</title></head>
<body>
<h1>Watchtower is running</h1>
<p>No portals are attached yet.</p>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Placeholder until the dashboard exists."""
    return PLACEHOLDER_PAGE
