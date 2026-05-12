#!/bin/bash
cd "$(dirname "$0")"

# Virtuelle Umgebung anlegen falls nicht vorhanden
if [ ! -d "venv" ]; then
  echo "Erstelle virtuelle Umgebung..."
  python3 -m venv venv
fi

# Aktivieren
source venv/bin/activate

# Abhängigkeiten installieren
echo "Installiere Abhängigkeiten..."
pip install -q -r requirements.txt

echo ""
echo "✓ mentortain.me Traumjob Tool"
echo "→ http://localhost:8000"
echo "→ Passwort: 0000"
echo ""
echo "Zum Beenden: Ctrl+C"
echo ""

uvicorn main:app --host 127.0.0.1 --port 8000 --reload
