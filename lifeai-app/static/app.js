// LifeAI – Web-App (kein Framework, kein Build-Schritt)
'use strict';

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const WT = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
const WT_LANG = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];

const zustand = { heute: null, aufgaben: [], datum: null, zeigeErledigte: false };

// ---------- Hilfen ----------
function isoHeute() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function plusTage(iso, n) {
  const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function tagText(iso) {
  if (!iso) return '';
  const h = isoHeute();
  if (iso === h) return 'heute';
  if (iso === plusTage(h, 1)) return 'morgen';
  if (iso === plusTage(h, -1)) return 'gestern';
  const d = new Date(iso + 'T12:00:00');
  return `${WT[d.getDay()]} ${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.`;
}
function tageBis(iso) {
  return Math.round((new Date(iso + 'T12:00:00') - new Date(isoHeute() + 'T12:00:00')) / 86400000);
}
const FARBEN = ['#4f46e5', '#0891b2', '#16a34a', '#ca8a04', '#dc2626', '#9333ea', '#db2777', '#ea580c', '#0d9488', '#2563eb'];
function fachFarbe(fach) {
  let h = 0; for (const c of String(fach)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return FARBEN[h % FARBEN.length];
}
const TYP = { hausaufgabe: 'Hausaufgabe', abgabe: 'Abgabe', klausur: 'Klausur', termin: 'Termin', sonstiges: 'Sonstiges' };

function toast(text) {
  const t = $('#toast'); t.textContent = text; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2800);
}

async function api(pfad, opts = {}) {
  const r = await fetch(pfad, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, ...opts });
  if (r.status === 401 || r.status === 403 || r.redirected) {
    // Cloudflare-Login abgelaufen -> Seite neu laden, Cloudflare zeigt die Anmeldung
    location.reload();
    throw new Error('Anmeldung nötig');
  }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

// ---------- Laden ----------
async function laden() {
  const btn = $('#btn-neu'); btn.classList.add('dreht');
  try {
    const [heute, aufg] = await Promise.all([
      api('/api/heute'),
      api('/api/aufgaben' + (zustand.zeigeErledigte ? '?erledigte=true' : '')),
    ]);
    zustand.heute = heute; zustand.aufgaben = aufg.aufgaben; zustand.datum = aufg.heute; detailCache.clear();
    zeichneKopf(); zeichneHeute(); zeichneAufgaben(); zeichneInfo();
  } catch (e) {
    if (!zustand.heute) $('#heute-inhalt').innerHTML = `<div class="karte leer">Keine Verbindung zum Pi.<br><small>${esc(e.message)}</small></div>`;
    else toast('Aktualisieren fehlgeschlagen – zeige letzten Stand');
  } finally {
    btn.classList.remove('dreht');
  }
}

// ---------- Kopf ----------
function zeichneKopf() {
  const d = new Date();
  const std = d.getHours();
  const gruss = std < 11 ? 'Guten Morgen' : std < 17 ? 'Hallo' : 'Guten Abend';
  $('#kopf-gruss').textContent = `${gruss}, Emil`;
  $('#kopf-datum').textContent = `${WT_LANG[d.getDay()]}, ${d.toLocaleDateString('de-DE', { day: 'numeric', month: 'long' })}`;
  const offen = zustand.aufgaben.filter((a) => !a.erledigt && a.faellig_am && a.faellig_am <= plusTage(isoHeute(), 1)).length;
  const b = $('#badge-aufgaben'); b.hidden = !offen; b.textContent = offen;
}

// ---------- Heute ----------
function zeichneHeute() {
  const { briefing, stundenplan } = zustand.heute;
  const h = isoHeute();
  const offen = zustand.aufgaben.filter((a) => !a.erledigt);
  const teile = [];

  // Briefing
  if (briefing) {
    const alt = briefing.datum !== h;
    teile.push(`
      <article class="karte briefing">
        <p class="leise">${briefing.art === 'nachmittag' ? 'Nachmittags-Update' : briefing.art === 'sonntag' ? 'Wochenstart' : 'Morgen-Briefing'} · ${esc(tagText(briefing.datum))} ${esc((briefing.erstellt || '').slice(11))}${alt ? ' (älter)' : ''}</p>
        <h2>${esc(briefing.titel)}</h2>
        <p>${esc(briefing.kurzfassung)}</p>
        ${briefing.wichtig?.length ? `<ul>${briefing.wichtig.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
        ${briefing.tipp ? `<div class="tipp">💡 ${esc(briefing.tipp)}</div>` : ''}
      </article>`);
  } else {
    teile.push(`<article class="karte leer">Noch kein Briefing. Das erste kommt um 06:30 bzw. 16:00.</article>`);
  }

  // Zähler
  const ueber = offen.filter((a) => a.faellig_am && a.faellig_am < h).length;
  const heuteF = offen.filter((a) => a.faellig_am === h).length;
  const morgenF = offen.filter((a) => a.faellig_am === plusTage(h, 1)).length;
  teile.push(`
    <div class="zaehler">
      <div class="zahl ${ueber ? 'rot' : ''}"><b>${ueber}</b><span>überfällig</span></div>
      <div class="zahl"><b>${heuteF}</b><span>heute fällig</span></div>
      <div class="zahl"><b>${morgenF}</b><span>morgen fällig</span></div>
    </div>`);

  // Stundenplan
  if (stundenplan?.stunden?.length) {
    const zeilen = stundenplan.stunden.map((s) => {
      let hinweis = '';
      if (s.status === 'entfall') hinweis = 'Entfällt' + (s.info ? ` – ${s.info}` : '');
      else if (s.status === 'aenderung') hinweis = s.raum_vorher ? `Raum ${s.raum_vorher} → ${s.raum}` : (s.vertretungstext || s.info || 'Änderung');
      return `
        <div class="stunde ${s.status}">
          <div class="zeit">${esc(s.beginn)}<br>${esc(s.ende)}</div>
          <div>
            <div class="fach"><i class="punkt" style="background:${fachFarbe(s.fach)}"></i><span>${esc(s.fach)}</span></div>
            ${hinweis ? `<div class="hinweis">${s.status === 'entfall' ? '❌' : '⚠️'} ${esc(hinweis)}</div>` : ''}
          </div>
          <div class="raum">${esc(s.raum)}</div>
        </div>`;
    }).join('');
    const aenderungen = stundenplan.stunden.filter((s) => s.status !== 'normal').length;
    teile.push(`
      <article class="karte">
        <div class="karte-kopf"><h3>Stundenplan ${esc(stundenplan.titel || '')}</h3>
          ${aenderungen ? `<span class="chip gelb">${aenderungen} Änderung${aenderungen > 1 ? 'en' : ''}</span>` : `<span class="chip gruen">wie geplant</span>`}</div>
        ${zeilen}
      </article>`);
  }

  // Bald fällig (heute + morgen + überfällig)
  const bald = offen.filter((a) => a.faellig_am && a.faellig_am <= plusTage(h, 2) && a.typ !== 'klausur');
  if (bald.length) {
    teile.push(`
      <article class="karte">
        <div class="karte-kopf"><h3>Bald fällig</h3><a href="#aufgaben" class="chip">alle</a></div>
        ${bald.map(aufgabeHtml).join('')}
      </article>`);
  }

  // Klausuren
  const klausuren = offen.filter((a) => a.typ === 'klausur' && a.faellig_am && a.faellig_am >= h).slice(0, 5);
  if (klausuren.length) {
    teile.push(`
      <article class="karte">
        <div class="karte-kopf"><h3>Klausuren</h3></div>
        ${klausuren.map((k) => `
          <div class="klausur">
            <div><div class="fach" style="font-weight:600">${esc(k.fach)}</div><div class="leise" style="font-size:.85rem">${esc(tagText(k.faellig_am))}</div></div>
            <span class="chip ${tageBis(k.faellig_am) <= 7 ? 'rot' : tageBis(k.faellig_am) <= 21 ? 'gelb' : ''}">in ${tageBis(k.faellig_am)} Tagen</span>
          </div>`).join('')}
      </article>`);
  }

  // Neu aus den Chats
  if (briefing?.neues?.length) {
    teile.push(`
      <article class="karte">
        <div class="karte-kopf"><h3>Neu aus den Chats</h3></div>
        <ul class="neues-liste">${briefing.neues.map((n) => `
          <li><i class="punkt" style="background:${fachFarbe(n.fach)};margin-top:7px"></i>
            <div><b>${esc(n.fach)}</b><br><span class="leise">${esc(n.text)}</span></div></li>`).join('')}</ul>
      </article>`);
  }

  $('#heute-inhalt').innerHTML = teile.join('');
}

// ---------- Aufgaben ----------
function aufgabeHtml(a) {
  const h = isoHeute();
  const ueber = a.faellig_am && a.faellig_am < h && !a.erledigt;
  return `
    <div class="aufgabe ${a.erledigt ? 'erledigt' : ''}" data-pfad="${esc(a.pfad)}">
      <button class="check" aria-label="Erledigt umschalten">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>
      </button>
      <div class="a-inhalt" role="button" tabindex="0" aria-expanded="false">
        <div class="a-kopf">
          <div class="a-titel">${esc(a.titel)}</div>
          <svg class="pfeil" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
        </div>
        <div class="a-meta">
          <span class="chip" style="background:${fachFarbe(a.fach)}1f;color:${fachFarbe(a.fach)}">${esc(a.fach)}</span>
          <span>${esc(TYP[a.typ] || a.typ)}</span>
          ${a.faellig_am ? `<span class="${ueber ? 'chip rot' : ''}">fällig ${esc(tagText(a.faellig_am))}</span>` : ''}
          ${a.quelle ? `<span>· ${esc(a.quelle === 'untis' ? 'Untis' : 'Logineo')}</span>` : ''}
        </div>
        <div class="a-details" hidden></div>
      </div>
    </div>`;
}

// Mini-Markdown für die Aufgaben-Details: Überschriften, Listen, [[Links]]
function mdLite(text) {
  const link = (s) => s.replace(/\[\[(?:\d{4}-\d{2}-\d{2}_(?:\d{4}_)?)?([^\]|]+?)(?:\.md)?(?:\|([^\]]+))?\]\]/g, (_, ziel, label) => `<b>${label || ziel}</b>`);
  const html = [];
  let liste = false;
  for (const roh of String(text || '').split('\n')) {
    const z = roh.trim();
    if (!z) continue;
    const e = link(esc(z));
    if (z.startsWith('- ') || z.startsWith('* ')) {
      if (!liste) { html.push('<ul>'); liste = true; }
      html.push(`<li>${e.slice(2)}</li>`);
      continue;
    }
    if (liste) { html.push('</ul>'); liste = false; }
    if (z.startsWith('## ')) html.push(`<h4>${e.slice(3)}</h4>`);
    else if (z.startsWith('Aus: ') || z.startsWith('Gestellt am')) html.push(`<p class="leise klein-p">${e}</p>`);
    else html.push(`<p>${e}</p>`);
  }
  if (liste) html.push('</ul>');
  return html.join('') || '<p class="leise">Keine weiteren Details.</p>';
}

const detailCache = new Map();
async function detailsUmschalten(inhalt) {
  const box = inhalt.querySelector('.a-details');
  const offen = !box.hidden;
  box.hidden = offen;
  inhalt.setAttribute('aria-expanded', String(!offen));
  inhalt.closest('.aufgabe').classList.toggle('offen', !offen);
  if (offen) return;
  const pfad = inhalt.closest('.aufgabe').dataset.pfad;
  if (detailCache.has(pfad)) { box.innerHTML = detailCache.get(pfad); return; }
  box.innerHTML = '<p class="leise">Lade …</p>';
  try {
    const d = await api('/api/aufgabe?pfad=' + encodeURIComponent(pfad));
    const html = mdLite(d.text);
    detailCache.set(pfad, html);
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<p class="leise">Details konnten nicht geladen werden.</p>';
  }
}

function zeichneAufgaben() {
  const h = isoHeute(), m = plusTage(h, 1), w = plusTage(h, 7);
  const liste = zustand.aufgaben;
  const gruppen = [
    ['ueberfaellig', 'Überfällig', (a) => a.faellig_am && a.faellig_am < h && !a.erledigt],
    ['heute', 'Heute', (a) => a.faellig_am === h],
    ['morgen', 'Morgen', (a) => a.faellig_am === m],
    ['woche', 'Diese Woche', (a) => a.faellig_am > m && a.faellig_am <= w],
    ['spaeter', 'Später', (a) => a.faellig_am > w],
    ['ohne', 'Ohne Datum', (a) => !a.faellig_am],
  ];
  const benutzt = new Set();
  const html = gruppen.map(([key, titel, f]) => {
    const drin = liste.filter((a) => !benutzt.has(a.pfad) && f(a));
    drin.forEach((a) => benutzt.add(a.pfad));
    if (!drin.length) return '';
    return `<article class="karte gruppe ${key}"><h3><span>${titel}</span><span>${drin.length}</span></h3>${drin.map(aufgabeHtml).join('')}</article>`;
  }).join('');
  // Erledigte mit Datum in der Vergangenheit, die in keine Gruppe passen
  const rest = liste.filter((a) => !benutzt.has(a.pfad));
  const restHtml = rest.length ? `<article class="karte gruppe"><h3><span>Erledigt</span><span>${rest.length}</span></h3>${rest.map(aufgabeHtml).join('')}</article>` : '';
  $('#aufgaben-inhalt').innerHTML = (html + restHtml) || `<div class="karte leer">🎉 Keine offenen Aufgaben</div>`;
}

async function umschalten(el) {
  const pfad = el.dataset.pfad;
  const a = zustand.aufgaben.find((x) => x.pfad === pfad);
  if (!a) return;
  const neu = !a.erledigt;
  a.erledigt = neu;                                  // sofort anzeigen …
  document.querySelectorAll(`.aufgabe[data-pfad="${CSS.escape(pfad)}"]`).forEach((n) => n.classList.toggle('erledigt', neu));
  if (navigator.vibrate) navigator.vibrate(15);
  try {
    await api('/api/aufgaben/erledigt', { method: 'POST', body: JSON.stringify({ pfad, erledigt: neu }) });
    toast(neu ? 'Erledigt ✓' : 'Wieder offen');
    setTimeout(() => {                               // … und nach kurzer Zeit aus der Liste nehmen
      if (neu && !zustand.zeigeErledigte) zustand.aufgaben = zustand.aufgaben.filter((x) => x.pfad !== pfad);
      zeichneKopf(); zeichneHeute(); zeichneAufgaben(); zeichneInfo();
    }, 700);
  } catch (e) {
    a.erledigt = !neu;                               // … und bei Fehler zurücksetzen
    document.querySelectorAll(`.aufgabe[data-pfad="${CSS.escape(pfad)}"]`).forEach((n) => n.classList.toggle('erledigt', !neu));
    toast('Konnte nicht speichern');
  }
}

// ---------- Einstellungen / Push ----------
function zeichneInfo() {
  const sp = zustand.heute?.stundenplan;
  const b = zustand.heute?.briefing;
  $('#info-stand').innerHTML = `Untis-Stand: ${esc(sp?.stand ? tagText(sp.stand) : 'unbekannt')}<br>Letztes Briefing: ${esc(b ? `${tagText(b.datum)} ${(b.erstellt || '').slice(11)}` : '–')}<br>Offene Aufgaben: ${zustand.aufgaben.filter((a) => !a.erledigt).length}`;
}

function b64ToUint8(b64) {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function pushStatus() {
  const st = $('#push-status'), btn = $('#btn-push'), test = $('#btn-push-test');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    st.textContent = 'Dein Browser unterstützt keine Push-Benachrichtigungen.'; btn.hidden = true; return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (Notification.permission === 'denied') {
    st.textContent = 'Benachrichtigungen sind blockiert – in den Browser-/App-Einstellungen erlauben.'; btn.hidden = true; return;
  }
  st.textContent = sub ? 'Aktiv auf diesem Gerät ✓' : 'Aus';
  btn.textContent = sub ? 'Deaktivieren' : 'Aktivieren';
  btn.hidden = false; test.hidden = !sub;
}

async function pushUmschalten() {
  const btn = $('#btn-push'); btn.disabled = true;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await api('/api/push/unsubscribe', { method: 'POST', body: JSON.stringify(sub.toJSON()) });
      await sub.unsubscribe();
      toast('Benachrichtigungen aus');
    } else {
      const erlaubt = await Notification.requestPermission();
      if (erlaubt !== 'granted') { toast('Nicht erlaubt'); return; }
      const { key } = await api('/api/push/key');
      const neu = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(key) });
      await api('/api/push/subscribe', { method: 'POST', body: JSON.stringify(neu.toJSON()) });
      toast('Benachrichtigungen an ✓');
    }
  } catch (e) {
    toast('Fehler: ' + e.message);
  } finally {
    btn.disabled = false; pushStatus();
  }
}

// ---------- Navigation ----------
function zeige(ziel) {
  document.querySelectorAll('.ansicht').forEach((s) => (s.hidden = s.id !== `ansicht-${ziel}`));
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('aktiv', t.dataset.ziel === ziel));
  if (location.hash !== '#' + ziel) history.replaceState(null, '', '#' + ziel);
  window.scrollTo(0, 0);
  if (ziel === 'einstellungen') pushStatus();
}

document.addEventListener('click', (e) => {
  const tab = e.target.closest('.tab'); if (tab) return zeige(tab.dataset.ziel);
  const check = e.target.closest('.aufgabe .check'); if (check) return umschalten(check.closest('.aufgabe'));
  const inhalt = e.target.closest('.aufgabe .a-inhalt'); if (inhalt) return detailsUmschalten(inhalt);
  const link = e.target.closest('a[href^="#"]'); if (link) { e.preventDefault(); zeige(link.getAttribute('href').slice(1)); }
});
$('#btn-neu').addEventListener('click', laden);
$('#btn-push').addEventListener('click', pushUmschalten);
$('#btn-push-test').addEventListener('click', async () => {
  try { const r = await api('/api/push/test', { method: 'POST' }); toast(`Gesendet an ${r.gesendet} Gerät(e)`); } catch (e) { toast('Fehler: ' + e.message); }
});
$('#zeige-erledigte').addEventListener('change', (e) => { zustand.zeigeErledigte = e.target.checked; laden(); });
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') laden(); });

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
const start = (location.hash || '').slice(1);
zeige(['heute', 'aufgaben', 'einstellungen'].includes(start) ? start : 'heute');
laden();
