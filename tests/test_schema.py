"""First unit tests for the Personal Internet Vault's dedupe core.

Run:  python -m pytest tests/   (from the repo root)
Stdlib only — no extra dependencies.
"""

import unittest

from vault.schema import SavedItem, normalize_url


class NormalizeUrlTests(unittest.TestCase):
    def test_strips_tracking_params(self):
        url = "https://example.com/article?utm_source=newsletter&fbclid=abc&id=42"
        key = normalize_url(url)
        self.assertIn("id=42", key)
        self.assertNotIn("utm_source", key)
        self.assertNotIn("fbclid", key)

    def test_strips_fragment_and_lowercases_host(self):
        self.assertEqual(
            normalize_url("HTTPS://Example.COM/Watch?v=1#comments"),
            "https://example.com/Watch?v=1",
        )

    def test_dedupe_key_equal_for_equivalent_urls(self):
        a = normalize_url("https://youtu.be/abc?utm_campaign=x")
        b = normalize_url("https://youtu.be/abc?si=123#t=10")
        self.assertEqual(a, b)

    def test_distinct_pages_stay_distinct(self):
        a = normalize_url("https://example.com/p/1")
        b = normalize_url("https://example.com/p/2")
        self.assertNotEqual(a, b)

    def test_empty_and_blank(self):
        self.assertEqual(normalize_url(""), "")
        self.assertEqual(normalize_url("   "), "")


class SavedItemTests(unittest.TestCase):
    def test_normalizes_service_kind_and_tags(self):
        item = SavedItem(service=" YouTube ", kind="VIDEO", title=" Hi ",
                         url="https://example.com/x", tags=["Music", "music", " "])
        self.assertEqual(item.service, "youtube")
        self.assertEqual(item.kind, "video")
        self.assertEqual(item.title, "Hi")
        self.assertEqual(item.tags, ["music"])

    def test_url_key_uses_normalized_url(self):
        item = SavedItem(service="reddit", kind="post", title="t",
                         url="https://example.com/r/test?utm_source=x#top")
        self.assertEqual(item.url_key, normalize_url(item.url))
        self.assertNotIn("utm_source", item.url_key)

    def test_roundtrip_to_dict(self):
        item = SavedItem(service="github", kind="repo", title="repo",
                         url="https://github.com/x/y", tags=["code"])
        restored = SavedItem.from_dict(item.to_dict())
        self.assertEqual(restored.service, item.service)
        self.assertEqual(restored.url, item.url)
        self.assertEqual(restored.tags, item.tags)


if __name__ == "__main__":
    unittest.main()
