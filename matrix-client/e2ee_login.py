import asyncio
import sys
from nio import AsyncClient
from pathlib import Path

HOMESERVER = "https://190688.logineonrw-messenger.de"
USER_ID = "@dqq989d8:190688.logineonrw-messenger.de"

if len(sys.argv) != 2:
    print("Nutzung: python e2ee_login.py <login_token>")
    sys.exit(1)

LOGIN_TOKEN = sys.argv[1]

BASE_DIR = Path(__file__).parent

STORE_PATH = BASE_DIR / "crypto_store"
async def main():
    import os
    os.makedirs(STORE_PATH, exist_ok=True)

    client = AsyncClient(HOMESERVER, USER_ID, store_path=STORE_PATH)

    resp = await client.login_raw({
        "type": "m.login.token",
        "token": LOGIN_TOKEN,
        "initial_device_display_name": "pi5-nio",
    })

    print(resp)

    if hasattr(resp, "access_token"):
        print("\n=== WICHTIG, notieren ===")
        print("Access Token:", resp.access_token)
        print("Device ID:", resp.device_id)
        print("User ID:", resp.user_id)

    await client.close()

asyncio.run(main())
