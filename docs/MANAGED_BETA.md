# Managed WatchNixtoons2 / AniList Sync beta (Kodi 21)

**Status:** Opt-in release channel. First-render playback and notification
behaviour was tested on Firestick 2. The new repository installation,
repository-origin association and subsequent auto-update have **not yet been
verified on physical Firesticks**. Keep Firestick 1 unchanged until then.

## First installation on the test Firestick

1. In Kodi, add the file-manager source:
   `https://genomesteve.github.io/kodi-anilist-sync/beta/managed/`
   and give it a name, such as `GenomeSteve Beta`.
2. Kodi → Add-ons → Install from ZIP file → `GenomeSteve Beta` →
   `repository.genomesteve.syncbeta-1.0.4.zip`.
3. Kodi → Add-ons → Install from repository →
   **GenomeSteve WatchNixtoons2 Managed Beta**.
4. In the repository, find **WatchNixtoons2 AniList Sync** (program add-ons)
   and **WatchNixtoons2** (video add-ons). Confirm that the offered versions
   are **0.5.5** and **0.14.24.1**, respectively.
5. **Existing manual-ZIP installations are not auto-updated by Kodi.**
   On the existing add-on's information page use **Versions** to explicitly
   select the build from **GenomeSteve WatchNixtoons2 Managed Beta**.
   This associates the installed add-on with this source. Do not uninstall
   either add-on or delete its profile, mapping, private sync, or credentials.
6. Verify first-render in-progress indicators, first-click resume, synced
   watched ticks and quiet notifications before changing other devices.
7. For each add-on, check its own **Auto-update** option after selecting
   the managed source. Do not enable auto-updates globally merely to fix
   this add-on. Conflicting third-party repository origins may require
   choosing the new source explicitly under **Versions**.

## Release safety and update policy

- The stable pre-existing `zips/` feed is unchanged.
- The opt-in managed channel is published under `beta/managed/`. Its
  `addons.xml` and `addons.xml.md5` follow Kodi's indexed-repository
  layout, and installers use canonical `addon.id-version.zip` filenames.
- All build inputs are SHA-256 approved in `tools/build_managed_repo.py`.
  Builds fail if either provider or sync archive differs from the reviewed
  v0.14.24.1/v0.5.5 packages. The public `SHA256.txt` records released
  file digests. Checksums are **not digital signatures**.
- Automatic Kodi updates apply only after a reviewed new version is
  expressly published to this feed, and only after Kodi has associated the
  installed add-on with the managed repository.
- Daily GitHub Actions reads the originally packaged
  `deklica/repo.dexe` WNT2 ZIP metadata and also the separately identified
  `christianhaitian/plugin.video.watchnixtoons2` `kodi19` source.
  It reports changes to GitHub issue #9; it never downloads or applies
  executable upstream changes to the deployed feed.
- The source versions `plugin.video.watchnixtoons2` (0.14.24) and
  `plugin.video.watchnixtoons2.kodi19` (0.3) have distinct add-on IDs:
  do not treat them as directly interchangeable.

## Rollback

The original standalone v0.5.5 and companion v0.14.24.1 ZIPs remain
available at `beta/v055/`. The old stable Kodi repository feed remains
unchanged. Existing Kodi user data must not be deleted when switching
versions. When testing a new version, preserve a copy of the previously
working ZIP and choose it from the add-on's **Versions** screen, or
reinstall that known-good ZIP if necessary.

## Verification pending

- Confirm GitHub Pages downloads `addons.xml`, ZIPs and the indexed
  repository directly on Firestick 2.
- Confirm installing the same approved versions from the repository preserves
  settings and the Kodi update origin.
- Test repository checks with an approved *future higher version* before
  claiming automatic upgrade installation works end-to-end.
- Review third-party WNT2 repository priority and auto-update settings.
