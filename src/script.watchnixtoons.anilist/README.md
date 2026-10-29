# WatchNixtoons2 → AniList Sync 0.1.0

**Experimental Kodi 21 / Fire TV Python 3 add-on. Not tested on an actual Fire TV Stick.**

A separate, small background service. It does not replace, patch or configure WatchNixtoons2, The Crew or Real-Debrid.

## Features

- Detects WatchNixtoons2 *episodes*, using Kodi's playback metadata **and** the add-on's recently-watched file modification time to avoid syncing unrelated video sources.
- Counts an episode after 85% playback (adjustable 50–95%).
- Writes to AniList using your personally authorised OAuth token.
- Does not decrease existing AniList progress.
- Auto-matches only uniquely exact first-season anime titles. Ambiguous or later seasons are queued for review.
- Lets you manually map a title to AniList and optionally subtract an episode offset for long-running / split seasons.
- Keeps pending episodes if offline or unauthorised. Ignores series you exclude.
- Uses only Kodi APIs and the Python standard library; no Real-Debrid or Trakt access.

## Installation

1. Transfer **script.watchnixtoons.anilist-0.1.0.zip** to a storage location Kodi can browse on your Firestick (for example, a trusted SMB shared folder on your home network or a local Downloads folder). It does not need extracting.
2. Kodi → Settings → Add-ons → Install from zip file → select the ZIP.
3. Open Kodi → Add-ons → Program add-ons → **WatchNixtoons2 AniList Sync**.
4. Check **View diagnostics**. The WatchNixtoons2 history file should say `FOUND` *after you have played an episode once*.
5. Select **AniList account: Connect** and complete the instructions below.

## AniList account authorisation

AniList requires an OAuth client and *does not offer a traditional TV device-code login*. The first-time sign-in is more fiddly than it should be.

1. On a **phone or PC**, visit `https://anilist.co/settings/developer` and select **Create New Application**.
2. Enter `WNT2 Fire TV Sync` for the name and **exactly** `https://anilist.co/api/v2/oauth/pin` as the redirect URL. Save the application.
3. Note its numeric **Client ID**. **Do not share or enter the Client Secret.**
4. In the Kodi add-on, choose **AniList account: Connect → Enter Client ID**, and type the numeric Client ID.
5. Open the displayed link on your phone, which has this form:
   `https://anilist.co/api/v2/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=token`
6. Approve the application. AniList's PIN page will display a lengthy **access token**. Copy it.
7. In Kodi, choose **Paste AniList access token**. The official **Amazon Fire TV mobile remote** text-entry feature may make pasting more practical than typing the long token with the physical remote. Test that its text entry works with your Fire TV first.
8. The add-on verifies your token and reports the AniList username. Never share the token, screenshot it, or paste it into a public chat.

AniList tokens are valid for about one year and give broad access to account data. They are stored **locally in Kodi add-on settings as plain text**, as Kodi does not offer a secure keychain for this add-on. Disconnect in the menu to delete the stored token. Your Firestick should not be shared with untrusted people.

## Use

1. Play an anime episode through **WatchNixtoons2** as you normally do, and watch at least 85%.
2. The sync service picks up the event automatically when playback and WatchNixtoons2's history update match.
3. A first-season anime with an unambiguous exact match should sync automatically, normally within 45 seconds if AniList is reachable.
4. For ambiguously titled anime, open **WatchNixtoons2 AniList Sync → Review unmatched series**. Search for the correct AniList entry and confirm. The queued episodes will sync after confirmation.
5. **Episode offset**: if WatchNixtoons2 labels an episode as 14 but the correct AniList season starts at episode 1, set the mapping's offset to 13. An offset is a number of episodes to **subtract**, not an AniList season number.
6. Open **View diagnostics** to inspect pending and completed event counts, or check the Kodi log for `[WNT2 AniList Sync]`.

## Limitations / important safeguards

- **Not a tested, guaranteed plug-and-play integration.** Validated for packaging, Python syntax and offline unit tests, not on a real Firestick nor a signed-in AniList account.
- WatchNixtoons2 may change its file format or playback tags in later versions. The current source examined is `christianhaitian/plugin.video.watchnixtoons2` on the `kodi19` branch.
- The `recently_watched.dat` file contains **series visits**, not a complete record of watched episode numbers. This version tracks **new playbacks only**, not your past history.
- It only synchronises episode counts. It **doesn't store exact resume position**, mark entries in WatchNixtoons2, sync to Trakt, or sync Western cartoons which have no AniList entry.
- Kodi playback metadata must expose an actual episode number; otherwise it intentionally skips the stream. Anime with complicated episode numbering need correct manual mapping and an offset.
- Distinguishing WatchNixtoons2 streams is best-effort. If source attribution is uncertain, do not assume the sync occurred. Check Diagnostics / AniList.
- The log suppresses tokens; do not share your Kodi settings directory or backups containing it.
- If Kodi is shut down before the 85% threshold is observed, nothing is queued. A mid-session crash may also lose progress.
- If a title is accidentally auto-matched, edit the mapping and correct the AniList entry yourself: the add-on will **not** automatically undo an earlier update.
- Read-only access to WatchNixtoons2 history, no modifications to that add-on's database or other add-ons' settings.

## Technical verification

- Official Kodi documentation: https://kodi.wiki/view/Service_add-ons
- Kodi scripts: https://kodi.wiki/view/HOW-TO:Script_addon
- WatchNixtoons2 source: https://github.com/christianhaitian/plugin.video.watchnixtoons2/tree/kodi19
- AniList OAuth + PIN: https://docs.anilist.co/guide/auth/
- AniList progress mutation: https://docs.anilist.co/guide/graphql/mutations

This software is supplied as-is, for tracking media you are authorised to watch.
