"""Generate ignored local credentials and an encrypted-runtime settings handoff."""
import json
import os
from pathlib import Path
import secrets

from werkzeug.security import generate_password_hash


def main():
    root = Path(__file__).resolve().parent
    settings = root / 'settings.json'
    if settings.exists():
        values = json.loads(settings.read_text())
    else:
        password = secrets.token_urlsafe(24)
        route = '/_ops-' + secrets.token_hex(8)
        values = {'route': route, 'secret': secrets.token_urlsafe(48),
                  'password_hash': generate_password_hash(password, method='pbkdf2:sha256:600000')}
        for path, content in (
            (settings, json.dumps(values, indent=2) + '\n'),
            (root / 'ACCESS.txt', f'Local path: {route}\nPassword: {password}\n\nKeep this file private. Production uses HTTPS at /admin.\n'),
        ):
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
                stream.write(content)
    handoff = root / 'production-admin.env'
    if not handoff.exists():
        with os.fdopen(os.open(handoff, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            stream.write('ADMIN_PANEL_SECRET=' + values['secret'] + '\n')
            stream.write('ADMIN_PANEL_PASSWORD_HASH=' + values['password_hash'] + '\n')
            stream.write('ADMIN_PANEL_PATH=/admin\n')
    print('Admin settings ready. Credentials are in ignored private_admin/ACCESS.txt.')
    print('Copy private_admin/production-admin.env values into encrypted runtime settings. Do not commit or share either file.')


if __name__ == '__main__':
    main()
