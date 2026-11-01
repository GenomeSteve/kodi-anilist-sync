"""Fail-closed check that the 0.5.6 upgrade changes only Kodi add-on version metadata.

This verifies against the previously released, SHA-256-pinned 0.5.5 archive,
not against an unchecked archive from the latest commit.
"""
import hashlib
import io
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
from zipfile import ZipFile

OLD_SHA = "2a2543482221bda3afc9705008c778652ea00b7f77709d591f1086a1d9fb79fd"
WNT2_SHA = "baf458aa9e07257c6b331e0a28b68d7b385951660f32191707d9c223f40ff3a6"
OLD_URL = (
    "https://raw.githubusercontent.com/GenomeSteve/kodi-anilist-sync/main/"
    "beta/v055/script.watchnixtoons.anilist-0.5.5-beta.zip"
)
NEW_PACKAGE = Path("dist/script.watchnixtoons.anilist-0.5.6-beta.zip")
WNT2_PACKAGE = Path("dist/plugin.video.watchnixtoons2-0.14.24.1-sync-beta.zip")
METADATA = "script.watchnixtoons.anilist/addon.xml"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    req = urllib.request.Request(OLD_URL, headers={"User-Agent": "Kodi-Verified-Upgrade"})
    with urllib.request.urlopen(req, timeout=30) as r:
        old = r.read(2_000_001)
    assert len(old) < 2_000_001, "Original package too large"
    assert sha(old) == OLD_SHA, "0.5.5 reference package is not the approved release"
    assert sha(WNT2_PACKAGE.read_bytes()) == WNT2_SHA, "WatchNixtoons2 changed unexpectedly"

    candidate = NEW_PACKAGE.read_bytes()
    with ZipFile(io.BytesIO(old)) as previous, ZipFile(io.BytesIO(candidate)) as next_zip:
        assert previous.testzip() is None and next_zip.testzip() is None
        assert set(previous.namelist()) == set(next_zip.namelist()), "Files added or removed"
        for name in previous.namelist():
            before, after = previous.read(name), next_zip.read(name)
            if name == METADATA:
                assert after.replace(b'version="0.5.6"', b'version="0.5.5"', 1) == before, (
                    "Changes to add-on manifest beyond version number")
                x = ET.fromstring(after)
                assert x.get("id") == "script.watchnixtoons.anilist"
                assert x.get("version") == "0.5.6"
            else:
                assert before == after, "Executable or settings changed: " + name
    assert len(candidate) <= 2_000_000
    print("Only addon.xml version changed from approved 0.5.5")
    print("::notice title=Verified AniList Sync 0.5.6 SHA256::" + sha(candidate))


if __name__ == "__main__":
    main()
