"""Read-only evidence for an explicitly selected workspace timezone."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

name = sys.argv[1]
ZoneInfo(name)
root = Path('/usr/share/zoneinfo').resolve()
expected = (root / name).resolve(strict=True)
if not expected.is_relative_to(root):
    raise ValueError('Timezone escaped system database')
if Path('/etc').is_symlink():
    raise ValueError('Unexpected system configuration directory')
with expected.open('rb') as stream:
    data = stream.read(131073)
if not data.startswith(b'TZif') or len(data) > 131072:
    raise ValueError('Invalid timezone data')
try:
    with Path('/etc/localtime').open('rb') as stream:
        actual = stream.read(131073)
except OSError:
    actual = b''
try:
    text = Path('/etc/timezone').read_text(encoding='ascii').strip()
except (OSError, UnicodeError):
    text = ''
time.tzset()
print(json.dumps({'schema': 1, 'zone': name, 'tzif_matches': actual == data,
                  'timezone_text_matches': text == name, 'process_tz_matches': os.environ.get('TZ') == name,
                  'offset_seconds': -time.altzone if time.localtime().tm_isdst else -time.timezone,
                  'utc_tzif_sha256': hashlib.sha256((root / 'Etc/UTC').read_bytes()).hexdigest()}))
