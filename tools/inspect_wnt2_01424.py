"""Verify original WatchNixtoons2 0.14.24 package before building a companion."""
import hashlib
import io
import re
import urllib.request
import zipfile
from xml.etree import ElementTree

URL = ("https://raw.githubusercontent.com/deklica/repo.dexe/master/"
       "zips/plugin.video.watchnixtoons2/plugin.video.watchnixtoons2-0.14.24.zip")
GIT_BLOB_SHA = "b6a5cbc56a3f840120fc07ed6421e540d904c2fd"

def main():
    req = urllib.request.Request(URL, headers={"User-Agent":"Kodi-Source-Compatibility-CI"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(2_000_000)
    assert len(data) < 2_000_000, "Refusing very large external archive"
    blob_sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    assert blob_sha == GIT_BLOB_SHA, "Upstream ZIP changed unexpectedly: fail closed"
    print("Verified original archive Git blob SHA", blob_sha)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        print("ZIP path sample", names[:30])
        manifests = [n for n in names if n.endswith("/addon.xml")]
        assert len(manifests)==1, manifests
        root = manifests[0][:-len("addon.xml")]
        addon = ElementTree.fromstring(z.read(root+"addon.xml"))
        print("Exact manifest", addon.attrib)
        assert addon.get("id")=="plugin.video.watchnixtoons2", addon.get("id")
        assert addon.get("version")=="0.14.24", addon.get("version")
        source = z.read(root+"lib/plugin.py").decode("utf-8-sig")
        print("SOURCE LENGTH", len(source))
        for q in ("def actionEpisodesMenu(params):",
                  "def _episodeItemsGen():",
                  "item = listItemFunc(title, url, art_dict, plot, is_folder=False, is_special=False, oldParams=None)",
                  "item_url = build_url(item_params)",
                  "xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_episodeItemsGen()))"):
            matches=source.count(q)
            print("ANCHOR", repr(q),matches)
        a=source.index("def actionEpisodesMenu(params):")
        b=source.index("def actionLatestMoviesMenu",a)
        print("EPISODE PAGE SOURCE START\n"+source[a:min(b,a+7000)])
        assert all(x in source[a:b] for x in (
                  "def _episodeItemsGen():", "item_url = build_url(item_params)",
                  "xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_episodeItemsGen()))"))
if __name__ == "__main__":
    main()
