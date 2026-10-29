import importlib.util
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'src' / 'script.watchnixtoons.anilist'
spec = importlib.util.spec_from_file_location('watched_db', BASE / 'watched_db.py')
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)


def plugin(slug):
    return ('plugin://plugin.video.watchnixtoons2/?action=actionResolve'
            '&url=%2F' + slug.replace('-', '-') )


class TestWatchedDB(unittest.TestCase):
    def test_plain_episodes(self):
        r = db.parse_watched_url(plugin('naruto-shippuden-episode-104-english-dubbed'))
        self.assertEqual(r, {'title': 'naruto shippuden', 'season': 1, 'episode': 104})

    def test_season_marker(self):
        r = db.parse_watched_url(plugin('demon-slayer-season-2-episode-4'))
        self.assertEqual(r, {'title': 'demon slayer', 'season': 2, 'episode': 4})

    def test_sxxexx(self):
        r = db.parse_watched_url(plugin('test-anime-s02e06'))
        self.assertEqual(r, {'title': 'test anime', 'season': 2, 'episode': 6})

    def test_unrelated_plugin_rejected(self):
        self.assertIsNone(db.parse_watched_url('plugin://plugin.video.thecrew/?action=actionResolve&url=%2Fnaruto-episode-2'))

    def test_unrelated_action_rejected(self):
        self.assertIsNone(db.parse_watched_url('plugin://plugin.video.watchnixtoons2/?action=actionEpisodesMenu&url=%2Fnaruto-episode-2'))

    def test_no_episode_rejected(self):
        self.assertIsNone(db.parse_watched_url(plugin('naruto-shippuden-movie')))

    def test_encoded_url(self):
        r = db.parse_watched_url('plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=%252Fbleach-episode-37-english-subbed')
        self.assertEqual(r['episode'], 37)

    def test_recent_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = str(Path(tmp) / 'MyVideos121.db')
            cx = sqlite3.connect(file)
            cx.executescript('CREATE TABLE files (strFilename TEXT, playCount INTEGER, lastPlayed TEXT);')
            current = time.strftime('%Y-%m-%d %H:%M:%S')
            cx.execute('INSERT INTO files VALUES (?,?,?)', (plugin('naruto-episode-23'), 1, current))
            cx.execute('INSERT INTO files VALUES (?,?,?)', (plugin('naruto-episode-24'), 0, current))
            cx.execute('INSERT INTO files VALUES (?,?,?)', ('plugin://plugin.video.thecrew/?action=actionResolve&url=naruto-episode-25', 1, current))
            cx.execute('INSERT INTO files VALUES (?,?,?)', (plugin('naruto-episode-11'), 1, '2020-01-01 00:00:00'))
            cx.commit();cx.close()
            result = db.recent_watched(file)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['episode'], 23)


if __name__ == '__main__':
    unittest.main()
