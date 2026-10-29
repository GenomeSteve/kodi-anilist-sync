# Historical WatchNixtoons2 → AniList import (candidate 0.3.0)

This proposed feature is **manual and opt-in**. It does not run at Kodi startup, change the live playback synchroniser, or modify Kodi's database, WatchNixtoons2, Trakt, or Real-Debrid.

## What it will do after review and installation

1. From `Program add-ons → WatchNixtoons2 AniList Sync`, choose **Historical watched import (manual)**.
2. Confirm a **read-only** scan of Kodi's `MyVideos###.db` watched ticks.
3. Select **one anime series**. Only genuine WatchNixtoons2 `actionResolve` watched records with an unambiguous episode number are eligible; `recently_watched.dat` merely records recently opened shows and is not sufficient.
4. Accept the existing AniList mapping or select the correct AniList series manually. No automatic match or migration of existing mapping files.
5. Review the exact episode numbers, current AniList progress and proposed changes. **A second confirmation is required per series** before any AniList API mutation.
6. The importer re-fetches AniList progress immediately before writing. If it differs from the preview, it aborts and asks for another preview.

### Conservative assumptions

- AniList stores a **single progress count**, not an arbitrary set of episodes watched. Therefore the importer only advances to **contiguous, individually ticked** episodes after current AniList progress. It will not infer watching episodes 1–14 simply because Kodi marks episode 15 as watched.
- Kodi retained watched ticks only. Cleaned or lost Kodi database entries cannot be recovered from `recently_watched.dat`.
- Episode numbering, especially dubbed series and split seasons, can differ from AniList. Confirm the mapping and the offset carefully.
- Existing AniList progress is never deliberately lowered. A concurrent remote update is unlikely but possible between the final check and write; avoid importing while playing on another device.
- Existing watchlist statuses PAUSED, DROPPED and REPEATING are preserved on a partial historical import; COMPLETED is used only if the total episode count is known and AniList marks the series FINISHED.
- The scan fails closed if there are more than 25,000 matching Kodi records rather than silently importing a truncated dataset.

## Regression protection

- The background `service.py`, `watched_db.py`, `core.py`, `storage.py` and `anilist_api.py` are **unchanged** compared with v0.2.0.
- The only existing files modified are `default.py` (new opt-in menu entry) and `addon.xml` (candidate version bump).
- All new import logic lives in `history_import.py` and `historical_ui.py`, which are **not imported by the background service**.
- Automated tests cover Kodi SQLite history filtering, read-only scans, duplicates, missing episode gaps, safe offsets, AniList API confirmation, stale state, unchanged live service behaviour, and menu cancellation.
- The CI workflow runs Python unit tests and syntax checks on pull requests. It does not deploy Kodi ZIPs from feature branches.
- This candidate is intentionally left on a GitHub feature branch / draft PR and not merged into `main`, so the existing repository continues to serve v0.2.0.

**Hardware testing remains necessary** before a production release. The test suite simulates Kodi and AniList rather than using the user's Firestick or live credentials.
