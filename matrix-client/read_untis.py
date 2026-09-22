#!/usr/bin/env python3
"""
read_untis.py — holt Stundenplan, Vertretungen/Ausfälle, Hausaufgaben und
Klausuren aus WebUntis und gibt sie als EINE JSON-Zeile auf stdout aus (für n8n).
Alles andere (Hinweise, Fehler) geht nach stderr.

NUR LESEN: Das Skript meldet sich an, ruft ausschließlich Lese-Methoden auf
und meldet sich am Ende wieder ab. Es ändert nichts in WebUntis.

Zugangsdaten stehen NICHT hier, sondern in untis_config.json (chmod 600):
{
  "server": "xyz.webuntis.com",
  "school": "Schulname",
  "user": "dein.benutzername",
  "password": "dein-passwort",
  "tage_voraus": 7
}
"""
import base64
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "untis_config.json"
CLIENT_NAME = "LifeAiManager"


def log(*args):
    print(*args, file=sys.stderr)


def ymd(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def iso(n: int) -> str:
    s = str(n)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def hhmm(n: int) -> str:
    return f"{n // 100:02d}:{n % 100:02d}"


class Untis:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.base = f"https://{cfg['server']}/WebUntis"
        self.http = requests.Session()
        self.http.headers["User-Agent"] = CLIENT_NAME
        # manche REST-Endpunkte erwarten zusätzlich dieses Cookie
        school_b64 = base64.b64encode(cfg["school"].encode()).decode()
        self.http.cookies.set("schoolname", f'"_{school_b64}"')
        self.person_id = self.person_type = self.klasse_id = None

    # --- JSON-RPC (die "klassische" Untis-API) ---------------------------------
    def rpc(self, method: str, params=None):
        r = self.http.post(
            f"{self.base}/jsonrpc.do",
            params={"school": self.cfg["school"]},
            json={"id": CLIENT_NAME, "method": method, "params": params or {}, "jsonrpc": "2.0"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"{method}: {data['error'].get('message')} (code {data['error'].get('code')})")
        return data.get("result")

    def login(self):
        res = self.rpc("authenticate", {"user": self.cfg["user"], "password": self.cfg["password"],
                                        "client": CLIENT_NAME})
        self.person_id = res.get("personId")
        self.person_type = res.get("personType")  # 5 = Schüler
        self.klasse_id = res.get("klasseId")

    def logout(self):
        try:
            self.rpc("logout")
        except Exception:  # noqa: BLE001
            pass

    def timetable(self, start: date, end: date) -> list:
        opts = {
            "element": {"id": self.person_id, "type": self.person_type},
            "startDate": ymd(start), "endDate": ymd(end),
            "showInfo": True, "showSubstText": True, "showLsText": True, "showStudentgroup": True,
            "klasseFields": ["name"], "roomFields": ["name", "longname"],
            "subjectFields": ["name", "longname"], "teacherFields": ["name"],
        }
        return self.rpc("getTimetable", {"options": opts}) or []

    # --- REST (wie die Web-Oberfläche) -----------------------------------------
    def rest(self, path: str, params: dict):
        r = self.http.get(f"{self.base}/api/{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()


def namen(liste, feld="name"):
    """Aktuelle und ursprüngliche Namen aus z.B. ro/te/su holen."""
    jetzt = [e.get(feld) or e.get("name") for e in liste or [] if e.get(feld) or e.get("name")]
    vorher = [e.get("orgname") for e in liste or [] if e.get("orgname")]
    return jetzt, vorher


def stunde_aufbereiten(p: dict) -> dict:
    fach, fach_vorher = namen(p.get("su"))
    fach_lang, _ = namen(p.get("su"), "longname")
    raum, raum_vorher = namen(p.get("ro"))
    lehrer, lehrer_vorher = namen(p.get("te"))
    code = p.get("code")  # "cancelled" | "irregular" | None
    if code == "cancelled":
        status = "entfall"
    elif code == "irregular" or raum_vorher or lehrer_vorher or fach_vorher or p.get("substText"):
        status = "aenderung"
    else:
        status = "normal"
    return {
        "datum": iso(p["date"]),
        "beginn": hhmm(p["startTime"]),
        "ende": hhmm(p["endTime"]),
        "fach": ", ".join(fach),
        "fach_lang": ", ".join(fach_lang),
        "raum": ", ".join(raum),
        "lehrer": ", ".join(lehrer),
        "status": status,
        "raum_vorher": ", ".join(raum_vorher) or None,
        "lehrer_vorher": ", ".join(lehrer_vorher) or None,
        "fach_vorher": ", ".join(fach_vorher) or None,
        "vertretungstext": p.get("substText") or None,
        "info": p.get("info") or None,
        "art": p.get("activityType") or None,
    }


def main():
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except FileNotFoundError:
        log(f"Konfiguration fehlt: {CONFIG_FILE}")
        sys.exit(1)

    heute = date.today()
    bis = heute + timedelta(days=int(cfg.get("tage_voraus", 7)))
    u = Untis(cfg)
    out = {"abgerufen": heute.isoformat(), "stunden": [], "hausaufgaben": [], "klausuren": []}

    try:
        u.login()
    except Exception as e:  # noqa: BLE001
        log(f"Untis-Login fehlgeschlagen: {e}")
        sys.exit(1)

    try:
        # 1) Stundenplan inkl. Ausfälle/Vertretungen
        try:
            perioden = u.timetable(heute, bis)
            out["stunden"] = sorted((stunde_aufbereiten(p) for p in perioden),
                                    key=lambda s: (s["datum"], s["beginn"]))
            log(f"Stundenplan: {len(out['stunden'])} Stunden, "
                f"{sum(s['status'] == 'entfall' for s in out['stunden'])} Entfall, "
                f"{sum(s['status'] == 'aenderung' for s in out['stunden'])} Änderungen")
        except Exception as e:  # noqa: BLE001
            log(f"Stundenplan nicht abrufbar: {e}")

        # 2) Hausaufgaben (nicht jede Schule schaltet das frei)
        try:
            hw = u.rest("homeworks/lessons", {"startDate": ymd(heute - timedelta(days=7)),
                                               "endDate": ymd(heute + timedelta(days=21))})
            data = hw.get("data", hw)
            lessons = {l["id"]: l.get("subject") for l in data.get("lessons", [])}
            for h in data.get("homeworks", []):
                out["hausaufgaben"].append({
                    "fach": lessons.get(h.get("lessonId")),
                    "gestellt_am": iso(h["date"]) if h.get("date") else None,
                    "faellig_am": iso(h["dueDate"]) if h.get("dueDate") else None,
                    "text": h.get("text"),
                    "bemerkung": h.get("remark") or None,
                    "erledigt": bool(h.get("completed")),
                })
            log(f"Hausaufgaben: {len(out['hausaufgaben'])}")
        except Exception as e:  # noqa: BLE001
            log(f"Hausaufgaben nicht abrufbar (evtl. von der Schule nicht freigeschaltet): {e}")

        # 3) Klausuren/Prüfungen
        try:
            ex = u.rest("exams", {"startDate": ymd(heute), "endDate": ymd(heute + timedelta(days=120)),
                                  "klasseId": u.klasse_id or -1, "withGrades": "false"})
            data = ex.get("data", ex)
            for k in data.get("exams", []):
                teilnehmer = k.get("assignedStudents")
                if teilnehmer and u.person_id and not any(s.get("id") == u.person_id for s in teilnehmer):
                    continue  # Klausur gilt nicht für dich
                out["klausuren"].append({
                    "fach": k.get("subject"),
                    "art": k.get("examType") or None,
                    "name": k.get("name") or None,
                    "datum": iso(k["examDate"]) if k.get("examDate") else None,
                    "beginn": hhmm(k["startTime"]) if k.get("startTime") else None,
                    "ende": hhmm(k["endTime"]) if k.get("endTime") else None,
                    "raeume": k.get("rooms") or [],
                    "text": k.get("text") or None,
                })
            log(f"Klausuren: {len(out['klausuren'])}")
        except Exception as e:  # noqa: BLE001
            log(f"Klausuren nicht abrufbar (evtl. von der Schule nicht freigeschaltet): {e}")
    finally:
        u.logout()

    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
