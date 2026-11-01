"""Build source-verified, opt-in paired Kodi 21 betas for WNT2 0.14.24."""
import ast
import hashlib
import io
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BASE = Path(__file__).resolve().parents[1]
SOURCE_URL = ("https://raw.githubusercontent.com/deklica/repo.dexe/master/"
              "zips/plugin.video.watchnixtoons2/plugin.video.watchnixtoons2-0.14.24.zip")
SOURCE_BLOB = "b6a5cbc56a3f840120fc07ed6421e540d904c2fd"
ORIGINAL_VERSION = "0.14.24"
PATCHED_VERSION = "0.14.24.1"
SYNC_VERSION = "0.5.3"

def pinned_upstream_zip():
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent":"Kodi-Cross-Device-Build"})
    with urllib.request.urlopen(req,timeout=30) as response:
        data = response.read(2_000_000)
    assert len(data) < 2_000_000, "Oversize original package"
    sha = hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    assert sha == SOURCE_BLOB, "Original archive does not match verified GitHub blob"
    return data

def replace_once(source, original, replacement):
    assert source.count(original) == 1, ("Missing or ambiguous source anchor", original)
    return source.replace(original, replacement, 1)

def build_provider(contents):
    root = "plugin.video.watchnixtoons2/"
    files = {}
    with zipfile.ZipFile(io.BytesIO(contents)) as original:
        names = original.namelist()
        assert names and all(name.startswith(root) and not name.startswith("/") and
                             ".." not in Path(name).parts for name in names)
        assert len(names)==len(set(names)), "Duplicate archive paths"
        for item in original.infolist():
            if item.is_dir():
                continue
            assert item.file_size < 1_500_000, "Untrusted oversized file"
            assert not item.filename.endswith(".pyc")
            files[item.filename]=original.read(item)
    addon = ET.fromstring(files[root+"addon.xml"])
    assert addon.get("id")=="plugin.video.watchnixtoons2"
    assert addon.get("version")==ORIGINAL_VERSION
    addon.set("version",PATCHED_VERSION)
    addon.set("provider-name","WNT2; optional cross-device integration")
    files[root+"addon.xml"]=ET.tostring(addon,encoding="utf-8",xml_declaration=True)
    path = root+"lib/plugin.py"
    # Source release uses CRLF in places; normalise before fail-closed anchors.
    code=files[path].decode("utf-8-sig").replace("\r\n", "\n")
    header = "    def _episodeItemsGen():"
    bridge_init = (
        "    # Optional local-only metadata: never scrape or call the sync service here.\n"
        "    try:\n"
        "        from lib.wnt2_sync_bridge import load as _sync_load, decorate as _sync_decorate\n"
        "        _sync_state = _sync_load()\n"
        "    except Exception:\n"
        "        _sync_state = {}\n"
        "        _sync_decorate = lambda item, url, state: item\n\n"
        + header)
    code=replace_once(code,header,bridge_init)
    anchor="            item_url = build_url(item_params)\n            playlist.add(item_url, item)"
    applied=(
        "            item_url = build_url(item_params)\n"
        "            # The streaming episode's original URI remains unchanged.\n"
        "            try:\n"
        "                item = _sync_decorate(item, item_url, _sync_state)\n"
        "            except Exception:\n"
        "                pass  # Never let optional sync interfere with playback.\n"
        "            playlist.add(item_url, item)"
    )
    code=replace_once(code,anchor,applied)
    ast.parse(code)
    files[path]=code.encode("utf-8")
    bridge=BASE/"integration/watchnixtoons2-kodi19/lib/wnt2_sync_bridge.py"
    ast.parse(bridge.read_text(encoding="utf-8"))
    files[root+"lib/wnt2_sync_bridge.py"]=bridge.read_bytes()
    # Source fork's ordinary media files, settings, scraper code, and IDs unchanged.
    zip_out=BASE/"dist"/("plugin.video.watchnixtoons2-"+PATCHED_VERSION+"-sync-beta.zip")
    write_zip(zip_out,files)
    # Verify round-trip original plugin IDs and metadata.
    with zipfile.ZipFile(zip_out) as check:
        assert "wnt2_sync_bridge" in check.read(path).decode()
        installed=ET.fromstring(check.read(root+"addon.xml"))
        assert installed.get("id")=="plugin.video.watchnixtoons2"
        assert installed.get("version")==PATCHED_VERSION
        assert check.testzip() is None
    return zip_out

def write_zip(path, files):
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as output:
        for name,data in sorted(files.items()):
            meta=zipfile.ZipInfo(name,date_time=(2026,10,31,0,0,0))
            meta.compress_type=zipfile.ZIP_DEFLATED
            meta.external_attr=0o644<<16
            output.writestr(meta,data)

def build_sync():
    root=BASE/"src/script.watchnixtoons.anilist"
    files={}
    for p in root.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in ("__pycache__", ".pytest_cache")) or p.suffix==".pyc":
            continue
        files["script.watchnixtoons.anilist/"+p.relative_to(root).as_posix()]=p.read_bytes()
    addon=ET.fromstring(files["script.watchnixtoons.anilist/addon.xml"])
    assert addon.get("id")=="script.watchnixtoons.anilist"
    assert addon.get("version")==SYNC_VERSION
    result=BASE/"dist"/("script.watchnixtoons.anilist-"+SYNC_VERSION+"-beta.zip")
    write_zip(result,files)
    with zipfile.ZipFile(result) as z:
        assert z.testzip() is None
        assert "script.watchnixtoons.anilist/auto_sync.py" in z.namelist()
    return result

def main():
    original = pinned_upstream_zip()
    packages=(build_provider(original),build_sync())
    for p in packages:
        raw=p.read_bytes()
        print("BUILT",p.name,"bytes",len(raw),"sha256",hashlib.sha256(raw).hexdigest())
    print("NOTE: opt-in beta only; original v0.14.24 streaming addon kept unchanged on GitHub.")

if __name__=="__main__":
    main()
