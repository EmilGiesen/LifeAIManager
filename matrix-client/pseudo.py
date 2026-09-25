#!/usr/bin/env python3
"""
pseudo.py – lokale Pseudonymisierung für den LifeAIManager.

Claude soll keine echten Namen sehen. Dieses Skript baut auf dem Pi eine
Tabelle "echter Name -> Rolle" (z.B. "Anna Schmidt" -> "Lehrkraft L003 (Deutsch GK)",
"Noah Beispiel" -> "Mitschüler S012"). n8n ersetzt damit die Namen, bevor etwas
an die Anthropic-API geht, und übersetzt Claudes Antwort danach wieder zurück.

Datenquelle: die Matrix-API des Logineo-Messengers, NUR LESEND (GET):
  - /rooms/<id>/joined_members          (Anzeigenamen der Raum-Mitglieder)
  - /rooms/<id>/state/m.room.power_levels  (wer Moderator ist -> Lehrkraft)
  - /profile/<eigene-id>/displayname    (dein eigener Name)
Es werden keine Nachrichten gesendet, keine Schlüssel angefragt, nichts verändert.

Dateien (alle chmod 600, liegen neben diesem Skript):
  pseudonyme_auto.json  – automatisch gepflegt (feste Kürzel, werden nie neu vergeben)
  pseudonyme.json       – deine Handliste (umbenennen / zusatz / ignorieren)

Befehle:
  python3 pseudo.py export [--refresh]   JSON-Tabelle für n8n (letzte Zeile = JSON)
  python3 pseudo.py status               Übersicht zum Prüfen (zeigt echte Namen!)
  python3 pseudo.py test "Text ..."      zeigt, was Claude von diesem Text sehen würde
  python3 pseudo.py lehrkraft "Name|@id" ...   Person(en) als Lehrkraft festlegen
  python3 pseudo.py schueler "Name|@id" ...    Person(en) als Schüler festlegen
"""
import ast
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
AUTO_FILE = BASE / "pseudonyme_auto.json"
HAND_FILE = BASE / "pseudonyme.json"
MATRIX_CONFIG = BASE / "matrix_config.json"
READ_MESSAGES = BASE / "read_messages.py"

MAX_ALTER_S = 6 * 3600          # Mitgliederliste höchstens alle 6 h neu holen
MIN_LAENGE = 3                  # kürzere Namensteile werden nicht einzeln ersetzt
ORGA_RAEUME = {"Stufenchat", "Abi27 Orga"}   # dort sind oft auch Schüler Moderatoren
TITEL = {"frau", "herr", "fr", "hr", "dr", "prof", "str", "ostr", "std", "ostd", "str'", "str’",
         "studienrat", "studienrätin", "oberstudienrat", "oberstudienrätin",
         "mr", "mrs", "ms", "miss", "sr", "sra", "srta", "señor", "señora", "profe", "mme", "mlle"}
ANREDEN = ["Frau", "Herr", "Fr.", "Hr.", "Fr", "Hr", "Mr", "Mr.", "Mrs", "Mrs.", "Ms", "Ms.", "Sr.", "Sra.", "Profe"]

HAND_VORLAGE = {
    "_hilfe": [
        "Hier kannst du die automatische Tabelle von Hand verbessern. Nach dem Speichern gilt es ab dem nächsten n8n-Lauf.",
        "umbenennen: eigene Rolle für eine Person. Schlüssel = Matrix-ID (@...:...) ODER Anzeigename wie in 'pseudo.py status'.",
        "zusatz: Namen, die nicht im Messenger stehen (z.B. Lehrer-Kürzel auf Arbeitsblättern wie 'Jae', Eltern, externe Personen).",
        "lehrkraefte / schueler: Rolle erzwingen, wenn die automatische Erkennung (Moderatorenrechte) falsch liegt. Matrix-ID oder Anzeigename. Am einfachsten per 'python3 pseudo.py lehrkraft \"Name\"'.",
        "ignorieren: Wörter, die NICHT ersetzt werden sollen, obwohl sie ein Namensteil sind (z.B. 'Will', 'Mark').",
        "Rollen möglichst eindeutig wählen (nicht zweimal dieselbe), sonst kann die Rückübersetzung nicht wissen, wer gemeint ist."
    ],
    "umbenennen": {},
    "zusatz": {},
    "lehrkraefte": [],
    "schueler": [],
    "ignorieren": []
}


def log(*a):
    print(*a, file=sys.stderr)


def jetzt_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def json_laden(pfad, standard):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return standard


def json_speichern(pfad, daten):
    tmp = Path(str(pfad) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, pfad)


# ---------------------------------------------------------------- Konfiguration

def _konstanten_aus_read_messages():
    """Liest HOMESERVER, USER_ID, ROOM_TO_FACH usw. aus read_messages.py, OHNE es auszuführen."""
    werte = {}
    try:
        baum = ast.parse(READ_MESSAGES.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log("Hinweis: read_messages.py nicht lesbar:", e)
        return werte
    for knoten in baum.body:
        if isinstance(knoten, ast.Assign):
            for ziel in knoten.targets:
                if isinstance(ziel, ast.Name):
                    try:
                        werte[ziel.id] = ast.literal_eval(knoten.value)
                    except Exception:  # noqa: BLE001 – kein Literal (z.B. cfg["x"])
                        pass
    return werte


def _flach(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flach(v, prefix + str(k).lower() + "."))
    else:
        out[prefix.rstrip(".")] = obj
    return out


def _suche(flach, namen):
    for key, wert in flach.items():
        letzter = key.split(".")[-1]
        if letzter in namen and isinstance(wert, str) and wert:
            return wert
    return None


def konfiguration():
    konst = _konstanten_aus_read_messages()
    cfg = _flach(json_laden(MATRIX_CONFIG, {}))
    token = _suche(cfg, {"access_token", "accesstoken", "token"}) or konst.get("ACCESS_TOKEN")
    hs = _suche(cfg, {"homeserver", "homeserver_url", "hs_url", "base_url", "server_url", "server"}) or konst.get("HOMESERVER")
    user = _suche(cfg, {"user_id", "userid", "user", "mxid"}) or konst.get("USER_ID")
    raeume = konst.get("ROOM_TO_FACH") or {}
    if not isinstance(raeume, dict):
        raeume = {}
    fehlt = [n for n, w in (("Access Token", token), ("Homeserver", hs), ("User-ID", user)) if not w]
    if fehlt:
        raise RuntimeError("In matrix_config.json / read_messages.py nicht gefunden: " + ", ".join(fehlt))
    if not raeume:
        raise RuntimeError("ROOM_TO_FACH in read_messages.py nicht gefunden (muss ein festes Dictionary sein)")
    if not hs.startswith("http"):
        hs = "https://" + hs
    return {"token": token, "homeserver": hs.rstrip("/"), "user_id": user, "raeume": raeume}


# ---------------------------------------------------------------- Matrix (nur GET)

def matrix_get(cfg, pfad):
    url = cfg["homeserver"] + "/_matrix/client/v3" + pfad
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + cfg["token"],
        "User-Agent": "LifeAIManager-pseudo/1.0",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def q(s):
    return urllib.parse.quote(s, safe="")


def raum_ids_aufloesen(cfg):
    """ROOM_TO_FACH kann Raum-IDs (!abc:server) oder Raumnamen als Schlüssel haben."""
    ergebnis = {}
    namen = {}
    for schluessel, fach in cfg["raeume"].items():
        if str(schluessel).startswith("!"):
            ergebnis[schluessel] = fach
        else:
            namen[str(schluessel)] = fach
    if namen:
        for rid in matrix_get(cfg, "/joined_rooms").get("joined_rooms", []):
            try:
                n = matrix_get(cfg, "/rooms/" + q(rid) + "/state/m.room.name").get("name")
            except Exception:  # noqa: BLE001
                continue
            if n in namen:
                ergebnis[rid] = namen[n]
    return ergebnis


def mitglieder_holen(cfg):
    """-> {user_id: {"name": Anzeigename, "faecher": set, "lehrkraft": bool}}, eigener Name"""
    leute = {}
    for rid, fach in raum_ids_aufloesen(cfg).items():
        try:
            joined = matrix_get(cfg, "/rooms/" + q(rid) + "/joined_members").get("joined", {})
        except Exception as e:  # noqa: BLE001
            log("Warnung: Mitglieder von", fach, "nicht abrufbar:", e)
            continue
        try:
            pl = matrix_get(cfg, "/rooms/" + q(rid) + "/state/m.room.power_levels") or {}
        except Exception:  # noqa: BLE001
            pl = {}
        stufen = pl.get("users", {}) or {}
        grenze = 100 if fach in ORGA_RAEUME else 50
        for uid, info in joined.items():
            p = leute.setdefault(uid, {"name": None, "faecher": set(), "lehrkraft": False})
            if info and info.get("display_name"):
                p["name"] = info["display_name"]
            p["faecher"].add(fach)
            if int(stufen.get(uid, pl.get("users_default", 0) or 0)) >= grenze:
                p["lehrkraft"] = True
    eigener = None
    try:
        eigener = matrix_get(cfg, "/profile/" + q(cfg["user_id"]) + "/displayname").get("displayname")
    except Exception:  # noqa: BLE001
        eigener = (leute.get(cfg["user_id"]) or {}).get("name")
    return leute, eigener


def auto_aktualisieren():
    cfg = konfiguration()
    leute, eigener = mitglieder_holen(cfg)
    if not leute:
        raise RuntimeError("Keine Raum-Mitglieder gefunden (Token abgelaufen?)")
    auto = json_laden(AUTO_FILE, {"personen": {}, "zaehler": {"S": 0, "L": 0}})
    personen = auto.setdefault("personen", {})
    zaehler = auto.setdefault("zaehler", {"S": 0, "L": 0})
    for uid, p in leute.items():
        if uid == cfg["user_id"]:
            continue
        alt = personen.get(uid)
        if alt and alt.get("code"):
            # Kürzel und bisherige Rolle bleiben; ob sie noch stimmt, entscheidet rollen_anwenden()
            code, rolle_bisher = alt["code"], bool(alt.get("lehrkraft"))
        else:
            praefix = "L" if p["lehrkraft"] else "S"
            zaehler[praefix] = int(zaehler.get(praefix, 0)) + 1
            code, rolle_bisher = "%s%03d" % (praefix, zaehler[praefix]), p["lehrkraft"]
        personen[uid] = {
            "code": code,
            "name": p["name"] or (alt or {}).get("name"),
            "faecher": sorted(p["faecher"]),
            "lehrkraft": rolle_bisher,
            "lehrkraft_matrix": p["lehrkraft"],
            "anzeige_roh": p["name"],
            "zuletzt_gesehen": jetzt_iso(),
        }
    auto["ich"] = {"id": cfg["user_id"], "name": eigener}
    auto["stand"] = jetzt_iso()
    auto["stand_ts"] = int(time.time())
    json_speichern(AUTO_FILE, auto)
    return auto


# ---------------------------------------------------------------- Rollen (Automatik + Handliste)

def _person_passt(uid, p, eintrag):
    e = str(eintrag).strip()
    if not e:
        return False
    if e.startswith("@"):
        return uid == e
    name = p.get("name") or ""
    return e.lower() in (name.lower(), namensteile(name)[0].lower())


def rollen_anwenden(auto, hand):
    """Legt die endgültige Rolle fest: Handliste > Anrede im Anzeigenamen > Moderatorenrechte.
    Wechselt jemand die Rolle, bekommt er ein neues Kürzel (L... bzw. S...). Speichert nur bei Änderung."""
    lk = hand.get("lehrkraefte", []) or []
    sch = hand.get("schueler", []) or []
    zaehler = auto.setdefault("zaehler", {"S": 0, "L": 0})
    geaendert = False
    for uid, p in (auto.get("personen") or {}).items():
        if "lehrkraft_matrix" not in p:          # Tabelle aus älterer Version
            p["lehrkraft_matrix"] = bool(p.get("lehrkraft"))
            geaendert = True
        roh = str(p.get("anzeige_roh") or p.get("name") or "").strip()
        anrede = bool(re.match(r"(?i)^(frau|herr|fr\.|hr\.)\s", roh))
        if any(_person_passt(uid, p, e) for e in sch):
            soll = False
        elif any(_person_passt(uid, p, e) for e in lk) or anrede:
            soll = True
        else:
            soll = bool(p.get("lehrkraft_matrix", p.get("lehrkraft")))
        praefix = "L" if soll else "S"
        if p.get("lehrkraft") != soll or not str(p.get("code", "")).startswith(praefix):
            p["lehrkraft"] = soll
            if not str(p.get("code", "")).startswith(praefix):
                zaehler[praefix] = int(zaehler.get(praefix, 0)) + 1
                p["code"] = "%s%03d" % (praefix, zaehler[praefix])
            geaendert = True
    if geaendert:
        json_speichern(AUTO_FILE, auto)
    return auto


def handliste_ergaenzen(liste, eintraege):
    """'lehrkraft'/'schueler'-Befehl: sucht Personen und trägt sie in pseudonyme.json ein."""
    hand = json_laden(HAND_FILE, None) or json.loads(json.dumps(HAND_VORLAGE))
    auto = json_laden(AUTO_FILE, {"personen": {}})
    ziel = hand.setdefault(liste, [])
    gegen = hand.setdefault("schueler" if liste == "lehrkraefte" else "lehrkraefte", [])
    ok = True
    for suche in eintraege:
        s = suche.strip().lower()
        treffer = [(uid, p) for uid, p in auto.get("personen", {}).items()
                   if uid.lower() == s or s in (p.get("name") or "").lower()]
        exakt = [(u, p) for u, p in treffer if _person_passt(u, p, suche)]
        if len(exakt) == 1:
            treffer = exakt
        if len(treffer) != 1:
            ok = False
            print("\u2717 \"%s\": %s" % (suche, "nicht gefunden" if not treffer else "mehrdeutig – bitte genauer oder mit Matrix-ID:"))
            for uid, p in treffer[:10]:
                print("     %-30s %s  (%s)" % (p.get("name"), uid, ", ".join(p.get("faecher", []))))
            continue
        uid, p = treffer[0]
        if uid not in ziel:
            ziel.append(uid)
        if uid in gegen:
            gegen.remove(uid)
        print("\u2713 %s (%s) -> %s" % (p.get("name"), uid, "Lehrkraft" if liste == "lehrkraefte" else "Schüler"))
    json_speichern(HAND_FILE, hand)
    return ok


# ---------------------------------------------------------------- Tabelle bauen

def namensteile(anzeige):
    """'Schmidt, Anna (Lehrerin)' -> ('Anna Schmidt', ['Anna', 'Schmidt'])"""
    s = re.sub(r"[\(\[].*?[\)\]]", " ", str(anzeige or ""))
    s = re.sub(r"[^\w\s,.'’-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.-")
    if "," in s:
        a, b = s.split(",", 1)
        s = (b.strip() + " " + a.strip()).strip()
    teile = [t.strip(".,") for t in s.split(" ") if t.strip(".,")]
    teile = [t for t in teile if t.lower().rstrip(".") not in TITEL]
    sauber = " ".join(teile)
    return sauber, teile


def einzelteile(teile):
    """Namensteile einzeln, Doppelnamen zusätzlich zerlegt ('Jäger-Tasch' -> 'Jäger', 'Tasch')."""
    out = []
    for t in teile:
        out.append(t)
        if "-" in t:
            out.extend(x for x in t.split("-") if x)
    return out


def rolle(p):
    if p.get("lehrkraft"):
        kurse = [f for f in p.get("faecher", []) if f not in ORGA_RAEUME] or p.get("faecher", [])
        return "Lehrkraft %s (%s)" % (p["code"], ", ".join(kurse))
    return "Mitschüler " + p["code"]


def varianten(anzeige, sauber, teile, mit_einzelteilen=True):
    v = {str(anzeige).strip(), sauber}
    if len(teile) >= 2:
        vor, nach = teile[0], teile[-1]
        v |= {vor + " " + nach, nach + " " + vor, nach + ", " + vor}
        for a in ANREDEN:
            v.add(a + " " + nach)
            v.add(a + " " + sauber)
    elif len(teile) == 1:
        for a in ANREDEN:
            v.add(a + " " + teile[0])
    if len(teile) >= 2 and "-" in teile[-1]:
        for x in teile[-1].split("-"):
            for a in ANREDEN:
                v.add(a + " " + x)
    if mit_einzelteilen:
        v |= set(einzelteile(teile))
    return {x for x in v if x and len(x) >= MIN_LAENGE}


def tabelle_bauen(auto, hand):
    umbenennen = hand.get("umbenennen", {}) or {}
    zusatz = hand.get("zusatz", {}) or {}
    ignorieren = set(hand.get("ignorieren", []) or [])

    vor_kandidaten = {}   # variante -> set(label)
    rueck = {}            # label -> echter Name
    ids = {}

    ich = auto.get("ich") or {}
    ich_name = ich.get("name") or ""
    ich_sauber, ich_teile = namensteile(ich_name)
    ich_vorname = ich_teile[0] if ich_teile else "Emil"

    for uid, p in (auto.get("personen") or {}).items():
        sauber, teile = namensteile(p.get("name") or "")
        label = umbenennen.get(uid) or umbenennen.get(p.get("name") or "") or umbenennen.get(sauber) or rolle(p)
        ids[uid] = {"pseudo": label, "echt": sauber or p.get("name") or uid.split(":")[0].lstrip("@")}
        rueck[label] = ids[uid]["echt"]
        # Kurzformen, falls Claude die Rolle abkürzt ("Lehrkraft L003", "S012")
        rueck.setdefault(p["code"], ids[uid]["echt"])
        if p.get("lehrkraft"):
            rueck.setdefault("Lehrkraft " + p["code"], ids[uid]["echt"])
        if not sauber:
            continue
        for var in varianten(p.get("name"), sauber, teile):
            if var in ignorieren or var == ich_vorname:
                continue
            vor_kandidaten.setdefault(var, set()).add(label)

    # Eigener Name: Vorname bleibt, alles andere (Nachname, voller Name) wird "Emil"
    if ich_sauber:
        for var in varianten(ich_name, ich_sauber, ich_teile):
            if var != ich_vorname and var not in ignorieren:
                vor_kandidaten.setdefault(var, set()).add(ich_vorname)
        if ich.get("id"):
            ids[ich["id"]] = {"pseudo": ich_vorname, "echt": ich_vorname}

    for echt, pseudo in zusatz.items():
        if echt and pseudo:
            vor_kandidaten[echt] = {pseudo}
            rueck[pseudo] = echt

    vor = {}
    for var, labels in vor_kandidaten.items():
        if len(labels) == 1:
            vor[var] = next(iter(labels))
        else:
            # z.B. zwei Leute heißen "Noah": "Mitschüler S003 oder Mitschüler S017"
            kombi = " oder ".join(sorted(labels))
            vor[var] = kombi
            rueck.setdefault(kombi, var)
    # Nie ein Label durch sich selbst zurückübersetzen, wenn es identisch ist
    rueck = {k: v for k, v in rueck.items() if k and v and k != v}

    lang_zuerst = lambda paare: sorted(paare, key=lambda kv: (-len(kv[0]), kv[0]))
    return {
        "stand": auto.get("stand"),
        "ich": ich_vorname,
        "vor": lang_zuerst(vor.items()),
        "rueck": lang_zuerst(rueck.items()),
        "ids": ids,
    }


# ---------------------------------------------------------------- Anwenden (für 'test'; n8n macht dasselbe in JS)

ID_MUSTER = re.compile(r"@[A-Za-z0-9._=\-/+]+:[A-Za-z0-9.\-]+(?::\d+)?")
MAIL_MUSTER = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
GEHEIM_MUSTER = re.compile(r"([?&#](?:token|key|access_token|auth|sig|signature|code|password|pw|pwd)=)[^&\s#]+", re.I)
TEL_MUSTER = re.compile(r"(?<!\d)(?:\+49|0)[1-9][\d /-]{6,}\d(?!\d)")


def pseudonymisieren(text, tab):
    t = str(text)
    t = ID_MUSTER.sub(lambda m: (tab["ids"].get(m.group(0)) or {}).get("pseudo", "Unbekannt"), t)
    t = GEHEIM_MUSTER.sub(r"\1[entfernt]", t)
    t = MAIL_MUSTER.sub("[E-Mail]", t)
    t = TEL_MUSTER.sub("[Telefon]", t)
    if tab["vor"]:
        karte = dict(tab["vor"])
        muster = re.compile(r"(?<![^\W_])(" + "|".join(re.escape(e) for e, _ in tab["vor"]) + r")(s|'s|’s)?(?![^\W_])")
        t = muster.sub(lambda m: karte[m.group(1)] + (m.group(2) or ""), t)
    return t


def zurueck(text, tab):
    if not tab["rueck"]:
        return text
    karte = dict(tab["rueck"])
    muster = re.compile(r"(?<![^\W_])(" + "|".join(re.escape(p) for p, _ in tab["rueck"]) + r")(s|'s|’s)?(?![^\W_])")
    return muster.sub(lambda m: karte[m.group(1)] + (m.group(2) or ""), str(text))


# ---------------------------------------------------------------- CLI

def tabelle(refresh=False):
    hand = json_laden(HAND_FILE, None)
    if hand is None:
        json_speichern(HAND_FILE, HAND_VORLAGE)
        hand = HAND_VORLAGE
    auto = json_laden(AUTO_FILE, None)
    alt = auto is None or refresh or (time.time() - int(auto.get("stand_ts", 0)) > MAX_ALTER_S)
    if alt:
        try:
            auto = auto_aktualisieren()
            log("Pseudonym-Tabelle aus Matrix aktualisiert:", len(auto["personen"]), "Personen")
        except Exception as e:  # noqa: BLE001
            if auto is None:
                raise RuntimeError("Keine Pseudonym-Tabelle vorhanden und Matrix nicht erreichbar: %s" % e)
            log("Warnung: Aktualisierung fehlgeschlagen, nutze gespeicherte Tabelle vom", auto.get("stand"), "-", e)
    auto = rollen_anwenden(auto, hand)
    return tabelle_bauen(auto, hand)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("export", "status", "test", "lehrkraft", "schueler"):
        print(__doc__)
        sys.exit(1)
    befehl = sys.argv[1]
    if befehl in ("lehrkraft", "schueler"):
        namen = [a for a in sys.argv[2:] if a != "--refresh"]
        if not namen:
            print('Beispiel: python3 pseudo.py %s "Anna Schmidt" "@abc123:server"' % befehl)
            sys.exit(1)
        if json_laden(AUTO_FILE, None) is None:
            tabelle(refresh=True)
        ok = handliste_ergaenzen("lehrkraefte" if befehl == "lehrkraft" else "schueler", namen)
        befehl = "status"
    try:
        tab = tabelle(refresh="--refresh" in sys.argv)
    except Exception as e:  # noqa: BLE001
        log("FEHLER:", e)
        sys.exit(2)

    if befehl == "export":
        print(json.dumps(tab, ensure_ascii=False, separators=(",", ":")))
    elif befehl == "status":
        auto = json_laden(AUTO_FILE, {})
        print("Stand:", tab["stand"], "| eigener Vorname bleibt:", tab["ich"])
        print("Personen:", len(auto.get("personen", {})), "| Ersetzungsregeln:", len(tab["vor"]))
        print()
        personen = auto.get("personen", {})
        zeilen = sorted(tab["ids"].items(), key=lambda kv: kv[1]["pseudo"])
        for uid, x in zeilen:
            p = personen.get(uid, {})
            quelle = ""
            if p:
                if p.get("lehrkraft") != bool(p.get("lehrkraft_matrix", p.get("lehrkraft"))):
                    quelle = "  [von Hand/Anrede]"
                if not p.get("lehrkraft"):
                    quelle += "  Räume: " + ", ".join(p.get("faecher", []))
            print("  %-40s <- %-28s %s%s" % (x["pseudo"], x["echt"], uid, quelle))
        mehrdeutig = [(e, p) for e, p in tab["vor"] if " oder " in p]
        if mehrdeutig:
            print("\nMehrdeutige Namensteile (werden ersetzt, Rückübersetzung = nur der Namensteil):")
            for e, p in mehrdeutig:
                print("  %-20s -> %s" % (e, p))
    elif befehl == "test":
        text = " ".join(a for a in sys.argv[2:] if a != "--refresh") or sys.stdin.read()
        p = pseudonymisieren(text, tab)
        print("Claude sieht:\n" + p)
        print("\nZurückübersetzt:\n" + zurueck(p, tab))


if __name__ == "__main__":
    main()
