"""Read-only verification after the human finishes DigitalOcean setup."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from utils.telemetry_store import PostgresStore

url = dotenv_values(ROOT / '.env').get('TELEMETRY_READ_DATABASE_URL')
if not url:
    raise SystemExit('No private production read connection configured.')
try:
    data = PostgresStore(url).snapshot(1)
except Exception:
    raise SystemExit('Production telemetry is unreachable. Check trusted sources, TLS and database credentials.') from None
print(f"Production connection verified. Last hour: {data['totals']['requests']} requests, {data['totals']['active']} active sessions.")
if not data['workers']:
    print('No collector worker has reported yet. Confirm the web-service environment variables and deployment.')
