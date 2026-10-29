"""Strict negative/positive cases for opt-in historical AniList importing."""
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'src' / 'script.watchnixtoons.anilist'
sys.path.insert(0, str(BASE))
from history_import import (locate_myvideos, read_history, make_plan,
                            import_confirmed, HistoryError)


def uri(slug, addon='plugin.video.watchnixtoons2', action='actionResolve'):
    return f'plugin://{addon}/?action={action}&url=%2F{slug}'


class HistoryDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'MyVideos121.db')
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript('CREATE TABLE files (idFile INTEGER PRIMARY KEY, strFilename TEXT, playCount INTEGER, lastPlayed TEXT);')

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, filename, plays=1):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO files(strFilename,playCount,lastPlayed) VALUES(?,?,?)',
                         (filename, plays, '2020-02-01 10:00:00'))

    def test_scan_old_rows_without_recent_date(self):
        self.add(uri('demon-slayer-episode-1'))
        self.add(uri('demon-slayer-episode-2'))
        rows = read_history(self.path)
        self.assertEqual(rows['demon slayer|s1']['episodes'], [1, 2])

    def test_ignore_unwatched_unrelated_addons_actions_and_movies(self):
        self.add(uri('naruto-episode-1'), 0)
        self.add(uri('naruto-episode-1', addon='plugin.video.thecrew'))
        self.add(uri('naruto-episode-1', action='actionEpisodesMenu'))
        self.add(uri('naruto-the-movie'))
        self.assertEqual(read_history(self.path), {})

    def test_deduplicate_watched_ticks(self):
        self.add(uri('bleach-episode-5'))
        self.add(uri('bleach-episode-5'))
        self.assertEqual(read_history(self.path)['bleach|s1']['episodes'], [5])

    def test_separate_seasons(self):
        self.add(uri('demon-slayer-season-2-episode-1'))
        self.add(uri('demon-slayer-episode-1'))
        self.assertEqual(len(read_history(self.path)), 2)

    def test_encoded_plugin_urls(self):
        self.add('plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=%252Fbleach-episode-10')
        self.assertEqual(read_history(self.path)['bleach|s1']['episodes'], [10])

    def test_scan_limit_fails_closed(self):
        self.add(uri('naruto-episode-1'))
        self.add(uri('naruto-episode-2'))
        with self.assertRaises(HistoryError):
            read_history(self.path, limit=1)

    def test_no_database(self):
        with self.assertRaises(HistoryError):
            read_history(self.path + '_missing')

    def test_requires_read_only_database(self):
        self.add(uri('naruto-episode-1'))
        self.assertEqual(len(read_history(self.path)), 1)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM files').fetchone()[0], 1)

    def test_version_selection(self):
        self.assertEqual(locate_myvideos(['MyVideos99.db', 'MyVideos121.db',
                                          'MyVideos8.db', 'MyVideos120.db-journal']),
                         'MyVideos121.db')
        self.assertIsNone(locate_myvideos(['MyVideos.db', 'music99.db']))


class PlanSafety(unittest.TestCase):
    def test_contiguous_from_start(self):
        p = make_plan([2, 1, 3], 0, 0, 12)
        self.assertEqual((p['before'], p['after'], p['changed']), (0, 3, True))

    def test_never_infer_missing_first_episodes(self):
        p = make_plan([5, 6, 7], 0, 0, 24)
        self.assertFalse(p['changed'])
        self.assertEqual(p['after'], 0)

    def test_never_skip_gap_in_middle(self):
        self.assertEqual(make_plan([1, 2, 4, 5], 0, 0)['after'], 2)

    def test_existing_progress_can_be_extended_with_following_episode(self):
        self.assertEqual(make_plan([9, 10, 11], 0, 8)['after'], 11)

    def test_existing_progress_never_reduced(self):
        self.assertEqual(make_plan([1, 2, 3], 0, 7)['after'], 7)

    def test_mapping_offset(self):
        self.assertEqual(make_plan([14, 15, 16], 13, 0, 12)['after'], 3)

    def test_offset_does_not_infer_earlier_episodes(self):
        self.assertEqual(make_plan([15, 16], 13, 0)['after'], 0)

    def test_reject_episode_count_mismatch_entire_series(self):
        p = make_plan([1, 2, 14], 0, 0, 12)
        self.assertFalse(p['changed'])
        self.assertIn('exceed', p['reason'])

    def test_bad_offset_fails(self):
        with self.assertRaises(HistoryError):
            make_plan([1, 2], -1, 0)

    def test_bad_data_fails(self):
        with self.assertRaises(HistoryError):
            make_plan([1, 'bad'], 0, 0)

    def test_duplicates_and_out_of_order(self):
        self.assertEqual(make_plan([3, 2, 2, 1, 3], 0, 0)['after'], 3)


class ConfirmedImport(unittest.TestCase):
    def setUp(self):
        self.group = {'title': 'naruto', 'season': 1, 'episodes': [1, 2, 3]}
        self.mapping = {'id': 77, 'offset': 0}
        self.anime = {'id': 77, 'episodes': 12, 'status': 'FINISHED',
                      'mediaListEntry': {'id': 17, 'progress': 0, 'status': 'CURRENT'}}
        self.calls = []

    def save(self, *args):
        self.calls.append(args)
        return {'progress': args[2]}

    def test_requires_explicit_consent(self):
        out = import_confirmed(self.group, self.mapping, self.anime, 'mock', False, self.save)
        self.assertEqual(out['outcome'], 'cancelled')
        self.assertFalse(self.calls)

    def test_calls_api_only_once_after_consent(self):
        out = import_confirmed(self.group, self.mapping, self.anime, 'mock', True, self.save)
        self.assertEqual(out['outcome'], 'updated')
        self.assertEqual(self.calls, [(77, 17, 3, 'CURRENT', 'mock')])

    def test_does_not_write_when_episodes_missing(self):
        self.group['episodes'] = [2, 3]
        self.assertEqual(import_confirmed(self.group, self.mapping, self.anime, 'mock', True, self.save)['outcome'], 'skipped')
        self.assertFalse(self.calls)

    def test_rejects_wrong_anime_identity(self):
        self.mapping['id'] = 71
        self.assertEqual(import_confirmed(self.group, self.mapping, self.anime, 'mock', True, self.save)['outcome'], 'skipped')
        self.assertFalse(self.calls)

    def test_ignored_or_missing_mapping(self):
        for mapping in ({'ignore': True}, None):
            self.assertEqual(import_confirmed(self.group, mapping, self.anime, 'mock', True, self.save)['outcome'], 'skipped')
        self.assertFalse(self.calls)

    def test_never_reduce_existing_progress(self):
        self.anime['mediaListEntry']['progress'] = 7
        self.assertEqual(import_confirmed(self.group, self.mapping, self.anime, 'mock', True, self.save)['outcome'], 'skipped')
        self.assertFalse(self.calls)

    def test_preserves_paused_status(self):
        self.anime['mediaListEntry']['status'] = 'PAUSED'
        import_confirmed(self.group, self.mapping, self.anime, 'mock', True, self.save)
        self.assertEqual(self.calls[0][3], 'PAUSED')

    def test_marks_complete_only_when_finished_and_all_episodes(self):
        self.group['episodes'] = list(range(1, 13))
        import_confirmed(self.group, self.mapping, self.anime, 'mock', True, self.save)
        self.assertEqual(self.calls[0][3], 'COMPLETED')

    def test_does_not_change_completed_if_no_new_progress(self):
        self.anime['mediaListEntry']['progress'] = 12
        self.anime['mediaListEntry']['status'] = 'COMPLETED'
        out = import_confirmed(self.group, self.mapping, self.anime, 'mock', True, self.save)
        self.assertEqual(out['outcome'], 'skipped')
        self.assertFalse(self.calls)

    def test_remote_api_unconfirmed_raises(self):
        with self.assertRaises(HistoryError):
            import_confirmed(self.group, self.mapping, self.anime, 'mock', True, lambda *args: {'progress': 1})


if __name__ == '__main__':
    unittest.main()
