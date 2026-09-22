import asyncio
import getpass
import jsom
from nio import AsyncClient
from pathlib import Path

HOMESERVER = "https://190688.logineonrw-messenger.de"
USER_ID = "@dqq989d8:190688.logineonrw-messenger.de"

CONFIG_PATH = Path(__file__).parent / "matrix_config.json"
with open(CONFIG_PATH) as f:
    _cfg = json.load(f)

ACCESS_TOKEN = _cfg["access_token"]
DEVICE_ID = "XKNFPTGUDZ"

BASE_DIR = Path(__file__).parent
STORE_PATH = BASE_DIR / "crypto_store"
KEYS_FILE = BASE_DIR / "element-keys.txt"

KEYS_PASSWORD = getpass.getpass("Passwort für die exportierte Schlüsseldatei: ")
async def main():
    client = AsyncClient(HOMESERVER, USER_ID, store_path=STORE_PATH)
    client.access_token = ACCESS_TOKEN
    client.user_id = USER_ID
    client.device_id = DEVICE_ID
    client.load_store()

    await client.import_keys(KEYS_FILE, KEYS_PASSWORD)
    print("Schlüssel importiert!")

    await client.close()

asyncio.run(main())
