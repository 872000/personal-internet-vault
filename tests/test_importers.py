"""Unit tests for the vault importers.

Run:  python -m pytest tests/   (from the repo root)
Stdlib only — no extra dependencies.
"""

import json
import tempfile
import unittest
from pathlib import Path

from vault.importers import spotify_saved_json


def _write_json(data):
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp)
    tmp.close()
    return tmp.name


class SpotifySavedTests(unittest.TestCase):
    def test_title_is_string_when_track_and_artist_missing(self):
        # Regression test: the title fallback used to be `[url]` (a list),
        # so an export row with no track/artist names produced a SavedItem
        # whose title was a list, not a string.
        path = _write_json({"tracks": [
            {"album": "Unknown Album", "uri": "spotify:track:abc123"},
        ]})
        items = spotify_saved_json(path)
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0].title, str)
        self.assertEqual(items[0].title,
                         "https://open.spotify.com/track/abc123")

    def test_title_is_string_when_no_uri_either(self):
        path = _write_json({"tracks": [{"album": "Unknown Album"}]})
        items = spotify_saved_json(path)
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0].title, str)
        self.assertEqual(items[0].title, "")

    def test_title_prefers_track_and_artist(self):
        path = _write_json({"tracks": [
            {"track": "Song Title", "artist": "The Artist",
             "album": "An Album", "uri": "spotify:track:xyz"},
        ]})
        items = spotify_saved_json(path)
        self.assertEqual(items[0].title, "Song Title — The Artist")
        self.assertEqual(items[0].url, "https://open.spotify.com/track/xyz")


if __name__ == "__main__":
    unittest.main()
