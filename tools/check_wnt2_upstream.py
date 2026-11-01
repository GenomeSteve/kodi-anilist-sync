"""Read-only upstream WatchNixtoons2 release/source monitor.

Tracks the specific v0.14.24 provider ID we patched and the separate author's
kodi19 source, without treating them as interchangeable or publishing builds.
GitHub REST metadata only; never downloads or executes unapproved scripts.
"""
import base64
import json
import os
import re
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

PUBLISHED = 'https://api.github.com/repos/deklica/repo.dexe/contents/zips/plugin.video.watchnixtoons2'
DEVELOPER = 'https://api.github.com/repos/christianhaitian/plugin.video.watchnixtoons2/contents'
BASELINE_VERSION = '0.14.24'
BASELINE_PACKAGE_SHA = 'b6a5cbc56a3f840120fc07ed6421e540d904c2fd'
BASELINE_XML_SHA = '14669d4e555d0619a2bdc771c1d7ee99e4f5dbd6'
BASELINE_DEV_XML_SHA = 'e1e9ab58f71e6af0b20ef2c003058d1190fe4429'
BASELINE_DEV_CODE_SHA = '74864eb82fef410bd310a75de867bb5af2a07fc8'


def read_github(url, token=None):
    if not url.startswith(('https://api.github.com/repos/deklica/repo.dexe/',
                           'https://api.github.com/repos/christianhaitian/plugin.video.watchnixtoons2/')):
        raise ValueError('Only approved public upstream GitHub repositories allowed')
    headers = {'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28',
               'User-Agent': 'GenomeSteve-WNT2-ReadOnly-Monitor'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request(url, headers=headers)
    with urlopen(req, timeout=15) as response:
        return json.loads(response.read(250_000).decode('utf-8'))


def release_version(filename):
    match = re.fullmatch(r'plugin\.video\.watchnixtoons2-(\d+(?:\.\d+)+)\.zip', filename)
    return tuple(map(int, match.group(1).split('.'))) if match else None


def inspect(read=read_github):
    files = read(PUBLISHED)
    if not isinstance(files, list):
        raise ValueError('Unexpected published package directory')
    versions = [(release_version(f.get('name', '')), f)
                for f in files if isinstance(f, dict)]
    versions = [(v, f) for v, f in versions if v is not None]
    if not versions:
        raise ValueError('No official source-matched WNT2 ZIP found')
    latest_version, latest = max(versions, key=lambda pair: pair[0])
    current_version = '.'.join(map(str, latest_version))
    published_xml = read(PUBLISHED + '/addon.xml?ref=master')
    dev_xml = read(DEVELOPER + '/addon.xml?ref=kodi19')
    dev_code = read(DEVELOPER + '/lib/plugin.py?ref=kodi19')
    for response in (published_xml, dev_xml, dev_code):
        if not isinstance(response, dict) or not re.fullmatch(r'[0-9a-f]{40}', response.get('sha', '')):
            raise ValueError('Missing verified GitHub blob identity')
    if dev_xml.get('encoding') != 'base64':
        raise ValueError('Unexpected developer XML encoding')
    xml = ET.fromstring(base64.b64decode(dev_xml['content']))
    dev_id, dev_version = xml.get('id'), xml.get('version')
    if dev_id not in ('plugin.video.watchnixtoons2.kodi19', 'plugin.video.watchnixtoons2'):
        raise ValueError('Unexpected upstream developer add-on ID')
    alerts = []
    baseline = tuple(map(int, BASELINE_VERSION.split('.')))
    if latest_version > baseline:
        alerts.append('A newer published WNT2 ZIP is available: ' + current_version)
    elif latest_version == baseline and latest.get('sha') != BASELINE_PACKAGE_SHA:
        alerts.append('Existing WNT2 v0.14.24 ZIP has changed bytes; investigate before use')
    if published_xml['sha'] != BASELINE_XML_SHA:
        alerts.append('Published WNT2 addon.xml changed')
    if dev_xml['sha'] != BASELINE_DEV_XML_SHA or dev_code['sha'] != BASELINE_DEV_CODE_SHA:
        alerts.append('Author kodi19 source changed; different add-on ID, manual compatibility review required')
    if dev_id != 'plugin.video.watchnixtoons2.kodi19':
        alerts.append('Author changed Kodi add-on ID; check provider compatibility')

    # The stable warning fingerprint prevents a daily GitHub comment storm.
    fingerprint = '|'.join((current_version, latest.get('sha', ''),
                            published_xml['sha'], dev_xml['sha'], dev_code['sha'], dev_id))
    import hashlib
    marker = '<!-- wnt2-upstream-' + hashlib.sha256(fingerprint.encode()).hexdigest()[:24] + ' -->'
    return {'changed': bool(alerts), 'alerts': alerts,
            'published_version': current_version, 'published_zip_sha': latest.get('sha'),
            'developer_addon_id': dev_id, 'developer_version': dev_version,
            'developer_source_sha': dev_code['sha'], 'marker': marker,
            'upstream_url': PUBLISHED}


def main():
    token = os.getenv('GITHUB_TOKEN') or None
    result = inspect(lambda url: read_github(url, token))
    message = json.dumps(result, sort_keys=True)
    print(message)
    path = os.getenv('GITHUB_OUTPUT')
    if path:
        with open(path, 'a', encoding='utf-8') as file:
            file.write('changed=%s\n' % str(result['changed']).lower())
            file.write('marker=%s\n' % result['marker'])
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as file:
            file.write('## WatchNixtoons2 upstream read-only check\n\n')
            file.write('Published version: %s. Author kodi19: %s (%s).\n\n' %
                       (result['published_version'], result['developer_version'],
                        result['developer_addon_id']))
            file.write('\n'.join('- ' + a for a in result['alerts']) or
                       'No upstream drift relative to the reviewed baselines.\n')
    if result['changed']:
        with open('upstream-alert.txt', 'w', encoding='utf-8') as file:
            file.write('Upstream WatchNixtoons2 change detected. No packages were published.\n\n')
            file.write('\n'.join('- ' + alert for alert in result['alerts']) + '\n\n')
            file.write('Original source: ' + PUBLISHED + '\n\n' + result['marker'] + '\n')


if __name__ == '__main__':
    main()
