# Opt-in first-render integration for WatchNixtoons2 (Kodi 21)

**Prototype, not an installable streaming add-on.** Do not replace a user's
WatchNixtoons2 until the *installed* provider version/source tree is confirmed.
This integration targets the published `christianhaitian/plugin.video.watchnixtoons2`
`kodi19` branch's `lib/plugin.py::actionEpisodesMenu` design, which uses
`makeListItem` or `makeListItemClean`, then `xbmcplugin.addDirectoryItems`.

## Why the standalone script cannot fully achieve startup-ready menus

Kodi only knows local resume/watched entries previously registered in its
MyVideos database. A background script cannot assign metadata to episode
ListItems that the streaming plug-in has not constructed yet. Scanning or
requesting plug-in directories on startup would execute WatchNixtoons2 itself
and could reintroduce the user's earlier errors. Directly writing the Kodi
SQLite database is also unsafe.

## Proposed minimally invasive provider integration

The synchroniser's startup service first attempts a GitHub fetch, then saves
`private_snapshot.json` atomically in its local profile. This snapshot is
token-free and read-only to the streaming provider; if offline it keeps the
last successfully validated private state. No network calls occur while
rendering WatchNixtoons2 episode lists.

Copy `lib/wnt2_sync_bridge.py` into a source-matched companion WNT2 build.
Within `actionEpisodesMenu(params)`, after `listItemFunc` is selected but
before `def _episodeItemsGen()`, add:

```python
    # Read one token-free snapshot per episode list; no extra HTTP requests.
    from lib.wnt2_sync_bridge import load as _wnt2_sync_load, decorate as _wnt2_sync_decorate
    wnt2_snapshot = _wnt2_sync_load()
```

Inside `_episodeItemsGen()`, replace the original three-line sequence:

```python
            item = listItemFunc(title, url, art_dict, plot, is_folder=False, is_special=False, oldParams=None)
            item_params['url'] = url
            item_url = build_url(item_params)
```

with:

```python
            item = listItemFunc(title, url, art_dict, plot, is_folder=False, is_special=False, oldParams=None)
            item_params['url'] = url
            item_url = build_url(item_params)
            item = _wnt2_sync_decorate(item, item_url, wnt2_snapshot)
```

The original `playlist.add(item_url, item)` and
`yield (item_url, item, False)` remain unchanged.

`decorate` uses Kodi 20+ `InfoTagVideo.setPlaycount()` and
`InfoTagVideo.setResumePoint()`. It checks the exact source episode URI,
including sub/dub, against the cached private state. A local completed mark
wins. An existing meaningful local bookmark of unknown age wins over an
incoming remote bookmark. No site, add-on setting or streaming code changes.

## Device checks required before packaging

- Verify the actual installed WNT2 ID, version and SHA/source compatibility
  on **both** Firesticks. Do not assume the published branch matches.
- Test that Kodi 21 shows *in-progress* marker on first rendering the episode
  listing and *Resume from 11:30* on first press, rather than merely launching
  from 00:00. If Kodi ignores an InfoTag-only resume on first press, an
  additional provider-managed playback setup may be needed.
- Verify a newer rewind on Firestick 2 uploads and is adopted by Firestick 1.
- Test large episode lists, offline startup, malformed snapshot, local
  bookmarks, dubbed/subbed, unchanged scraping count and no extra requests.
- Provider updates could overwrite this companion integration. Keep patch
  isolated and version-specific rather than silently replacing/updating WNT2.

## Compatibility

Source example: https://github.com/christianhaitian/plugin.video.watchnixtoons2/tree/kodi19
Do not merge into the user's current stable add-on feed.
