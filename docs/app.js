/* Classement des youtubeurs SLA : charge les 3 CSV du dossier data/ et les affiche. */
(() => {
  'use strict';

  const MODES = {
    bot: {
      title: 'Battlefield of Time', file: 'data/classement_bot.csv',
      total: ['chrono_s', 'chrono'], t1: [], t2: [],
      better: 'low', kpiRecord: 'Meilleur chrono', totalHeader: 'Chrono',
      fmt: (v) => nf3.format(v) + ' s',
      note: 'Chrono de la phase 3 : le plus court est en tête. L’écart est mesuré par rapport au meilleur chrono de la semaine.',
    },
    gb: {
      title: 'Boss de Guilde', file: 'data/classement_gb.csv',
      total: ['rc_total', 'total_rc', 'total'], t1: ['rc_equipe_1', 'equipe_1'], t2: ['rc_equipe_2', 'equipe_2'],
      better: 'high', kpiRecord: 'Record de Rage Count', totalHeader: 'Total RC',
      fmt: (v) => nf0.format(v),
      unit: 'RC',
      note: 'Total de Rage Count (RC) des équipes montrées dans la vidéo. À égalité de RC, les dégâts totaux départagent, puis la vidéo publiée en premier.',
    },
    poc: {
      title: 'Puissance de Calamité', file: 'data/classement_poc.csv',
      total: ['total_t', 'total'], t1: ['equipe_1_t', 'equipe_1'], t2: ['equipe_2_t', 'equipe_2'],
      better: 'high', kpiRecord: 'Record de dégâts', totalHeader: 'Dégâts',
      fmt: (v) => nfT.format(v) + ' T',
      note: 'Dégâts en T (1 T = mille milliards, soit 10¹²). Quand deux équipes sont montrées, le total des deux sert au classement.',
    },
  };
  const ORDER = ['bot', 'gb', 'poc'];
  const SOURCES = {
    'titre': 'Titre',
    'description': 'Description',
    'claude': 'Lu sur l’image',
    'titre sans rc écrit': 'Titre (RC non écrit)',
  };

  const nf0 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
  const nf3 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  const nfT = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 4 });
  const nfPct = new Intl.NumberFormat('fr-FR', { style: 'percent', maximumFractionDigits: 1 });

  const state = {}; // par mode : { status, rows, error, modified }
  ORDER.forEach((m) => { state[m] = { status: 'loading', rows: [], error: '', modified: null }; });
  let current = 'bot';
  let query = '';

  const $ = (id) => document.getElementById(id);
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  /* ---------- CSV ---------- */
  function parseCSV(text) {
    text = text.replace(/^﻿/, '');
    const rows = []; let row = []; let cell = ''; let inQ = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inQ) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else inQ = false; }
        else cell += c;
      } else if (c === '"') inQ = true;
      else if (c === ';') { row.push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cell); cell = '';
        if (row.some((x) => x !== '')) rows.push(row);
        row = [];
      } else cell += c;
    }
    row.push(cell);
    if (row.some((x) => x !== '')) rows.push(row);
    if (!rows.length) return { headers: [], records: [] };
    const headers = rows[0].map((x) => x.trim().toLowerCase());
    const records = rows.slice(1).map((r) => Object.fromEntries(headers.map((k, i) => [k, (r[i] ?? '').trim()])));
    return { headers, records };
  }
  const pick = (rec, names) => { for (const n of names) if (n in rec && rec[n] !== '') return rec[n]; return ''; };
  const num = (s) => { if (s === '') return null; const v = parseFloat(String(s).replace(',', '.')); return Number.isFinite(v) ? v : null; };
  const safeUrl = (s) => { try { const u = new URL(s); return /^https?:$/.test(u.protocol) ? u.href : null; } catch { return null; } };

  function toRows(mode, parsed) {
    const cfg = MODES[mode];
    if (parsed.records.length && !cfg.total.some((n) => parsed.headers.includes(n))) {
      throw new Error('colonnes non reconnues (' + parsed.headers.join(', ') + ')');
    }
    const rows = parsed.records.map((r) => ({
      rang: num(r.rang),
      chaine: (r.chaine || '').trim(),
      t1: num(pick(r, cfg.t1)),
      t2: num(pick(r, cfg.t2)),
      total: num(pick(r, cfg.total)),
      source: (r.lu_dans || '').trim(),
      titre: (r.titre_video || '').trim(),
      date: r.date ? new Date(r.date) : null,
      url: safeUrl(r.url),
    })).filter((r) => r.chaine);
    rows.sort((a, b) => {
      if (a.rang != null && b.rang != null) return a.rang - b.rang;
      const d = (a.total ?? 0) - (b.total ?? 0);
      return cfg.better === 'low' ? d : -d;
    });
    return rows;
  }

  async function load(mode) {
    const s = state[mode];
    s.status = 'loading'; s.error = '';
    render();
    try {
      const res = await fetch(MODES[mode].file, { cache: 'no-cache' });
      if (!res.ok) throw new Error('fichier introuvable (' + res.status + ')');
      const lm = res.headers.get('Last-Modified');
      s.modified = lm ? new Date(lm) : null;
      s.rows = toRows(mode, parseCSV(await res.text()));
      s.status = 'ok';
    } catch (e) {
      s.status = 'error'; s.error = e && e.message ? e.message : String(e);
    }
    render();
  }

  /* ---------- Semaine (jeudi 01h, heure de Paris) ---------- */
  function weekRange(now = new Date()) {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Paris', hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: 'numeric',
    }).formatToParts(now).filter((x) => x.type !== 'literal').map((x) => [x.type, +x.value]));
    const local = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
    const dow = new Date(local).getUTCDay(); // 4 = jeudi
    let since = (dow - 4 + 7) % 7;
    if (since === 0 && p.hour < 1) since = 7;
    const start = Date.UTC(p.year, p.month - 1, p.day - since, 1, 0);
    return { start: new Date(start), end: new Date(start + 7 * 864e5) };
  }
  const dm = (d) => d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', timeZone: 'UTC' });

  /* ---------- Rendu ---------- */
  function sourceLabel(s) { return SOURCES[s.toLowerCase()] || s || '—'; }
  function fmtDate(d) {
    return d && !isNaN(d) ? d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', timeZone: 'Europe/Paris' }) : '—';
  }
  function fmtDateLong(d) {
    return d && !isNaN(d) ? d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Paris' }) : '';
  }
  function chip(rank) {
    return h('span', { class: 'chip' + (rank >= 1 && rank <= 3 ? ' r' + rank : ''), text: rank != null ? String(rank) : '–' });
  }

  function metrics(mode, rows) {
    const cfg = MODES[mode];
    const vals = rows.map((r) => r.total).filter((v) => v != null);
    const best = vals.length ? (cfg.better === 'low' ? Math.min(...vals) : Math.max(...vals)) : null;
    return rows.map((r) => {
      if (best == null || r.total == null || r.total === 0) return { pct: null, gap: null };
      const pct = cfg.better === 'low' ? best / r.total : r.total / best;
      return { pct, gap: cfg.better === 'low' ? r.total - best : null };
    }).map((m) => ({ ...m, best }));
  }

  function renderKpis(mode, rows) {
    const cfg = MODES[mode];
    const box = $('kpis'); box.replaceChildren();
    if (!rows.length) return;
    const leader = rows[0];
    const best = metrics(mode, rows)[0]?.best;
    const recordText = best == null ? '—' : cfg.fmt(best) + (cfg.unit ? ' ' + cfg.unit : '');
    box.append(
      h('div', { class: 'kpi' }, h('h2', { text: 'Chaînes classées' }), h('div', { class: 'big', text: String(rows.length) }), h('p', { class: 'sub', text: 'cette semaine' })),
      h('div', { class: 'kpi' }, h('h2', { text: cfg.kpiRecord }), h('div', { class: 'big', text: recordText }), h('p', { class: 'sub', text: 'cette semaine' })),
      h('div', { class: 'kpi' }, h('h2', { text: 'Chaîne en tête' }), h('div', { class: 'big name', text: leader.chaine }), h('p', { class: 'sub', text: leader.total != null ? cfg.fmt(leader.total) + (cfg.unit ? ' ' + cfg.unit : '') : '' })),
    );
  }

  function stateBox(title, text, btnLabel, onClick) {
    return h('div', { class: 'state' }, h('h2', { text: title }), h('p', { text }),
      btnLabel ? h('button', { class: 'btn', type: 'button' }, btnLabel) : null);
  }

  function renderTable(mode, rows, met, showTeams) {
    const cfg = MODES[mode];
    const head = h('tr', null,
      h('th', { scope: 'col', class: 'rank', text: 'Rang' }),
      h('th', { scope: 'col', text: 'Chaîne' }),
      showTeams ? h('th', { scope: 'col', class: 'num', text: 'Équipe 1' }) : null,
      showTeams ? h('th', { scope: 'col', class: 'num', text: 'Équipe 2' }) : null,
      h('th', { scope: 'col', class: 'num', text: cfg.totalHeader }),
      h('th', { scope: 'col', class: 'num', text: cfg.better === 'low' ? 'Écart au 1er' : '% du 1er' }),
      h('th', { scope: 'col', text: 'Chiffre lu dans' }),
      h('th', { scope: 'col', text: 'Vidéo' }),
      h('th', { scope: 'col', text: 'Date' }),
      h('th', { scope: 'col', text: 'Lien' }),
    );
    const body = h('tbody');
    rows.forEach((r, i) => {
      const m = met.get(r);
      const pctTxt = m.pct == null ? '—' : (cfg.better === 'low' ? (m.gap > 0 ? '+' + nf3.format(m.gap) + ' s' : 'record') : nfPct.format(m.pct));
      body.append(h('tr', null,
        h('td', { class: 'rank' }, chip(r.rang)),
        h('th', { scope: 'row', class: 'channel', text: r.chaine, style: 'font-weight:650' }),
        showTeams ? h('td', { class: 'num', text: r.t1 != null ? cfg.fmt(r.t1) : '—' }) : null,
        showTeams ? h('td', { class: 'num', text: r.t2 != null ? cfg.fmt(r.t2) : '—' }) : null,
        h('td', { class: 'num total', text: r.total != null ? cfg.fmt(r.total) : '—' }),
        h('td', { class: 'level' },
          h('span', { class: 'pct', text: pctTxt }),
          (m.pct != null && cfg.better !== 'low') ? h('div', { class: 'bar', 'aria-hidden': 'true' }, h('span', { style: 'width:' + Math.max(2, Math.round(m.pct * 100)) + '%' })) : null),
        h('td', null, h('span', { class: 'src', text: sourceLabel(r.source) })),
        h('td', null, h('span', { class: 'video-title', title: r.titre, text: r.titre || '—' })),
        h('td', { class: 'date' }, r.date && !isNaN(r.date) ? h('time', { datetime: r.date.toISOString(), text: fmtDate(r.date) }) : '—'),
        h('td', null, r.url ? h('a', { class: 'btn', href: r.url, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Voir la vidéo de ' + r.chaine + ' (nouvel onglet)' }, '▶ Voir') : '—'),
      ));
    });
    return h('div', { class: 'table-wrap' }, h('table', null,
      h('caption', { class: 'sr-only', text: 'Classement ' + cfg.title + ' de la semaine' }), h('thead', null, head), body));
  }

  function renderCards(mode, rows, met) {
    const cfg = MODES[mode];
    return h('ul', { class: 'cards', 'aria-label': 'Classement ' + cfg.title }, rows.map((r) => {
      const m = met.get(r);
      const pctTxt = m.pct == null ? '' : (cfg.better === 'low' ? (m.gap > 0 ? '+' + nf3.format(m.gap) + ' s' : 'record') : nfPct.format(m.pct));
      return h('li', { class: 'card' },
        h('div', { class: 'card-head' }, chip(r.rang), h('span', { class: 'channel', text: r.chaine }), h('span', { class: 'total', text: r.total != null ? cfg.fmt(r.total) : '—' })),
        (r.t1 != null && r.t2 != null) ? h('p', { class: 'card-teams', text: 'Équipe 1 : ' + cfg.fmt(r.t1) + ' · Équipe 2 : ' + cfg.fmt(r.t2) }) : null,
        (m.pct != null && cfg.better !== 'low') ? h('div', { class: 'card-level' }, h('div', { class: 'bar', 'aria-hidden': 'true' }, h('span', { style: 'width:' + Math.max(2, Math.round(m.pct * 100)) + '%' })), h('span', { class: 'pct', text: pctTxt })) : null,
        (m.pct != null && cfg.better === 'low') ? h('p', { class: 'card-teams', text: pctTxt === 'record' ? 'Meilleur chrono de la semaine' : 'Écart au 1er : ' + pctTxt }) : null,
        h('span', { class: 'video-title', title: r.titre, text: r.titre || '—' }),
        h('div', { class: 'card-meta' }, h('span', { class: 'src', text: sourceLabel(r.source) }), h('span', { class: 'date', text: fmtDate(r.date) })),
        r.url ? h('a', { class: 'btn', href: r.url, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Voir la vidéo de ' + r.chaine + ' (nouvel onglet)' }, '▶ Voir la vidéo') : null,
      );
    }));
  }

  function renderSkeleton() {
    const box = $('kpis'); box.replaceChildren(h('div', { class: 'sk-kpi' }), h('div', { class: 'sk-kpi' }), h('div', { class: 'sk-kpi' }));
    $('results').replaceChildren(h('div', { class: 'skeleton', 'aria-hidden': 'true' }, [1, 2, 3, 4, 5, 6].map(() => h('div', { class: 'sk-row' }))),
      h('p', { class: 'sr-only', role: 'status', text: 'Chargement du classement…' }));
  }

  function render() {
    ORDER.forEach((m) => {
      const s = state[m];
      $('count-' + m).textContent = s.status === 'ok' ? String(s.rows.length) : (s.status === 'error' ? '!' : '…');
    });
    updateMeta();
    const mode = current; const s = state[mode]; const cfg = MODES[mode];
    $('panel').dataset.mode = mode;
    $('panel').setAttribute('aria-labelledby', 'tab-' + mode);
    $('note').textContent = '';
    $('count').textContent = '';
    $('toolbar').hidden = s.status !== 'ok' || !s.rows.length;
    const results = $('results');

    if (s.status === 'loading') return renderSkeleton();
    if (s.status === 'error') {
      $('kpis').replaceChildren();
      const box = stateBox('Impossible de charger le classement', 'Le fichier du classement ' + cfg.title + ' n’a pas pu être lu : ' + s.error + '.', 'Réessayer');
      box.querySelector('button').addEventListener('click', () => load(mode));
      results.replaceChildren(box);
      return;
    }
    if (!s.rows.length) {
      $('kpis').replaceChildren();
      results.replaceChildren(stateBox('Aucun résultat cette semaine', 'Aucune vidéo classée pour ' + cfg.title + ' pour le moment. Le classement repart de zéro chaque jeudi à 01h (heure de Paris).'));
      return;
    }

    renderKpis(mode, s.rows);
    const met = new Map(); const mm = metrics(mode, s.rows); s.rows.forEach((r, i) => met.set(r, mm[i]));
    const q = query.trim().toLowerCase();
    const shown = q ? s.rows.filter((r) => r.chaine.toLowerCase().includes(q)) : s.rows;
    $('count').textContent = shown.length + ' chaîne' + (shown.length > 1 ? 's' : '') + (q ? ' sur ' + s.rows.length : '');
    if (!shown.length) {
      const box = stateBox('Aucune chaîne trouvée', 'Aucune chaîne ne correspond à « ' + query.trim() + ' » dans ' + cfg.title + '.', 'Effacer la recherche');
      box.querySelector('button').addEventListener('click', () => { query = ''; $('q').value = ''; render(); $('q').focus(); });
      results.replaceChildren(box);
    } else {
      const showTeams = s.rows.some((r) => r.t2 != null);
      results.replaceChildren(renderTable(mode, shown, met, showTeams), renderCards(mode, shown, met));
    }
    $('note').textContent = cfg.note;
  }

  function updateMeta() {
    const w = weekRange();
    $('week').textContent = 'Semaine du jeudi ' + dm(w.start) + ' au jeudi ' + dm(w.end) + ' (01h, heure de Paris)';
    const mods = ORDER.map((m) => state[m].modified).filter((d) => d && !isNaN(d));
    $('updated').textContent = mods.length ? 'Page mise à jour le ' + fmtDateLong(new Date(Math.max(...mods))) : '';
  }

  /* ---------- Onglets (clavier : flèches, Début, Fin) ---------- */
  function select(mode, focus) {
    current = mode;
    document.querySelectorAll('.tab').forEach((t) => {
      const on = t.dataset.mode === mode;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    if (location.hash !== '#' + mode) history.replaceState(null, '', '#' + mode);
    render();
  }
  $('tabs').addEventListener('click', (e) => { const t = e.target.closest('.tab'); if (t) select(t.dataset.mode); });
  $('tabs').addEventListener('keydown', (e) => {
    const i = ORDER.indexOf(current); let n = null;
    if (e.key === 'ArrowRight') n = (i + 1) % ORDER.length;
    else if (e.key === 'ArrowLeft') n = (i + ORDER.length - 1) % ORDER.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = ORDER.length - 1;
    if (n != null) { e.preventDefault(); select(ORDER[n], true); }
  });
  $('q').addEventListener('input', (e) => { query = e.target.value; render(); });
  window.addEventListener('hashchange', () => { const m = location.hash.slice(1); if (MODES[m] && m !== current) select(m); });

  /* Bouton de thème : clair ou sombre. Sans choix du visiteur, on suit le réglage de son appareil. */
  const root = document.documentElement;
  const themeBtn = $('theme');
  const systemDark = () => !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  const theme = () => root.getAttribute('data-theme') || (systemDark() ? 'dark' : 'light');
  const paintTheme = () => {
    const dark = theme() === 'dark';
    themeBtn.textContent = dark ? '☀ Thème clair' : '☾ Thème sombre';
    themeBtn.setAttribute('aria-label', dark ? 'Passer au thème clair' : 'Passer au thème sombre');
  };
  themeBtn.addEventListener('click', () => {
    const next = theme() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('sla-theme', next); } catch (e) { /* stockage indisponible : le choix n'est pas gardé */ }
    paintTheme();
  });
  paintTheme();

  const start = location.hash.slice(1);
  if (MODES[start]) current = start;
  select(current);
  ORDER.forEach(load);
})();
