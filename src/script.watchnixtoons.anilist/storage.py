"""Safe small JSON files kept in this add-on's profile only."""
import json
import os


def read_json(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, encoding='utf-8') as handle:
            value = json.load(handle)
        if not isinstance(value, type(fallback)):
            raise ValueError('Unexpected JSON shape')
        return value
    except (OSError, ValueError) as exc:
        # Refuse to overwrite unreadable/corrupt files. Keep user data safe.
        raise ValueError('Could not read %s: %s' % (os.path.basename(path), exc))


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
