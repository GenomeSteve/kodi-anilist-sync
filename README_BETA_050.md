# WatchNixtoons2 → AniList Sync v0.5.0 beta

**Development status:** 170 automated tests passing on Python 3.11 and 3.12 in GitHub Actions; device-level resume sync NOT yet verified. Do not promote to the normal Kodi repository until two-Firestick smoke tests pass.

## New features

- **Background AniList receiving**, at most once per 15 minutes. Only previously user-approved AniList mappings, exact WatchNixtoons2 URLs; at most 15 added local watched marks per round. Leaves existing ticks and AniList untouched. The old outgoing episode tracker remains active.
- **Optional private exact-episode sync** at most once per 90 seconds when Kodi is idle: exact watched tick sets (anime AND cartoons) and saved playback bookmarks. Watched sets only grow. Kodi database access stays read-only. Actual local writes exclusively via Kodi's `Files.SetFileDetails` method.
- **Active playback bookmarking** when Kodi exposes a unique, verifiable WatchNixtoons2 episode and usable duration. Capture every ~35 seconds and publish roughly every 75 seconds. When upstream Kodi metadata is missing or multiple variants appear, refuse to guess and instead wait for Kodi's saved stop bookmark.
- **Rewatch** must be explicitly selected for a particular local episode; never lower AniList progress or clear ticks. Latest verified watch *event* can win even if it deliberately seeks backwards.
- **No network blocking** of the old tracking loop. New background calls are isolated in a worker. Both new modes are OFF by default; manual v0.4 controls preserved.

## Set up private sync (requires user-created private repository)

1. On GitHub create **another repository**, e.g. `GenomeSteve/kodi-watch-state`, **Private**. Initialise with a README. Do not make your existing public Kodi source repository private.
2. Create a **fine-grained personal access token** limited to that *single private repository*, with **Contents: Read and write** and no other unnecessary permissions. Never send that token in chat or screenshots.
3. On **each** Firestick install the beta explicitly, open `WatchNixtoons2 AniList Sync → Background sync settings (beta)`, configure **the same** private `owner/repo` and token. Use **Test private connection** first (read-only). Then enable **Private watched+resume sync**. Initially also enable **Auto-restore watched ticks from AniList** only on the test device.
4. Keep the original v0.4 beta on your primary Firestick until the second-device test succeeds. Initial private sync seeds existing watched ticks but **does not assume existing local bookmarks are recent**. Create a new pause/stop to publish a fresh position.
5. Test with one episode: stop at ~6m on device A, allow its background sync, load the same anime episode list on device B, allow sync, and see if Kodi's resume prompt uses ~6m. Test a deliberate rewind and later episode completion. Verify AniList never decreases.

### Known limits

- New receiving on a Firestick still requires WatchNixtoons2 episode URLs to be discovered on that device (open that show's episode list first). Unrecognized URLs are skipped rather than fabricated.
- `Files.SetFileDetails` bookmark acceptance on Kodi 21 / WatchNixtoons2 needs **physical verification**; a successful mock RPC is not a hardware test. Kodi may show a resume prompt rather than starting automatically at the saved second.
- Partial progress may be missed while the upstream player has no reliable episode metadata; stopping playback normally gives Kodi an opportunity to save its own bookmark.
- Strong conflict ordering assumes reasonably synchronized device clocks. Offline writes are queued locally and merged using conditional GitHub file writes. When both devices play at once, avoid treating either as a definite global latest until observed.
- The private state file stores viewing activity; keep the repository **private**, and revoke tokens on any lost device. This GitHub token is locally stored in Kodi settings (not encrypted). Do not give it access to the public source repository or other repositories.
- The private GitHub contents API uses small JSON commits, subject to rate limits and GitHub token expiry. Expect eventual rather than instant consistency (roughly 1-2 minutes when idle).
- Only restored ticks with an existing matching WNT2 video URL are eligible. No data is deleted from Kodi or AniList.

## Rollback

Disable both options in Background sync settings. This disables new receiving and private state changes without disabling outgoing AniList tracking. If the beta misbehaves, reinstall v0.4.0 beta from the previous beta installer, retaining the existing add-on data; no new changes were made to the existing AniList credentials or history importer files.
