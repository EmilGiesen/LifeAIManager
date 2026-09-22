"""
server.py — kleine API + Auslieferung der Web-App.

Start (auf dem Pi, per systemd):
  ./venv/bin/uvicorn server:app --host 127.0.0.1 --port 8090

Lauscht NUR auf 127.0.0.1. Von außen erreichbar ausschließlich über den
Cloudflare-Tunnel, davor sitzt Cloudflare Access (Login). Als zweite
Sicherung lehnt der Server API-Anfragen ohne Access-Header ab.
"""
from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import vault_lib as V

app = FastAPI(title="LifeAI", docs_url=None, redoc_url=None)


@app.middleware("http")
async def nur_mit_cloudflare_access(request: Request, call_next):
    if (V.CONFIG.get("require_access_header", True) and request.url.path.startswith("/api/")
            and "cf-access-jwt-assertion" not in request.headers):
        return JSONResponse({"detail": "Nur über Cloudflare Access erreichbar"}, status_code=403)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Heute / Briefing
# ---------------------------------------------------------------------------
@app.get("/api/heute")
def heute():
    untis = V.lade_untis()
    h = V.heute()
    tag = V.naechster_schultag(h, untis)  # heute, oder nächster Schultag (z.B. am Wochenende)
    aufgaben = V.lade_aufgaben()
    return {
        "jetzt": V.zeitstempel(),
        "datum": h.isoformat(),
        "stundenplan": {
            "datum": tag,
            "titel": ("Heute" if tag == h.isoformat() else "Morgen" if tag == V.datum_plus(1)
                      else V.WOCHENTAGE_LANG[date.fromisoformat(tag).weekday()]) if tag else None,
            "stunden": V.stundenplan(tag, untis) if tag else [],
            "stand": (untis or {}).get("abgerufen"),
        },
        "briefing": V.letztes_briefing(),
        "zaehler": {
            "offen": len(aufgaben),
            "ueberfaellig": sum(1 for a in aufgaben if a["faellig_am"] and a["faellig_am"] < h.isoformat()),
            "heute": sum(1 for a in aufgaben if a["faellig_am"] == h.isoformat()),
        },
    }


# ---------------------------------------------------------------------------
# Aufgaben
# ---------------------------------------------------------------------------
@app.get("/api/aufgaben")
def aufgaben(erledigte: bool = False):
    return {"aufgaben": V.lade_aufgaben(mit_erledigten=erledigte), "heute": V.heute().isoformat()}


@app.get("/api/aufgabe")
def aufgabe_details(pfad: str):
    """Inhalt einer Aufgaben-Notiz (ohne Frontmatter/Titel) für die Detail-Ansicht."""
    try:
        p = V.vault_pfad(pfad)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Aufgabe nicht gefunden")
    fm, body = V.parse_note(p.read_text(encoding="utf-8"))
    if str(fm.get("typ") or "").lower() not in V.TASK_TYPES:
        raise HTTPException(400, "Das ist keine Aufgaben-Notiz")
    zeilen = [z for z in body.split("\n") if not z.startswith("# ")]
    return {"pfad": pfad, "text": "\n".join(zeilen).strip()}


class Erledigt(BaseModel):
    pfad: str
    erledigt: bool


@app.post("/api/aufgaben/erledigt")
def aufgabe_erledigt(body: Erledigt):
    try:
        p = V.vault_pfad(body.pfad)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Aufgabe nicht gefunden")
    fm, _ = V.parse_note(p.read_text(encoding="utf-8"))
    if str(fm.get("typ") or "").lower() not in V.TASK_TYPES:
        raise HTTPException(400, "Das ist keine Aufgaben-Notiz")
    V.setze_frontmatter(p, "erledigt", body.erledigt)
    return {"ok": True, "pfad": body.pfad, "erledigt": body.erledigt}


# ---------------------------------------------------------------------------
# Push-Benachrichtigungen
# ---------------------------------------------------------------------------
@app.get("/api/push/key")
def push_key():
    return {"key": V.vapid_public_key()}


class Subscription(BaseModel):
    endpoint: str
    keys: dict


@app.post("/api/push/subscribe")
def push_subscribe(sub: Subscription):
    subs = [s for s in V.read_json(V.SUBS_FILE, []) if s.get("endpoint") != sub.endpoint]
    subs.append(sub.model_dump())
    V.write_json(V.SUBS_FILE, subs)
    return {"ok": True, "geraete": len(subs)}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(sub: Subscription):
    subs = [s for s in V.read_json(V.SUBS_FILE, []) if s.get("endpoint") != sub.endpoint]
    V.write_json(V.SUBS_FILE, subs)
    return {"ok": True, "geraete": len(subs)}


@app.post("/api/push/test")
def push_test():
    return V.push_senden("LifeAI", "Push funktioniert 🎉", tag="test")


# ---------------------------------------------------------------------------
# Web-App ausliefern
# ---------------------------------------------------------------------------
STATIC = V.APP_DIR / "static"


@app.get("/sw.js")
def service_worker():
    # Service Worker muss von der Wurzel kommen, damit er die ganze App abdeckt
    return FileResponse(STATIC / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
