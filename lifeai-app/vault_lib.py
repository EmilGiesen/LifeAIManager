"""
vault_lib.py — gemeinsame Funktionen für Server (server.py) und Kommandozeile (app_cli.py).

Liest den Obsidian-Vault (Aufgaben, Zusammenfassungen), den letzten Untis-Stand
und verschickt Web-Push-Benachrichtigungen. Keine KI hier – nur Daten.
"""
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CONFIG = json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))

VAULT = Path(CONFIG.get("vault", "~/obsidian-vault")).expanduser().resolve()
UNTIS_FILE = Path(CONFIG.get("untis_file", "~/element-matrix/untis_latest.json")).expanduser()
FAECHER = CONFIG.get("faecher", {})
TASK_TYPES = {"hausaufgabe", "abgabe", "klausur", "termin", "sonstiges"}
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WOCHENTAGE_LANG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------
# Kleine Helfer
# ----------------------------------------------------------------------------
def heute() -> date:
    return date.today()


def tag_kurz(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WOCHENTAGE[d.weekday()]} {d.strftime('%d.%m.')}"


def fach_name(kuerzel) -> str:
    key = re.sub(r"\s+", " ", str(kuerzel or "")).strip()
    return FAECHER.get(key, key or "Unsortiert")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # atomar: nie eine halb geschriebene Datei


# ----------------------------------------------------------------------------
# Frontmatter (der YAML-Block zwischen den --- am Anfang einer Notiz)
# Wir brauchen nur einfache "schluessel: wert"-Zeilen, deshalb kein YAML-Paket.
# ----------------------------------------------------------------------------
def _wert(raw: str):
    raw = raw.strip()
    if raw == "":
        return None
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip('"')
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def parse_note(text: str):
    """-> (frontmatter: dict, body: str)"""
    if not text.startswith("---"):
        return {}, text
    teile = text.split("\n")
    fm = {}
    for i, zeile in enumerate(teile[1:], start=1):
        if zeile.strip() == "---":
            return fm, "\n".join(teile[i + 1:])
        if ":" in zeile and not zeile.startswith((" ", "\t", "-")):
            k, v = zeile.split(":", 1)
            fm[k.strip()] = _wert(v)
    return {}, text  # kein schließendes ---


def titel_aus(body: str, fallback: str) -> str:
    for zeile in body.split("\n"):
        if zeile.startswith("# "):
            return zeile[2:].strip()
    return fallback


def vault_pfad(rel: str) -> Path:
    """Relativen Pfad sicher in einen Vault-Pfad verwandeln (nichts außerhalb!)."""
    p = (VAULT / rel).resolve()
    p.relative_to(VAULT)  # wirft ValueError, wenn außerhalb
    if p.suffix != ".md" or not p.is_file():
        raise FileNotFoundError(rel)
    return p


def setze_frontmatter(pfad: Path, key: str, wert) -> None:
    text = pfad.read_text(encoding="utf-8")
    fm, _ = parse_note(text)
    if not fm:
        raise ValueError("Notiz hat keinen Frontmatter-Block")
    neu = "true" if wert is True else "false" if wert is False else json.dumps(wert, ensure_ascii=False)
    zeilen = text.split("\n")
    for i in range(1, len(zeilen)):
        if zeilen[i].strip() == "---":
            zeilen.insert(i, f"{key}: {neu}")  # Schlüssel gab es noch nicht
            break
        if zeilen[i].split(":", 1)[0].strip() == key:
            zeilen[i] = f"{key}: {neu}"
            break
    pfad.write_text("\n".join(zeilen), encoding="utf-8")


def alle_notizen():
    for p in VAULT.rglob("*.md"):
        rel = p.relative_to(VAULT)
        if any(teil.startswith(".") for teil in rel.parts):  # .obsidian, .stversions …
            continue
        yield p, rel


# ----------------------------------------------------------------------------
# Aufgaben & Zusammenfassungen
# ----------------------------------------------------------------------------
def lade_aufgaben(mit_erledigten: bool = False) -> list:
    aufgaben = []
    for p, rel in alle_notizen():
        try:
            fm, body = parse_note(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        typ = str(fm.get("typ") or "").lower()
        if typ not in TASK_TYPES:
            continue
        erledigt = fm.get("erledigt") is True
        if erledigt and not mit_erledigten:
            continue
        faellig = fm.get("faellig_am")
        aufgaben.append({
            "pfad": rel.as_posix(),
            "titel": titel_aus(body, p.stem),
            "fach": fm.get("fach") or rel.parts[0],
            "typ": typ,
            "faellig_am": str(faellig) if faellig else None,
            "erledigt": erledigt,
            "quelle": fm.get("quelle"),
            "datum": str(fm.get("datum")) if fm.get("datum") else None,
        })
    aufgaben.sort(key=lambda a: (a["faellig_am"] or "9999-99-99", a["fach"], a["titel"]))
    return aufgaben


def lade_zusammenfassungen(seit_ts: float) -> list:
    """Zusammenfassungs-Notizen aus Logineo, die seit seit_ts geschrieben wurden."""
    out = []
    for p, rel in alle_notizen():
        try:
            if p.stat().st_mtime < seit_ts:
                continue
            fm, body = parse_note(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if fm.get("typ") != "zusammenfassung":
            continue
        # Originalnachrichten (Callout) und Aufgaben-Links weglassen – nur Claudes Stichpunkte
        kern = body.split("> [!quote]")[0].split("## Aufgaben")[0].split("## Anhänge")[0]
        out.append({"fach": fm.get("fach"), "titel": titel_aus(body, p.stem),
                    "text": "\n".join(z for z in kern.split("\n") if not z.startswith("# ")).strip(),
                    "pfad": rel.as_posix()})
    return out


# ----------------------------------------------------------------------------
# Stundenplan (aus untis_latest.json)
# ----------------------------------------------------------------------------
def lade_untis():
    return read_json(UNTIS_FILE, None)


def _min(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def stundenplan(datum_iso: str, untis=None) -> list:
    """Stunden eines Tages, Doppelstunden zusammengefasst, Fächer mit Klarnamen."""
    untis = untis if untis is not None else lade_untis()
    if not untis:
        return []
    stunden = sorted((s for s in untis.get("stunden", []) if s["datum"] == datum_iso),
                     key=lambda s: s["beginn"])
    bloecke = []
    for s in stunden:
        b = bloecke[-1] if bloecke else None
        if (b and b["_kuerzel"] == s["fach"] and b["raum"] == s["raum"] and b["status"] == s["status"]
                and _min(s["beginn"]) - _min(b["ende"]) <= 10):
            b["ende"] = s["ende"]
            continue
        bloecke.append({
            "_kuerzel": s["fach"], "fach": fach_name(s["fach"]), "beginn": s["beginn"], "ende": s["ende"],
            "raum": s.get("raum") or "", "status": s["status"], "raum_vorher": s.get("raum_vorher"),
            "vertretungstext": s.get("vertretungstext"), "info": s.get("info"),
        })
    for b in bloecke:
        b.pop("_kuerzel")
    return bloecke


def naechster_schultag(ab: date, untis=None) -> str | None:
    untis = untis if untis is not None else lade_untis()
    if not untis:
        return None
    tage = sorted({s["datum"] for s in untis.get("stunden", []) if s["datum"] >= ab.isoformat()})
    return tage[0] if tage else None


# ----------------------------------------------------------------------------
# Briefings
# ----------------------------------------------------------------------------
BRIEFING_DIR = DATA_DIR / "briefings"
BRIEFING_DIR.mkdir(exist_ok=True)


def letztes_briefing():
    dateien = sorted(BRIEFING_DIR.glob("*.json"))
    return read_json(dateien[-1], None) if dateien else None


# ----------------------------------------------------------------------------
# Web-Push
# ----------------------------------------------------------------------------
SUBS_FILE = DATA_DIR / "push_subscriptions.json"
VAPID_PEM = DATA_DIR / "vapid_private.pem"


def vapid_public_key() -> str:
    """Öffentlicher Schlüssel für den Browser (wird beim ersten Aufruf erzeugt)."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid01

    if not VAPID_PEM.exists():
        v = Vapid01()
        v.generate_keys()
        v.save_key(str(VAPID_PEM))
        VAPID_PEM.chmod(0o600)
    v = Vapid01.from_file(str(VAPID_PEM))
    raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def push_senden(titel: str, text: str, url: str = "/", tag: str | None = None) -> dict:
    """Schickt eine Benachrichtigung an alle registrierten Geräte."""
    from pywebpush import WebPushException, webpush

    subs = read_json(SUBS_FILE, [])
    if not subs:
        return {"gesendet": 0, "hinweis": "keine Geräte registriert"}
    vapid_public_key()  # stellt sicher, dass der Schlüssel existiert
    payload = json.dumps({"title": titel, "body": text, "url": url, "tag": tag}, ensure_ascii=False)
    ok, behalten = 0, []
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=payload, vapid_private_key=str(VAPID_PEM),
                    vapid_claims={"sub": CONFIG["vapid_sub"]},
                    ttl=6 * 3600)
            ok += 1
            behalten.append(sub)
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status not in (404, 410):  # 404/410 = Gerät abgemeldet -> entfernen
                behalten.append(sub)
    write_json(SUBS_FILE, behalten)
    return {"gesendet": ok, "geraete": len(behalten)}


def zeitstempel() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def jetzt_ts() -> float:
    return time.time()


def datum_plus(tage: int) -> str:
    return (heute() + timedelta(days=tage)).isoformat()
