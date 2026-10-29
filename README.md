# WatchNixtoons2 → AniList Sync · Personal Kodi Repository

**Owner:** GenomeSteve  
**Version:** 0.1.0 (experimental, offline-tested only)  
**Target:** Kodi 21 Omega / Amazon Fire TV Stick 4K Gen 2.

This repo hosts an experimental Kodi background tracker that watches WatchNixtoons2 episodes and syncs completed anime episode counts to AniList, without modifying WatchNixtoons2 or using Trakt / Real-Debrid credentials.

## Install on Kodi (after GitHub Pages has been enabled)

1. Kodi → Settings → File Manager → Add source → `https://genomesteve.github.io/kodi-anilist-sync/`
2. Give it the name `GenomeSteve`.
3. Kodi → Settings → Add-ons → Install from zip file → `GenomeSteve` → `repository.genomesteve.anilist-1.0.0.zip`.
4. Kodi → Settings → Add-ons → Install from repository → `GenomeSteve Kodi Repository` → Program add-ons → `WatchNixtoons2 AniList Sync`.
5. Open the add-on, check Diagnostics, and connect AniList following the guide in `src/script.watchnixtoons.anilist/README.md`.

## GitHub setup (once only)

1. Create a **public** GitHub repository named `kodi-anilist-sync` in account `GenomeSteve`, with an initial README (the Kodi repo hosted here is not yet live).
2. Publish these files to `main`, maintaining the directory structure.
3. Repository → Settings → Pages → Build and deployment → Deploy from a branch → `main` / `(root)` → Save.
4. Wait for GitHub to show the Pages URL and confirm it serves the repository ZIP before adding it in Kodi.

## Technical details

- Kodi add-on index: `zips/addons.xml` and `zips/addons.xml.md5`.
- Updateable packages: `zips/repository.genomesteve.anilist/` and `zips/script.watchnixtoons.anilist/`.
- Sources: `src/`.
- Kodi's repository add-on uses HTTPS GitHub **raw** URLs for its update feed; GitHub Pages is only used to make the initial ZIP easy to browse in Kodi.

**Important:** This is untested against a real Firestick or AniList account. Back up Kodi first. Tokens are stored locally in Kodi settings and must never be committed to GitHub.
