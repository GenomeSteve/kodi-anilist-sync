"""Small, best-effort Kodi toasts for confirmed outbound synchronisation.

Never display downloads, unchanged polls or failed remote writes. Display errors
must never affect saved progress, and private tokens never enter notification text.
"""
import re

MAX_TOASTS = 3


def _label(value):
    if not isinstance(value, str):
        return "Episode"
    if value.startswith("/"):
        # Private state uses exact source paths, not human-facing titles.
        # Keep dub/sub, season and episode details in the notification.
        if not re.fullmatch(r"/[a-z0-9/._%~-]{1,400}", value):
            return "Episode"
        value = value.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").title()
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return value[:95].strip() or "Episode"


def notify_sync(addon, destination, updates):
    """Notify at most three exact events, then aggregate the rest.

    updates: iterable of ('progress'|'watched', episode_source_key_or_label).
    Both the GitHub and AniList callers invoke this *after* confirmed writes.
    """
    if not updates:
        return
    try:
        if addon.getSetting("sync_notifications") == "false":
            return
    except (AttributeError, KeyError, TypeError):
        pass  # Existing profiles and older test doubles default to enabled.
    unique = []
    seen = set()
    for kind, title in updates:
        if kind not in ("progress", "watched"):
            continue
        name = _label(title)
        identity = (kind, name)
        if identity not in seen:
            seen.add(identity)
            unique.append(identity)
    if not unique:
        return
    try:
        import xbmcgui
        dialog = xbmcgui.Dialog()
        for kind, name in unique[:MAX_TOASTS]:
            text = ("Progress for " if kind == "progress" else "Watched status for ") + name + " synced"
            dialog.notification("AniList Sync: " + destination, text, time=5000, sound=False)
        if len(unique) > MAX_TOASTS:
            dialog.notification("AniList Sync: " + destination,
                                "%d more episode updates synced" % (len(unique) - MAX_TOASTS),
                                time=5000, sound=False)
    except Exception:
        # Notifications are non-critical: never retry an upload for a UI fault.
        return
