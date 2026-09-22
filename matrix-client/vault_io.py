#!/usr/bin/env python3
"""
vault_io.py — kleines Schreib-Helferlein für n8n (per SSH aufgerufen).

n8n übergibt die Daten als EIN base64-kodiertes JSON-Argument, damit es
keinerlei Probleme mit Anführungszeichen, Umlauten oder Zeilenumbrüchen gibt.

  python3 vault_io.py note   <base64(JSON{"path": "...", "content": "...", "mode": "new|overwrite|skip"})>

  mode (optional, Standard "new"):
    append    -> Text unten an eine BESTEHENDE Notiz anhängen (z.B. Details aus Logineo
                 an eine Untis-Hausaufgabe). Gibt es die Notiz nicht, passiert nichts.
                 Steht genau dieser Text schon drin, wird er nicht doppelt angehängt.
    new       -> nie überschreiben, bei Namensgleichheit _2, _3 … anhängen
    overwrite -> Datei ersetzen (z.B. Stundenplan-Tagesnotizen, die sich ändern)
    skip      -> nur anlegen, wenn es die Datei noch nicht gibt (z.B. Hausaufgaben,
                 damit dein "erledigt: true" in Obsidian nicht überschrieben wird)
  python3 vault_io.py attach <base64(JSON{"fach": "...", "filename": "...", "pfad": optional})>

Alle Zielpfade werden geprüft: Es kann nur INNERHALB des Vaults geschrieben
und nur AUS dem Anhang-Ordner kopiert werden.
Ausgabe: eine JSON-Zeile mit dem Ergebnis (landet in n8n als stdout).
"""
import base64
import json
import shutil
import sys
from pathlib import Path

VAULT = (Path.home() / "obsidian-vault").resolve()
ATTACH_SRC = (Path.home() / "element-matrix" / "attachments").resolve()


def fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def inside(base: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(base)
        return True
    except ValueError:
        return False


def clean_part(s: str) -> str:
    """Ordner-/Dateinamen entschärfen (kein /, \\, .. usw.)."""
    bad = '<>:"/\\|?*\n\r\t'
    s = "".join("_" if c in bad else c for c in str(s)).strip().strip(".")
    return s or "Unsortiert"


def free_path(p: Path) -> Path:
    """Wenn die Datei schon existiert: _2, _3 … anhängen statt überschreiben."""
    if not p.exists():
        return p
    i = 2
    while True:
        cand = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def cmd_note(data: dict) -> dict:
    rel = data.get("path")
    content = data.get("content")
    if not rel or content is None:
        fail("note: 'path' und 'content' werden benötigt")
    parts = [clean_part(x) for x in str(rel).replace("\\", "/").split("/") if x not in ("", ".", "..")]
    target = VAULT.joinpath(*parts)
    if target.suffix.lower() != ".md":
        target = target.with_suffix(".md")
    if not inside(VAULT, target):
        fail(f"note: Pfad außerhalb des Vaults: {rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = data.get("mode", "new")
    if mode not in ("new", "overwrite", "skip", "append"):
        fail(f"note: unbekannter mode '{mode}'")
    if mode == "append":
        if not target.is_file():
            return {"ok": True, "skipped": "Notiz nicht gefunden", "path": str(target.relative_to(VAULT))}
        alt = target.read_text(encoding="utf-8")
        kern = str(data.get("marker") or content).strip()
        if kern and kern in alt:
            return {"ok": True, "unchanged": str(target.relative_to(VAULT))}
        target.write_text(alt.rstrip("\n") + "\n\n" + content.strip("\n") + "\n", encoding="utf-8")
        return {"ok": True, "appended": str(target.relative_to(VAULT))}
    if mode == "skip" and target.exists():
        return {"ok": True, "skipped": "existiert schon", "path": str(target.relative_to(VAULT))}
    if mode == "overwrite" and target.exists() and target.read_text(encoding="utf-8") == content:
        return {"ok": True, "unchanged": str(target.relative_to(VAULT))}
    if mode == "new":
        target = free_path(target)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "written": str(target.relative_to(VAULT)), "mode": mode}


def cmd_attach(data: dict) -> dict:
    fach = clean_part(data.get("fach") or "Unsortiert")
    filename = data.get("filename")
    if not filename:
        fail("attach: 'filename' fehlt")
    src = Path(data["pfad"]) if data.get("pfad") else ATTACH_SRC / Path(filename).name
    if not inside(ATTACH_SRC, src):
        fail(f"attach: Quelle liegt nicht im Anhang-Ordner: {src}")
    if not src.is_file():
        fail(f"attach: Datei nicht gefunden: {src}")
    dest_dir = VAULT / fach / "Anhaenge"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / clean_part(Path(filename).name)
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return {"ok": True, "skipped": "schon vorhanden", "path": str(dest.relative_to(VAULT))}
    dest = free_path(dest)
    shutil.copy2(src, dest)
    return {"ok": True, "copied": str(dest.relative_to(VAULT))}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("note", "attach"):
        fail("Aufruf: vault_io.py note|attach <base64-json>")
    try:
        data = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        fail(f"Argument ist kein gültiges base64-JSON: {e}")
    VAULT.mkdir(parents=True, exist_ok=True)
    result = cmd_note(data) if sys.argv[1] == "note" else cmd_attach(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
