"""Build a Kodi 21 beta repository from reviewed installer bytes only.

Never auto-patch upstream files. Changing any archive requires an explicit
new SHA-256 allow-list and an accompanying review.
"""
import argparse
import hashlib
import html
import io
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

BASE_URL = 'https://genomesteve.github.io/kodi-anilist-sync/beta/managed/'
APPROVED = {
    'plugin.video.watchnixtoons2': ('0.14.24.1',
        'plugin.video.watchnixtoons2-0.14.24.1-sync-beta.zip',
        'baf458aa9e07257c6b331e0a28b68d7b385951660f32191707d9c223f40ff3a6'),
    'script.watchnixtoons.anilist': ('0.5.5',
        'script.watchnixtoons.anilist-0.5.5-beta.zip',
        '2a2543482221bda3afc9705008c778652ea00b7f77709d591f1086a1d9fb79fd'),
}
REPOSITORY_ID = 'repository.genomesteve.syncbeta'
REPOSITORY_VERSION = '1.0.1'
MAX_ARCHIVE_SIZE = 2_000_000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def packaged_addon(raw, expected_id, expected_version):
    """Verify archive and inspect its real addon.xml before indexing it."""
    if len(raw) > MAX_ARCHIVE_SIZE:
        raise ValueError('Archive too large')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if not names or len(names) != len(set(names)):
            raise ValueError('Missing or duplicate archive entries')
        if any(n.startswith('/') or '..' in Path(n).parts or '\\' in n for n in names):
            raise ValueError('Unsafe archive paths')
        target = expected_id + '/addon.xml'
        if target not in names or z.testzip() is not None:
            raise ValueError('Invalid add-on archive')
        addon = ET.fromstring(z.read(target))
        if addon.get('id') != expected_id or addon.get('version') != expected_version:
            raise ValueError('Unexpected add-on identity/version: ' + expected_id)
        return addon


def make_repo(source, output, repository_source):
    source, output, repository_source = map(Path, (source, output, repository_source))
    # Validate all approved inputs before publishing any metadata.
    packages = {}
    xmls = {}
    for addon_id, (version, filename, expected_sha) in APPROVED.items():
        raw = (source / filename).read_bytes()
        if digest(raw) != expected_sha:
            raise ValueError('Unapproved add-on ZIP hash: ' + filename)
        xmls[addon_id] = packaged_addon(raw, addon_id, version)
        packages[addon_id + '/' + addon_id + '-' + version + '.zip'] = raw

    repository_bytes = (repository_source / 'addon.xml').read_bytes()
    repo = ET.fromstring(repository_bytes)
    if repo.get('id') != REPOSITORY_ID or repo.get('version') != REPOSITORY_VERSION:
        raise ValueError('Unexpected repository ID/version')
    endpoint = repo.find('.//extension[@point="xbmc.addon.repository"]/dir')
    if endpoint is None:
        raise ValueError('Missing repository endpoint')
    for tag, url in [('info', 'addons.xml'), ('checksum', 'addons.xml.md5'), ('datadir', '')]:
        element = endpoint.find(tag)
        if element is None or (element.text or '') != BASE_URL + url:
            raise ValueError('Repository endpoint mismatch')
    if endpoint.find('datadir').get('zip') != 'true':
        raise ValueError('Kodi repository must explicitly use ZIP packages')
    if endpoint.findtext('hashes') != 'false':
        raise ValueError('Unsupported hash-header configuration')

    # Standard Kodi add-on ZIP layout, plus a root-level install shortcut.
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(REPOSITORY_ID + '/addon.xml', repository_bytes)
    repo_raw = data.getvalue()
    packaged_addon(repo_raw, REPOSITORY_ID, REPOSITORY_VERSION)
    repo_name = REPOSITORY_ID + '-' + REPOSITORY_VERSION + '.zip'
    packages[REPOSITORY_ID + '/' + repo_name] = repo_raw
    packages[repo_name] = repo_raw
    xmls[REPOSITORY_ID] = repo

    root = ET.Element('addons')
    for addon_id in sorted(xmls):
        root.append(xmls[addon_id])
    index = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8') + b'\n'
    ET.fromstring(index)

    output.mkdir(parents=True, exist_ok=True)
    for path, raw in packages.items():
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    (output / 'addons.xml').write_bytes(index)
    (output / 'addons.xml.md5').write_text(hashlib.md5(index).hexdigest(), encoding='ascii')
    (output / 'SHA256.txt').write_text(''.join(
        '%s  %s\n' % (digest(raw), name) for name, raw in sorted(packages.items())), encoding='ascii')
    (output / 'index.html').write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<title>GenomeSteve managed Kodi beta</title></head><body>'
        '<h1>GenomeSteve managed Kodi beta repository</h1>'
        '<p>Install this repository on Firestick 2 only while testing. '
        'Only reviewed source-matched versions are published.</p>'
        '<p><a href="%s">%s</a></p>' % (html.escape(repo_name), html.escape(repo_name)) +
        '<p><a href="SHA256.txt">SHA-256 checksums</a></p></body></html>\n', encoding='utf-8')
    return {path: digest(raw) for path, raw in packages.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--repo-src', default='src/repository.genomesteve.syncbeta')
    args = parser.parse_args()
    hashes = make_repo(args.source, args.out, args.repo_src)
    print('Managed repository assembled; approved entries:', len(hashes))


if __name__ == '__main__':
    main()
