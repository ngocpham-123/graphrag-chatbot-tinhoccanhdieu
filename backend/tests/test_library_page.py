"""Verify the /library route serves the library HTML shell.
Uses a minimal app with just the route, avoiding chat startup."""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient


def _make_app():
    app = FastAPI()

    @app.get("/library")
    async def serve_library():
        return FileResponse("frontend/library.html")

    return app


def test_library_file_exists():
    assert os.path.isfile("frontend/library.html")


def test_library_route_serves_html():
    client = TestClient(_make_app())
    resp = client.get("/library")
    assert resp.status_code == 200
    assert "Thư viện" in resp.text
    assert "/static/library.js" in resp.text
