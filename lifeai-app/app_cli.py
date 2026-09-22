#!/usr/bin/env python3
"""
app_cli.py — wird von n8n per SSH aufgerufen.

  app_cli.py collect <morgen|nachmittag|sonntag>   Daten fürs Briefing sammeln (JSON auf stdout)
  app_cli.py save-briefing <base64-json>          Claudes Text + Daten speichern, Notiz + Push
  app_cli.py untis-alerts                         Push bei neuem Ausfall/Vertretung (heute/morgen)
  app_cli.py task-alerts                          Push bei neuen Aufgaben im Vault
  app_cli.py push-test                            Test-Benachrichtigung

Ausgabe immer als EINE JSON-Zeile auf stdout.
"""
import base64
import json
import sys
from datetime import timedelta

import vault_lib as V

LAST_TS = V.DATA_DIR / "letztes_briefing_ts.json"
UNTIS_SEEN = V.DATA_DIR / "untis_alerts_seen.json"
TASKS_SEEN = V.DATA_DIR / "tasks_seen.json"


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))


# ---------------------------------------------------------------------------
def sammeln(art: str) -> dict:
    h = V.heute()
    untis = V.lade_untis()
    hi = h.isoformat()
    if art == "morgen":
        tag = V.naechster_schultag(h, untis)
    else:  # nachmittag / sonntag: der NÄCHSTE Schultag nach heute
        tag = V.naechster_schultag(h + timedelta(days=1), untis)
    aufgaben = V.lade_aufgaben()
    woche_ende = (h + timedelta(days=7)).isoformat()
    tag_danach = (h + timedelta(days=1)).isoformat()

    def kurz(a):
        return {k: a[k] for k in ("titel", "fach", "typ", "faellig_am", "quelle", "pfad")}

    seit = V.read_json(LAST_TS, {}).get("ts") or (V.jetzt_ts() - 24 * 3600)
    return {
        "art": art,
        "datum": hi,
        "wochentag": V.WOCHENTAGE_LANG[h.weekday()],
        "stundenplan": {
            "datum": tag,
            "titel": ("Heute" if tag == hi else ("Morgen" if tag == tag_danach else V.tag_kurz(tag))) if tag else None,
            "stunden": V.stundenplan(tag, untis) if tag else [],
        },
        "faellig": {
            "ueberfaellig": [kurz(a) for a in aufgaben if a["faellig_am"] and a["faellig_am"] < hi],
            "heute": [kurz(a) for a in aufgaben if a["faellig_am"] == hi],
            "naechster_schultag": [kurz(a) for a in aufgaben if tag and tag != hi and a["faellig_am"] == tag],
            "woche": [kurz(a) for a in aufgaben
                      if a["faellig_am"] and hi < a["faellig_am"] <= woche_ende and a["faellig_am"] != tag
                      and a["typ"] != "klausur"],
            "ohne_datum": [kurz(a) for a in aufgaben if not a["faellig_am"]],
        },
        "klausuren": [kurz(a) for a in aufgaben
                      if a["typ"] == "klausur" and a["faellig_am"]
                      and hi <= a["faellig_am"] <= (h + timedelta(days=60)).isoformat()],
        "neues_aus_chats": V.lade_zusammenfassungen(seit),
    }


def cmd_collect(art: str):
    if art not in ("morgen", "nachmittag", "sonntag"):
        raise SystemExit("art muss morgen|nachmittag|sonntag sein")
    out(sammeln(art))


# ---------------------------------------------------------------------------
def briefing_markdown(b: dict) -> str:
    z = ["---", "typ: briefing", f"datum: {b['datum']}", f"art: {b['art']}",
         f'erstellt: "{b["erstellt"]}"', "---", f"# {b.get('titel') or 'Briefing'}", "",
         b.get("kurzfassung") or "", ""]
    if b.get("wichtig"):
        z += ["## Wichtig"] + [f"- {w}" for w in b["wichtig"]] + [""]
    sp = b.get("stundenplan") or {}
    if sp.get("stunden"):
        z += [f"## Stundenplan {sp.get('titel') or ''}".rstrip()]
        for s in sp["stunden"]:
            hinweis = {"entfall": " – ❌ Entfall", "aenderung": " – ⚠️ Änderung"}.get(s["status"], "")
            z.append(f"- {s['beginn']}–{s['ende']} {s['fach']} ({s['raum']}){hinweis}")
        z.append("")
    if b.get("neues"):
        z += ["## Neu aus den Chats"] + [f"- **{n.get('fach')}:** {n.get('text')}" for n in b["neues"]] + [""]
    if b.get("tipp"):
        z += ["## Tipp", b["tipp"], ""]
    return "\n".join(z)


def cmd_save_briefing(b64: str):
    claude = json.loads(base64.b64decode(b64).decode("utf-8"))
    art = claude.get("art", "morgen")
    daten = sammeln(art)
    b = {**daten, "erstellt": V.zeitstempel(),
         "titel": claude.get("titel") or "Dein Briefing",
         "kurzfassung": claude.get("kurzfassung") or "",
         "wichtig": [str(x) for x in (claude.get("wichtig") or [])][:6],
         "neues": [n for n in (claude.get("neues") or []) if isinstance(n, dict)][:10],
         "tipp": claude.get("tipp") or ""}
    b.pop("neues_aus_chats", None)  # Rohtexte nicht doppelt speichern

    V.write_json(V.BRIEFING_DIR / f"{b['datum']}_{art}.json", b)
    md = V.VAULT / "_Briefing" / f"{b['datum']}_{art}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(briefing_markdown(b), encoding="utf-8")
    V.write_json(LAST_TS, {"ts": V.jetzt_ts(), "zeit": b["erstellt"]})

    # alte Briefing-Dateien der App aufräumen (Vault behält alles)
    for alt in sorted(V.BRIEFING_DIR.glob("*.json"))[:-30]:
        alt.unlink()

    kopf = {"morgen": "☀️ ", "nachmittag": "📚 ", "sonntag": "🗓️ "}.get(art, "")
    push = V.push_senden(kopf + b["titel"], b["kurzfassung"][:180] or "Dein Briefing ist da.", url="/", tag="briefing")
    out({"ok": True, "gespeichert": md.relative_to(V.VAULT).as_posix(), "push": push})


# ---------------------------------------------------------------------------
def cmd_untis_alerts():
    untis = V.lade_untis()
    if not untis:
        return out({"ok": True, "hinweis": "keine Untis-Daten"})
    h = V.heute()
    tage = {h.isoformat(): "Heute", (h + timedelta(days=1)).isoformat(): "Morgen"}
    erster_lauf = not UNTIS_SEEN.exists()
    seen = set(V.read_json(UNTIS_SEEN, []))
    neu = []
    for d in tage:
        for s in V.stundenplan(d, untis):
            if s["status"] == "normal":
                continue
            key = f"{d}|{s['beginn']}|{s['fach']}|{s['status']}|{s['raum']}|{s.get('vertretungstext')}"
            if key in seen:
                continue
            seen.add(key)
            if s["status"] == "entfall":
                neu.append(f"❌ {tage[d]} {s['beginn']} {s['fach']} entfällt" + (f" ({s['info']})" if s.get("info") else ""))
            else:
                was = f"Raum {s['raum_vorher']} → {s['raum']}" if s.get("raum_vorher") else (s.get("vertretungstext") or "Änderung")
                neu.append(f"⚠️ {tage[d]} {s['beginn']} {s['fach']}: {was}")
    # nur Einträge von heute/zukünftig behalten
    V.write_json(UNTIS_SEEN, sorted(k for k in seen if k[:10] >= h.isoformat()))
    if not neu or erster_lauf:
        return out({"ok": True, "neu": len(neu), "push": None, "erster_lauf": erster_lauf})
    titel = "Stundenplan-Änderung" if len(neu) == 1 else f"{len(neu)} Stundenplan-Änderungen"
    out({"ok": True, "neu": len(neu), "push": V.push_senden(titel, "\n".join(neu), url="/", tag="untis")})


def cmd_task_alerts():
    aufgaben = V.lade_aufgaben()
    erster_lauf = not TASKS_SEEN.exists()
    seen = set(V.read_json(TASKS_SEEN, []))
    h = V.heute().isoformat()
    neu = [a for a in aufgaben if a["pfad"] not in seen and not (a["faellig_am"] and a["faellig_am"] < h)]
    V.write_json(TASKS_SEEN, sorted(seen | {a["pfad"] for a in aufgaben}))
    if not neu or erster_lauf:
        return out({"ok": True, "neu": len(neu), "push": None, "erster_lauf": erster_lauf})

    def zeile(a):
        f = f" – fällig {V.tag_kurz(a['faellig_am'])}" if a["faellig_am"] else ""
        return f"{a['fach']}: {a['titel']}{f}"

    titel = "Neue Aufgabe" if len(neu) == 1 else f"{len(neu)} neue Aufgaben"
    text = "\n".join(zeile(a) for a in neu[:4]) + (f"\n… und {len(neu) - 4} weitere" if len(neu) > 4 else "")
    out({"ok": True, "neu": len(neu), "push": V.push_senden("📝 " + titel, text, url="/#aufgaben", tag="aufgaben")})


# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "collect" and len(sys.argv) == 3:
        cmd_collect(sys.argv[2])
    elif cmd == "save-briefing" and len(sys.argv) == 3:
        cmd_save_briefing(sys.argv[2])
    elif cmd == "untis-alerts":
        cmd_untis_alerts()
    elif cmd == "task-alerts":
        cmd_task_alerts()
    elif cmd == "push-test":
        out(V.push_senden("LifeAI", "Push funktioniert 🎉", tag="test"))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
