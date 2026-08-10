"""Renderer service tests covering FastAPI endpoints with an injected stub renderer."""

import unittest

from fastapi.testclient import TestClient

from app import app, get_renderer, get_resolver


class _StubRenderer:
    def __init__(self, html="<html>painted</html>"):
        self.html = html
        self.seen = None

    def render(self, url):
        self.seen = url
        return self.html


class RenderEndpoint(unittest.TestCase):
    def setUp(self):
        self.stub = _StubRenderer()
        app.dependency_overrides[get_renderer] = lambda: self.stub
        # offline stub DNS: any host -> a public IP (overridden per-test where needed)
        app.dependency_overrides[get_resolver] = lambda: (lambda host: ["93.184.216.34"])
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_healthz_ok(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_render_returns_painted_dom(self):
        resp = self.client.post("/render", json={"url": "https://example.test/app"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["html"], "<html>painted</html>")
        self.assertEqual(self.stub.seen, "https://example.test/app")

    def test_private_ip_url_is_rejected(self):
        # host resolves to a private IP -> SSRF guard -> 400
        app.dependency_overrides[get_resolver] = lambda: (lambda host: ["10.0.0.1"])
        resp = self.client.post("/render", json={"url": "https://private.test/"})
        self.assertEqual(resp.status_code, 400)

    def test_non_http_scheme_is_rejected(self):
        resp = self.client.post("/render", json={"url": "file:///etc/passwd"})
        self.assertEqual(resp.status_code, 400)

    def test_render_failure_is_a_502(self):
        def boom():
            class _Boom:
                def render(self, url):
                    raise RuntimeError("browser crashed")
            return _Boom()

        app.dependency_overrides[get_renderer] = boom
        resp = self.client.post("/render", json={"url": "https://example.test/app"})
        self.assertEqual(resp.status_code, 502)


if __name__ == "__main__":
    unittest.main()
