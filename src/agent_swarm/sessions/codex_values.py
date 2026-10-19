"""Native Codex times and inline attachment preservation."""
import base64
import binascii
from datetime import datetime
from .archive import JsonlSessionStore

def _timestamp(value: object) -> int | None:
    """Read native ISO timestamps without inventing missing creation times."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return int(parsed.timestamp() * 1000) if parsed.tzinfo else None
    except ValueError:
        return None


def _attachments(store: JsonlSessionStore, value: object, path: str = '') -> list[dict]:
    """Retain inline native input bytes without following arbitrary file/URL references.

    A transcript is content, not permission to read additional private files.
    External references retain an explicit missing-byte reason instead.
    """
    found = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_attachments(store, item, f'{path}/{index}'))
    elif isinstance(value, dict):
        kind = value.get('type')
        field = ({'input_image': 'image_url', 'input_file': 'file_data',
                  'local_image': 'path'}.get(kind) if isinstance(kind, str) else None)
        if field and isinstance(value.get(field), str):
            source = value[field]
            location = f'{path}/{field}'
            if source.startswith('data:') and ';base64,' in source:
                try:
                    content = base64.b64decode(source.split(';base64,', 1)[1], validate=True)
                    attachment = store.put_attachment(content)
                except (ValueError, binascii.Error):
                    attachment = {'missing': {'path': location, 'reason': 'Invalid inline base64 bytes.'}}
            else:
                attachment = {'missing': {'path': location,
                                         'reason': 'Native reference supplied without inline bytes; not fetched.'}}
            found.append({'nativePath': location, **attachment})
        for key, item in value.items():
            escaped = key.replace('~', '~0').replace('/', '~1')
            found.extend(_attachments(store, item, f'{path}/{escaped}'))
    return found


