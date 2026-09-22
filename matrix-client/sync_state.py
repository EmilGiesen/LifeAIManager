import json
import os

STATE_FILE = "sync_token.json"

def load_token():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f).get("next_batch")
    return None

def save_token(token):
    with open(STATE_FILE, "w") as f:
        json.dump({"next_batch": token}, f)
