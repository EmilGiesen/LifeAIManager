import asyncio
from nio import AsyncClient, RoomNameEvent

HOMESERVER = "https://190688.logineonrw-messenger.de"
USER_ID = "@dqq989d8:190688.logineonrw-messenger.de"
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "matrix_config.json"
with open(CONFIG_PATH) as f:
    _cfg = json.load(f)

ACCESS_TOKEN = _cfg["access_token"]

DEVICE_ID = "PMMIPPEMRF"
async def main():
    client = AsyncClient(HOMESERVER, USER_ID)
    client.access_token = ACCESS_TOKEN
    client.user_id = USER_ID
    client.device_id = DEVICE_ID

    resp = await client.sync(timeout=10000, full_state=True)

    for room_id, room_info in resp.rooms.join.items():
        name = None
        for event in room_info.state:
            if isinstance(event, RoomNameEvent):
                name = event.name
        print(f"{room_id}  ->  {name or '(kein Name gefunden)'}")
    await client.close()

asyncio.run(main())
