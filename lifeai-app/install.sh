#!/usr/bin/env bash
# Installiert die LifeAI-App auf dem Pi. Einfach im Ordner ~/lifeai-app ausführen:  bash install.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "1/5 Python-Umgebung anlegen …"
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q fastapi "uvicorn[standard]" pywebpush

echo "2/5 Datenordner + Push-Schlüssel …"
mkdir -p data && chmod 700 data
./venv/bin/python -c "import vault_lib as V; V.vapid_public_key()"

echo "3/5 Alarme initialisieren (beim ersten Mal wird nichts gesendet) …"
./venv/bin/python app_cli.py task-alerts
./venv/bin/python app_cli.py untis-alerts

echo "4/5 Dienst einrichten (fragt nach deinem Passwort) …"
sudo cp lifeai-app.service /etc/systemd/system/lifeai-app.service
sudo systemctl daemon-reload
sudo systemctl enable --now lifeai-app
sleep 3

echo "5/5 Test …"
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/)
api=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/api/heute)
echo "   Web-App: $code (soll 200)   API ohne Login: $api (soll 403)"
[ "$code" = "200" ] && [ "$api" = "403" ] && echo "✅ Fertig." || echo "❌ Etwas stimmt nicht – sudo journalctl -u lifeai-app -n 50"
