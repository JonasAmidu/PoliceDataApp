"""Create scoped database credentials without writing secrets to Git or logs."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values, set_key
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from utils.telemetry_store import SCHEMA, connect


def connection_url(parameters, username, password):
    host = parameters['host']
    if ':' in host:
        host = '[' + host + ']'
    query = {key: value for key, value in parameters.items()
             if key not in ('user', 'password', 'host', 'port', 'dbname', 'application_name')}
    query.setdefault('sslmode', 'require')
    return (f'postgresql://{quote(username, safe="")}:{quote(password, safe="")}@{host}:'
            f'{parameters.get("port", "5432")}/{quote(parameters["dbname"], safe="")}?{urlencode(query)}')


def provision(url, root=ROOT):
    root = Path(root)
    private = root / 'private_admin'
    private.mkdir(mode=0o700, exist_ok=True)
    parameters = conninfo_to_dict(url)
    target = hashlib.sha256(json.dumps([parameters.get('host'), parameters.get('port', '5432'), parameters.get('dbname')]).encode()).hexdigest()
    saved = private / 'database_access.json'
    if saved.exists():
        credentials = json.loads(saved.read_text())
        if credentials['target'] != target:
            raise ValueError('Private database credentials already exist for another database.')
    else:
        suffix = secrets.token_hex(4)
        writer, reader = 'policedata_writer_' + suffix, 'policedata_reader_' + suffix
        writer_password, reader_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with connect(url) as db:
            db.execute(SCHEMA)
            for role, password in ((writer, writer_password), (reader, reader_password)):
                db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
                db.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
            db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON telemetry_requests,telemetry_sessions,telemetry_workers TO {}').format(sql.Identifier(writer)))
            db.execute(sql.SQL('GRANT SELECT ON telemetry_requests,telemetry_sessions,telemetry_workers TO {}').format(sql.Identifier(reader)))
            db.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only=on').format(sql.Identifier(reader)))
        credentials = {'target': target, 'writer': connection_url(parameters, writer, writer_password),
                       'reader': connection_url(parameters, reader, reader_password)}
        with os.fdopen(os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(credentials, stream, indent=2)
            stream.write('\n')
    writer_file = private / 'production-writer.env'
    with os.fdopen(os.open(writer_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        stream.write('TELEMETRY_DATABASE_URL=' + credentials['writer'] + '\nTELEMETRY_ENABLED=1\n')
    reader_file = private / 'production-reader.env'
    with os.fdopen(os.open(reader_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        stream.write('TELEMETRY_READ_DATABASE_URL=' + credentials['reader'] + '\n')
    environment = root / '.env'
    environment.touch(mode=0o600, exist_ok=True)
    set_key(str(environment), 'TELEMETRY_READ_DATABASE_URL', credentials['reader'])
    set_key(str(environment), 'TELEMETRY_ENABLED', '0')
    environment.chmod(0o600)
    return credentials


def main():
    url = os.environ.get('TELEMETRY_ADMIN_DATABASE_URL') or dotenv_values(ROOT / 'private_admin/setup.env').get('TELEMETRY_ADMIN_DATABASE_URL')
    if not url:
        raise SystemExit('Use the private setup wizard to supply the database connection.')
    try:
        provision(url)
    except Exception:
        raise SystemExit('Database setup failed. Check connectivity and role-creation privileges. No credentials have been printed.') from None
    # Keep only the scoped credentials after successful setup.
    (ROOT / 'private_admin/setup.env').unlink(missing_ok=True)
    print('Telemetry tables and scoped accounts ready. Local panel configured with read-only access.')
    print('The production connection is saved privately in private_admin/production-writer.env.')


if __name__ == '__main__':
    main()
