"""Outbound sync notifications must describe real uploads, not idle checks."""
import sys
import unittest
from xml.etree import ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "script.watchnixtoons.anilist"))
from sync_notifications import notify_sync, _label


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.ui = SimpleNamespace(Dialog=lambda: SimpleNamespace(
            notification=lambda *args, **kwargs: self.calls.append((args, kwargs))))
        self.addon = SimpleNamespace(getSetting=lambda key: "true")

    def test_setting_is_visible_in_kodi_and_new_version(self):
        root = Path(__file__).resolve().parents[1] / "src" / "script.watchnixtoons.anilist"
        settings = ET.parse(root / "resources" / "settings.xml")
        notifications = [x for x in settings.iter("setting") if x.get("id") == "sync_notifications"]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].findtext("level"), "0")  # 4 = internal, never visible
        self.assertEqual(notifications[0].findtext("default"), "true")
        self.assertEqual(ET.parse(root / "addon.xml").getroot().get("version"), "0.5.4")

    def test_progress_from_exact_private_key(self):
        with patch.dict(sys.modules, {"xbmcgui": self.ui}):
            notify_sync(self.addon, "GitHub",
                        [("progress", "/black-clover-season-2-episode-1-english-subbed")])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0][0], "AniList Sync: GitHub")
        self.assertEqual(self.calls[0][0][1],
                         "Progress for Black Clover Season 2 Episode 1 English Subbed synced")

    def test_anilist_confirmation(self):
        with patch.dict(sys.modules, {"xbmcgui": self.ui}):
            notify_sync(self.addon, "AniList", [("progress", "Black Clover Season 2 Episode 1")])
        self.assertIn("Black Clover Season 2 Episode 1 synced", self.calls[0][0][1])

    def test_disabled_or_no_changes_silent(self):
        addon = SimpleNamespace(getSetting=lambda key: "false")
        with patch.dict(sys.modules, {"xbmcgui": self.ui}):
            notify_sync(addon, "GitHub", [("progress", "/naruto-episode-1")])
            notify_sync(self.addon, "GitHub", [])
        self.assertEqual(self.calls, [])

    def test_duplicate_updates_and_limited_burst(self):
        updates = [("progress", "/show-episode-%d" % n) for n in range(1, 7)]
        updates.append(updates[0])
        with patch.dict(sys.modules, {"xbmcgui": self.ui}):
            notify_sync(self.addon, "GitHub", updates)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.calls[-1][0][1], "3 more episode updates synced")

    def test_dub_sub_are_distinct(self):
        self.assertNotEqual(_label("/black-clover-episode-1-english-subbed"),
                            _label("/black-clover-episode-1-english-dubbed"))

    def test_malformed_key_does_not_leak_urls_or_tokens(self):
        self.assertEqual(_label("/outside/?token=secret"), "Episode")

    def test_broken_gui_does_not_fail_upload(self):
        with patch.dict(sys.modules, {"xbmcgui": SimpleNamespace(Dialog=lambda: None)}):
            notify_sync(self.addon, "GitHub", [("watched", "/naruto-episode-1")])


if __name__ == "__main__":
    unittest.main()
