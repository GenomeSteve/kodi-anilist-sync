# v0.4.0 candidate: cross-device watched-tick restoration

**Safety stage:** preview-first, manual only. **Do not auto-merge or enable automatic receiving until real Fire TV / Kodi 21 verification.** This feature doesn't alter the outgoing AniList background synchroniser or historical importer.

## What it does

- Firestick A continues sending completed anime episodes to AniList via the existing v0.2/v0.3 service.
- Firestick B can connect the **same AniList account** and open **Restore ticks from AniList (manual)**.
- It reads its own Kodi `MyVideos*.db` **read-only** to find existing local WatchNixtoons2 video paths.
- It optionally asks WatchNixtoons2 for an episode listing using Kodi `Files.GetDirectory`, but only for series already present in the local `recently_watched.dat` list.
- It requires an explicitly chosen AniList ID and trusted season offset, previews matched episodes, and asks for confirmation.
- Only after confirmation, it calls Kodi `Files.SetFileDetails` with `playcount:1` for each verified WNT2 URL. It never marks anything unwatched, modifies the SQLite database directly, or changes AniList history.
- After confirmation it re-fetches AniList progress and local watched data and refuses to apply stale previews. 50-write cap per series, per run. No bulk auto-apply.

## Current limits

- **Anime only**, because AniList is not a complete record of Western cartoons or individual watched episodes.
- AniList progress is a contiguous completed-through number, **not** a list of non-consecutive ticks. A progress of 8 means episodes 1..8 will be eligible. If the user skipped episode 3 and wants it unticked, they must NOT apply this plan.
- Titles/season mapping on two Firesticks are local to each device. The second Firestick may require one-off mapping confirmation.
- If Kodi doesn't have a saved URL for an unplayed episode and the WatchNixtoons2 episode-list API does not expose it, **it cannot invent a URL**. The preview will omit that episode. Opening the relevant series in WatchNixtoons2 first can help discover paths.
- JSON-RPC accepting a write is NOT proof the tick is immediately visible in the UI. Check the episode list for tick icons after the first one-series trial.
- The feature is not an automatic background receiver yet. That requires separate on-device validation and user approval. The existing outgoing AniList sync remains automatic.

## How to smoke test on Firestick (once ready)

1. Ensure you have a Kodi backup. Install the candidate on the second Firestick only after deliberately opting into beta testing.
2. Open WatchNixtoons2 and select a familiar anime series to populate local recently watched history. Prefer a series with one or two short episodes already confirmed as watched on Firestick A / AniList.
3. Open program add-on → **Restore ticks from AniList (manual)**, choose that anime, authorise the existing AniList mapping or choose the correct title.
4. In the read-only preview, check the series title, count, episode offset and EVERY proposed episode. Cancel if any episode should remain unwatched.
5. Approve a tiny batch, reopen the anime in WatchNixtoons2 and verify the ticks. Confirm outgoing AniList tracking still works normally.
6. Report the Kodi log line or a screenshot if Kodi rejects `Files.SetFileDetails`. Do not delete any databases.

## Test gate

- 102 offline automated tests across detection, SQLite read-only access, API errors, episode offsets, race conditions, cancellation and the original service regression suite.
- GitHub Actions matrix on Python 3.11 and 3.12.
- Byte-for-byte comparison with current stable background service and existing history importer.
- **Device-level tick creation and automatic receiving are intentionally not claimed as verified until physical Firestick smoke testing.**

## References

Official Kodi JSON-RPC `Files.GetDirectory` and `Files.SetFileDetails`: https://kodi.wiki/view/JSON-RPC_API/v8
