"""RemoteRenderer tests covering the HTTP client interface to the renderer service."""

import unittest

from cascade.render import RemoteRenderer, Renderer


class RemoteRendererClient(unittest.TestCase):
    def test_posts_url_and_returns_html(self):
        calls = {}

        def fake_post(url, payload, timeout, headers=None):
            calls["url"] = url
            calls["payload"] = payload
            calls["headers"] = headers
            return {"html": "<html>remote painted</html>"}

        client = RemoteRenderer("http://renderer:8080", post=fake_post)
        html = client.render("https://example.test/app")

        self.assertEqual(html, "<html>remote painted</html>")
        self.assertEqual(calls["url"], "http://renderer:8080/render")
        self.assertEqual(calls["payload"], {"url": "https://example.test/app"})
        self.assertNotIn("Authorization", calls["headers"])  # no auth by default

    def test_trailing_slash_in_base_url_is_handled(self):
        seen = {}

        def fake_post(url, payload, timeout, headers=None):
            seen["url"] = url
            return {"html": "x"}

        RemoteRenderer("http://renderer:8080/", post=fake_post).render("https://e.test/a")
        self.assertEqual(seen["url"], "http://renderer:8080/render")

    def test_attaches_id_token_when_auth_enabled(self):
        seen = {}

        def fake_post(url, payload, timeout, headers=None):
            seen["headers"] = headers
            return {"html": "x"}

        client = RemoteRenderer(
            "https://renderer-abc.run.app", post=fake_post, use_auth=True,
            id_token_fn=lambda audience: f"TOKEN-for-{audience}",
        )
        client.render("https://e.test/a")
        self.assertEqual(seen["headers"]["Authorization"],
                         "Bearer TOKEN-for-https://renderer-abc.run.app")

    def test_implements_the_renderer_protocol(self):
        self.assertIsInstance(RemoteRenderer("http://r:8080", post=lambda *a: {"html": ""}), Renderer)


if __name__ == "__main__":
    unittest.main()
