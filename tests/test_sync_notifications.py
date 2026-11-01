"""Sync notifications must never interrupt playback or duplicate live progress."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "script.watchnixtoons.anilist"))
import sync_notifications as alerts


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.ui = SimpleNamespace(Dialog=lambda: SimpleNamespace(
            notification=lambda *args, **kwargs: self.calls.append((args, kwargs))))
        self.addon = SimpleNamespace(getSetting=lambda key: "true")
        self.patcher = patch.object(alerts, "_BUFFER", alerts.NotificationBuffer())
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def flush(self, now=100, playing=False):
        with patch.dict(sys.modules, {"xbmcgui": self.ui}):
            alerts.flush_notifications(self.addon, is_playing=playing, now=now)

    def test_setting_is_visible_in_kodi_and_new_version(self):
        root = Path(__file__).resolve().parents[1] / "src" / "script.watchnixtoons.anilist"
        settings = ET.parse(root / "resources" / "settings.xml")
        notifications = [x for x in settings.iter("setting") if x.get("id") == "sync_notifications"]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].findtext("level"), "0")
        self.assertEqual(notifications[0].findtext("default"), "true")
        self.assertEqual(notifications[0].get("label"), "32041")
        language = (root / "resources" / "language" / "resource.language.en_gb" / "strings.po").read_text()
        self.assertIn('msgctxt "#32041"', language)
        self.assertIn('msgid "Notify when changes are sent to GitHub or AniList"', language)
        self.assertEqual(ET.parse(root / "addon.xml").getroot().get("version"), "0.5.6")

    def test_github_progress_waits_for_stop_not_live_minute_uploads(self):
        title = "/black-clover-season-2-episode-2-english-subbed"
        self.flush(now=100, playing=True)
        alerts.notify_sync(self.addon, "GitHub", [("progress", title)])
        self.flush(now=100, playing=True)
        alerts.notify_sync(self.addon, "GitHub", [("progress", title)])
        self.flush(now=160, playing=True)
        self.assertEqual(self.calls, [])
        self.flush(now=164, playing=False)
        self.assertEqual(self.calls, [])
        self.flush(now=169, playing=False)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0][1],
                         "Progress for Black Clover Season 2 Episode 2 English Subbed synced")
        self.flush(now=200, playing=False)
        self.assertEqual(len(self.calls), 1)

    def test_short_buffering_gap_never_releases_toast(self):
        self.flush(now=100, playing=True)
        alerts.notify_sync(self.addon, "GitHub", [("progress", "/naruto-episode-1")])
        self.flush(now=103, playing=False)
        self.flush(now=105, playing=True)
        self.assertFalse(self.calls)
        self.flush(now=112, playing=False)
        self.assertFalse(self.calls)
        self.flush(now=114, playing=False)
        self.assertEqual(len(self.calls), 1)

    def test_watched_wins_and_anilist_stays_separate(self):
        key = "/black-clover-season-2-episode-1-english-subbed"
        self.flush(now=100, playing=True)
        alerts.notify_sync(self.addon, "GitHub", [("progress", key)])
        alerts.notify_sync(self.addon, "GitHub", [("watched", key)])
        alerts.notify_sync(self.addon, "GitHub", [("progress", key)])
        alerts.notify_sync(self.addon, "AniList",
                           [("progress", "Black Clover Season 2 Episode 1")])
        self.flush(now=108, playing=True)
        self.assertFalse(self.calls)
        self.flush(now=117, playing=False)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("Watched status for Black Clover", self.calls[0][0][1])
        self.assertIn("Progress for Black Clover Season 2 Episode 1 synced", self.calls[1][0][1])

    def test_disabled_and_no_changes_silent(self):
        addon = SimpleNamespace(getSetting=lambda key: "false")
        alerts.notify_sync(self.addon, "GitHub", [("progress", "/naruto-episode-1")])
        alerts.flush_notifications(addon, is_playing=False, now=100)
        self.flush(now=101)
        self.assertEqual(self.calls, [])
        alerts.notify_sync(addon, "GitHub", [("progress", "/naruto-episode-2")])
        self.flush(now=110)
        self.assertEqual(self.calls, [])

    def test_batched_toasts_limited_without_duplicates(self):
        alerts.notify_sync(self.addon, "GitHub",
                           [("progress", "/show-episode-%d" % n) for n in range(1, 7)])
        alerts.notify_sync(self.addon, "GitHub", [("progress", "/show-episode-1")])
        self.flush(now=100)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.calls[-1][0][1], "3 more episode updates synced")

    def test_dub_sub_are_distinct(self):
        self.assertNotEqual(alerts._label("/black-clover-episode-1-english-subbed"),
                            alerts._label("/black-clover-episode-1-english-dubbed"))

    def test_malformed_key_does_not_leak_urls_or_tokens(self):
        self.assertEqual(alerts._label("/outside/?token=secret"), "Episode")

    def test_broken_gui_does_not_fail_upload(self):
        alerts.notify_sync(self.addon, "GitHub", [("watched", "/naruto-episode-1")])
        with patch.dict(sys.modules, {"xbmcgui": SimpleNamespace(Dialog=lambda: None)}):
            alerts.flush_notifications(self.addon, is_playing=False, now=100)


if __name__ == "__main__":
    unittest.main()
