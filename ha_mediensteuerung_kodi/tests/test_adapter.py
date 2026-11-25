import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appdaemon" / "apps" / "ha_mediensteuerung_kodi"))
from hmk_adapter import Media, MediaError, KodiClient, KodiSource, KodiPlayer, resolve_unique


class FakeClient:
    source_id = "kodi:test:8080"
    def __init__(self):
        self.calls = []
    def rpc(self, method, params=None):
        self.calls.append((method, params))
        return "OK"


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.movie = Media(self.client.source_id, "movie", 2092, "Matrix", 1999)

    def test_exact_title_excludes_sequels(self):
        sequel = Media(self.client.source_id, "movie", 2096, "Matrix Reloaded", 2003)
        self.assertEqual(resolve_unique([self.movie, sequel], "  MATRIX  "), self.movie)

    def test_ambiguous_title_requires_year(self):
        remake = Media(self.client.source_id, "movie", 9000, "Matrix", 2026)
        with self.assertRaises(MediaError):
            resolve_unique([self.movie, remake], "Matrix")
        self.assertEqual(resolve_unique([self.movie, remake], "Matrix", 1999), self.movie)

    def test_no_arbitrary_partial_match(self):
        with self.assertRaises(MediaError):
            resolve_unique([self.movie], "Mat")

    def test_play_uses_library_id(self):
        KodiPlayer(self.client).play(self.movie)
        self.assertEqual(self.client.calls, [("Player.Open", {"item": {"movieid": 2092}})])

    def test_source_mismatch_is_rejected(self):
        with self.assertRaises(MediaError):
            KodiPlayer(self.client).play(Media("kodi:another:8080", "movie", 2092, "Matrix"))
        self.assertEqual(self.client.calls, [])

    def test_invalid_ids_rejected(self):
        for value in (-1, 0, True, "2092", None):
            with self.assertRaises(MediaError):
                KodiSource.valid_id(value)

    def test_series_not_playable(self):
        with self.assertRaises(MediaError):
            KodiPlayer(self.client).play(Media(self.client.source_id, "series", 3, "Series"))

    def test_verify_requires_progress_of_matching_item(self):
        player = KodiPlayer(self.client)
        def state(i, seconds):
            return [{"item": {"id": i, "type": "movie"}, "speed": 1, "time": {"seconds": seconds}}]
        with patch.object(player, "get_now_playing", side_effect=[state(1, 99), state(2092, 1), state(2092, 1), state(2092, 3)]), patch("hmk_adapter.time.sleep"):
            report = player.verify(self.movie)
        self.assertTrue(report["verified"])
        self.assertEqual(len(report["samples"]), 4)

    def test_rpc_errors_are_not_success(self):
        client = KodiClient({"host": "example.invalid"})
        from io import BytesIO
        with patch.object(client.opener, "open", return_value=BytesIO(b'{"jsonrpc":"2.0","id":1,"error":{"code":-32602}}')):
            with self.assertRaises(MediaError):
                client.rpc("Player.Open")
        self.assertFalse(client.timings[0]["ok"])

if __name__ == "__main__":
    unittest.main()
