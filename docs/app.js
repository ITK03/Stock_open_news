/**
 * 開示レーダー — app.js
 * TDnet 適時開示モニター
 * Vanilla JS, no build step.
 */

'use strict';

/* ===== 定数 ===== */
const DATA_URL          = './data/disclosures.json';
const ARCHIVE_INDEX_URL = './data/archive/index.json';
const ARCHIVE_BASE_URL  = './data/archive/';
const AUTO_REFRESH_MS   = 60_000; // 60秒

/* ===== localStorage キー (名前空間: kaiji.*) ===== */
const LS_THEME         = 'kaiji.theme';
const LS_WATCHLIST     = 'kaiji.watchlist';
const LS_LAST_SEEN     = 'kaiji.lastSeen';
const LS_NOTIFY        = 'kaiji.notify';
const LS_FILTER_IMPACT = 'kaiji.filter.impact';
const LS_FILTER_CAT    = 'kaiji.filter.category';
const LS_FILTER_URGENT = 'kaiji.filter.urgent';
const LS_FILTER_WL     = 'kaiji.filter.watchlist';
const LS_SORT_ORDER    = 'kaiji.sort';

/* ===== 状態 ===== */
const state = {
  items:       [],
  updatedAt:   null,
  totalCount:  0,

  filterImpact:    'all',
  filterCategory:  'all',
  filterUrgent:    false,
  filterKeyword:   '',
  filterWatchlist: false,
  filterStockCode: null,
  filterNewOnly:   false,
  sortOrder:       'time',

  loading:      false,
  error:        null,
  selectedDate: null, // null = ライブ

  lastSeenTs:   0,
  watchlist:    new Set(),
  notifyEnabled: false,
  notifiedIds:  new Set(),
};

/* ===== 自動更新タイマー ===== */
let autoRefreshTimer     = null;
let relTimeRefreshTimer  = null;

function startAutoRefresh() {
  stopAutoRefresh();
  autoRefreshTimer = setInterval(() => fetchData({ silent: true }), AUTO_REFRESH_MS);
  // 相対時刻も60秒ごと更新
  relTimeRefreshTimer = setInterval(() => updateAllRelTimes(), AUTO_REFRESH_MS);
  updateLiveIndicator(true);
}

function stopAutoRefresh() {
  if (autoRefreshTimer !== null)    { clearInterval(autoRefreshTimer);    autoRefreshTimer    = null; }
  if (relTimeRefreshTimer !== null) { clearInterval(relTimeRefreshTimer); relTimeRefreshTimer = null; }
  updateLiveIndicator(false);
}

/** 相対時刻だけ再計算してDOMを更新(データ再取得なし) */
function updateAllRelTimes() {
  const spans = document.querySelectorAll('.time-rel[data-ts]');
  for (const span of spans) {
    const ts = parseInt(span.dataset.ts, 10);
    if (ts) span.textContent = relativeTime(ts);
  }
}

function updateLiveIndicator(isLive) {
  const ind = el.liveIndicator;
  if (!ind) return;
  if (isLive) {
    ind.removeAttribute('data-paused');
    const lbl = document.getElementById('live-label');
    if (lbl) lbl.textContent = 'LIVE';
    ind.setAttribute('aria-label', 'ライブ更新中');
  } else {
    ind.setAttribute('data-paused', 'true');
    const lbl = document.getElementById('live-label');
    if (lbl) lbl.textContent = '停止中';
    ind.setAttribute('aria-label', '自動更新停止中');
  }
}

/* ===== DOM 参照キャッシュ ===== */
const el = {};

/* ===== ユーティリティ ===== */

function parseTime(iso) {
  if (!iso) return { hhmm: '--:--', date: '', ts: 0 };
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return { hhmm: '--:--', date: '', ts: 0 };
    const pad = (n) => String(n).padStart(2, '0');
    const jst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
    const hhmm = `${pad(jst.getUTCHours())}:${pad(jst.getUTCMinutes())}`;
    const date  = `${jst.getUTCMonth() + 1}/${jst.getUTCDate()}`;
    return { hhmm, date, ts: d.getTime() };
  } catch {
    return { hhmm: '--:--', date: '', ts: 0 };
  }
}

function formatUpdatedAt(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, '0');
    const jst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
    return `${jst.getUTCFullYear()}/${pad(jst.getUTCMonth()+1)}/${pad(jst.getUTCDate())} `
         + `${pad(jst.getUTCHours())}:${pad(jst.getUTCMinutes())} JST`;
  } catch { return iso; }
}

function relativeTime(ts) {
  if (!ts) return '';
  const diff = Date.now() - ts;
  if (diff < 0) return 'たった今';
  const mins  = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days  = Math.floor(diff / 86_400_000);
  if (mins  < 1)   return 'たった今';
  if (mins  < 60)  return `${mins}分前`;
  if (hours < 24)  return `${hours}時間前`;
  return `${days}日前`;
}

function safePdfUrl(url) {
  if (!url || typeof url !== 'string') return null;
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
    return u.href;
  } catch { return null; }
}

/** 証券コードを4文字に正規化。英数字コード(例 546A)も保持する。
 *  5文字(末尾0の旧表記 例 546A0/72030) → 先頭4文字。4文字はそのまま。 */
function normalizeCode4(code) {
  if (!code) return null;
  const s = String(code).trim().toUpperCase();
  if (/^[0-9][0-9A-Z]{3}0$/.test(s)) return s.slice(0, 4); // 5文字(末尾0) → 4文字
  if (/^[0-9][0-9A-Z]{3}$/.test(s))  return s;             // 4文字(英数字可)
  return null;
}

function createTextEl(tag, text, className) {
  const elem = document.createElement(tag);
  if (className) elem.className = className;
  elem.textContent = String(text ?? '');
  return elem;
}

/* ===== テーマ管理 ===== */

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const meta = document.getElementById('meta-theme-color');
  if (meta) {
    meta.setAttribute('content', theme === 'light' ? '#ffffff' : '#0d1117');
  }
  try { localStorage.setItem(LS_THEME, theme); } catch { /* ok */ }
}

function initTheme() {
  let saved;
  try { saved = localStorage.getItem(LS_THEME); } catch { /* ok */ }
  if (saved === 'light' || saved === 'dark') {
    applyTheme(saved);
  } else {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    applyTheme(prefersDark ? 'dark' : 'light');
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

/* ===== ウォッチリスト管理 ===== */

function loadWatchlist() {
  try {
    const raw = localStorage.getItem(LS_WATCHLIST);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) { state.watchlist = new Set(arr); return; }
    }
  } catch { /* ok */ }
  state.watchlist = new Set();
}

function saveWatchlist() {
  try { localStorage.setItem(LS_WATCHLIST, JSON.stringify([...state.watchlist])); } catch { /* ok */ }
}

function toggleWatchlist(code) {
  if (!code) return;
  const wasStarred = state.watchlist.has(code);
  if (wasStarred) {
    state.watchlist.delete(code);
  } else {
    state.watchlist.add(code);
  }
  saveWatchlist();
  showToast(wasStarred ? `★ ウォッチリストから解除しました` : `★ ウォッチリストに追加しました`);
}

/* ===== 前回訪問時刻 ===== */

function loadLastSeen() {
  try {
    const raw = localStorage.getItem(LS_LAST_SEEN);
    state.lastSeenTs = raw ? parseInt(raw, 10) : 0;
  } catch { state.lastSeenTs = 0; }
}

function saveLastSeen() {
  try { localStorage.setItem(LS_LAST_SEEN, String(Date.now())); } catch { /* ok */ }
}

/* ===== フィルタ永続化 ===== */

function saveFilters() {
  try {
    localStorage.setItem(LS_FILTER_IMPACT, state.filterImpact);
    localStorage.setItem(LS_FILTER_CAT,    state.filterCategory);
    localStorage.setItem(LS_FILTER_URGENT, state.filterUrgent ? '1' : '0');
    localStorage.setItem(LS_FILTER_WL,     state.filterWatchlist ? '1' : '0');
    localStorage.setItem(LS_SORT_ORDER,    state.sortOrder);
  } catch { /* ok */ }
}

function loadFilters() {
  try {
    const impact = localStorage.getItem(LS_FILTER_IMPACT);
    if (impact && ['all','high','medium','low'].includes(impact)) state.filterImpact = impact;

    const urgent = localStorage.getItem(LS_FILTER_URGENT);
    if (urgent) state.filterUrgent = urgent === '1';

    const wl = localStorage.getItem(LS_FILTER_WL);
    if (wl) state.filterWatchlist = wl === '1';

    const sort = localStorage.getItem(LS_SORT_ORDER);
    if (sort && ['time','score','up','down'].includes(sort)) state.sortOrder = sort;
    // category は buildCategoryOptions 後に復元するため別途対応
  } catch { /* ok */ }
}

function restoreCategoryFilter() {
  try {
    const cat = localStorage.getItem(LS_FILTER_CAT);
    if (cat) {
      state.filterCategory = cat;
      if (el.categorySelect) el.categorySelect.value = cat;
    }
  } catch { /* ok */ }
}

/* ===== フィルタUI同期 ===== */

function syncFilterUI() {
  // impact ボタン
  if (el.impactBtns) {
    el.impactBtns.forEach((b) => {
      const active = b.dataset.impact === state.filterImpact;
      b.classList.toggle('active', active);
      b.setAttribute('aria-pressed', String(active));
    });
  }
  // urgent
  if (el.urgentCheck) el.urgentCheck.checked = state.filterUrgent;
  // watchlist
  if (el.btnWatchlist) {
    el.btnWatchlist.classList.toggle('active', state.filterWatchlist);
    el.btnWatchlist.setAttribute('aria-pressed', String(state.filterWatchlist));
  }
  // sort
  if (el.sortBtns) {
    el.sortBtns.forEach((b) => {
      const active = b.dataset.sort === state.sortOrder;
      b.classList.toggle('active', active);
      b.setAttribute('aria-pressed', String(active));
    });
  }
  // new-only toggle
  if (el.btnNewOnly) {
    el.btnNewOnly.classList.toggle('active', state.filterNewOnly);
    el.btnNewOnly.setAttribute('aria-pressed', String(state.filterNewOnly));
  }
}

/* ===== ブラウザ通知 ===== */

function loadNotifyPref() {
  try {
    const raw = localStorage.getItem(LS_NOTIFY);
    state.notifyEnabled = raw === '1' && Notification.permission === 'granted';
  } catch { state.notifyEnabled = false; }
  updateNotifyBtn();
}

function updateNotifyBtn() {
  if (!el.btnNotify) return;
  if (state.notifyEnabled) {
    el.btnNotify.classList.add('active');
    el.btnNotify.setAttribute('aria-label', 'ブラウザ通知を無効にする');
  } else {
    el.btnNotify.classList.remove('active');
    el.btnNotify.setAttribute('aria-label', 'ブラウザ通知を有効にする');
  }
}

async function toggleNotify() {
  if (!('Notification' in window)) return;

  if (state.notifyEnabled) {
    state.notifyEnabled = false;
    try { localStorage.setItem(LS_NOTIFY, '0'); } catch { /* ok */ }
    updateNotifyBtn();
    showToast('通知を無効にしました');
    return;
  }

  if (Notification.permission === 'granted') {
    state.notifyEnabled = true;
    try { localStorage.setItem(LS_NOTIFY, '1'); } catch { /* ok */ }
    updateNotifyBtn();
    showToast('通知を有効にしました');
    return;
  }

  if (Notification.permission === 'denied') return;

  const perm = await Notification.requestPermission().catch(() => 'denied');
  if (perm === 'granted') {
    state.notifyEnabled = true;
    try { localStorage.setItem(LS_NOTIFY, '1'); } catch { /* ok */ }
    showToast('通知を有効にしました');
  }
  updateNotifyBtn();
}

function sendNotification(item) {
  if (!state.notifyEnabled) return;
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    const n = new Notification('開示レーダー — 緊急開示', {
      body: `${item.company ?? ''} (${item.code ?? ''}) — ${item.title ?? ''}`,
      icon: './icon.svg',
      tag:  String(item.id ?? ''),
    });
    setTimeout(() => n.close(), 8000);
  } catch { /* ok */ }
}

function checkNewUrgent(newItems) {
  if (!state.notifyEnabled) return;
  for (const item of newItems) {
    if (item.urgent === true && !state.notifiedIds.has(String(item.id ?? ''))) {
      state.notifiedIds.add(String(item.id ?? ''));
      sendNotification(item);
    }
  }
}

/* ===== トースト通知 ===== */

let _toastTimer = null;

function showToast(message, duration = 2800) {
  let toast = document.getElementById('kaiji-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'kaiji-toast';
    toast.className = 'kaiji-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.setAttribute('aria-atomic', 'true');
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add('kaiji-toast--show');

  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    toast.classList.remove('kaiji-toast--show');
  }, duration);
}

/* ===== ヘルプダイアログ ===== */

function openHelp() {
  const existing = document.getElementById('help-dialog');
  if (existing) { existing.showModal(); return; }

  const dlg = document.createElement('dialog');
  dlg.id = 'help-dialog';
  dlg.className = 'help-dialog';

  const header = document.createElement('div');
  header.className = 'help-header';
  const title = createTextEl('h2', 'スコアリング凡例', 'help-title');
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'help-close-btn';
  closeBtn.setAttribute('aria-label', 'ヘルプを閉じる');
  closeBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
  closeBtn.addEventListener('click', () => dlg.close());
  header.appendChild(title);
  header.appendChild(closeBtn);
  dlg.appendChild(header);

  const body = document.createElement('div');
  body.className = 'help-body';

  const sections = [
    {
      heading: 'スコア (0〜100)',
      items: [
        '開示の重要度を0〜100の数値で表します。',
        '市場インパクト・緊急性・確信度を複合評価した独自スコアです。',
      ],
    },
    {
      heading: '重要度',
      items: [
        '高 (High): 株価に大きな影響を与える可能性が高い開示。決算、M&A、業績修正など。',
        '中 (Medium): 一定のインパクトが見込まれる開示。人事異動、契約締結など。',
        '低 (Low): 軽微な開示、定型的な情報開示など。',
      ],
    },
    {
      heading: '方向性',
      items: [
        '▲ 上昇: 株価にポジティブな影響が見込まれる内容。',
        '▼ 下落: 株価にネガティブな影響が見込まれる内容。',
        '─ 中立: 影響が限定的または中立的な内容。',
        '? 不明: 方向性が判断できない内容。',
      ],
    },
    {
      heading: '⚡ 緊急',
      items: [
        '速報性・重要性が特に高い開示。市場開示直後などに付与されます。',
      ],
    },
    {
      heading: '確信度 (%)',
      items: [
        'AIによるスコアリングの確信度を示します。高いほど評価の信頼性が高くなります。',
      ],
    },
  ];

  for (const sec of sections) {
    const secEl = document.createElement('section');
    secEl.className = 'help-section';
    secEl.appendChild(createTextEl('h3', sec.heading, 'help-section-title'));
    const ul = document.createElement('ul');
    ul.className = 'help-list';
    for (const item of sec.items) {
      ul.appendChild(createTextEl('li', item, 'help-list-item'));
    }
    secEl.appendChild(ul);
    body.appendChild(secEl);
  }

  dlg.appendChild(body);
  document.body.appendChild(dlg);

  // ESC は dialog の組み込み動作で閉じる
  // focus trap: 簡易実装
  dlg.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const focusables = Array.from(dlg.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )).filter((el2) => !el2.disabled);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last  = focusables[focusables.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last)  { e.preventDefault(); first.focus(); }
    }
  });

  dlg.showModal();
  // 閉じた後フォーカスをヘルプボタンへ
  dlg.addEventListener('close', () => {
    if (el.btnHelp) el.btnHelp.focus();
  }, { once: true });
}

/* ===== カテゴリ options 構築 ===== */

function buildCategoryOptions() {
  const categories = new Set();
  for (const item of state.items) {
    if (item.category) categories.add(item.category);
  }
  const sel = el.categorySelect;
  const current = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  for (const cat of [...categories].sort()) {
    const opt = document.createElement('option');
    opt.value       = cat;
    opt.textContent = cat;
    sel.appendChild(opt);
  }
  if ([...categories].includes(current)) sel.value = current;
}

/* ===== サマリーストリップ更新 ===== */

function renderSummary(items) {
  const total  = items.length;
  const high   = items.filter((i) => i.impact === 'high').length;
  const urgent = items.filter((i) => i.urgent === true).length;

  const catCount = {};
  for (const item of items) {
    if (item.category) catCount[item.category] = (catCount[item.category] || 0) + 1;
  }
  const topCat = Object.entries(catCount).sort((a, b) => b[1] - a[1])[0];

  const setText = (id, text) => {
    const elem = document.getElementById(id);
    if (elem) elem.textContent = text;
  };

  setText('stat-total',    total);
  setText('stat-high',     high);
  setText('stat-urgent',   urgent);
  setText('stat-category', topCat ? topCat[0] : '—');

  // サマリーボタンの active 状態を更新
  updateSummaryActiveStates();
}

function updateSummaryActiveStates() {
  const btnHigh     = document.getElementById('stat-btn-high');
  const btnUrgent   = document.getElementById('stat-btn-urgent');
  const btnCategory = document.getElementById('stat-btn-category');
  if (btnHigh)     btnHigh.classList.toggle('active',   state.filterImpact === 'high');
  if (btnUrgent)   btnUrgent.classList.toggle('active', state.filterUrgent === true);
  if (btnCategory) {
    const catVal = document.getElementById('stat-category')?.textContent;
    btnCategory.classList.toggle('active', state.filterCategory !== 'all' && catVal && state.filterCategory === catVal);
  }
}

/* ===== フィルタ & ソート ===== */

function applyFilters() {
  let result = state.items.slice();

  if (state.filterImpact !== 'all') {
    result = result.filter((i) => i.impact === state.filterImpact);
  }
  if (state.filterCategory !== 'all') {
    result = result.filter((i) => i.category === state.filterCategory);
  }
  if (state.filterUrgent) {
    result = result.filter((i) => i.urgent === true);
  }
  if (state.filterWatchlist) {
    result = result.filter((i) => i.code && state.watchlist.has(String(i.code)));
  }
  if (state.filterStockCode) {
    result = result.filter((i) => String(i.code ?? '') === state.filterStockCode);
  }
  if (state.filterNewOnly && state.lastSeenTs > 0) {
    result = result.filter((i) => {
      const ts = i.time ? new Date(i.time).getTime() : 0;
      return ts > state.lastSeenTs;
    });
  }

  const kw = state.filterKeyword.trim().toLowerCase();
  if (kw) {
    result = result.filter((i) =>
      (i.company  && i.company.toLowerCase().includes(kw))  ||
      (i.code     && i.code.toLowerCase().includes(kw))     ||
      (i.title    && i.title.toLowerCase().includes(kw))    ||
      (i.summary  && i.summary.toLowerCase().includes(kw))
    );
  }

  if (state.sortOrder === 'score') {
    result.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  } else if (state.sortOrder === 'up' || state.sortOrder === 'down') {
    // signed = positive? +score : negative? -score : 0
    const signed = (i) => {
      const s = Number(i.score) || 0;
      if (i.direction === 'positive') return s;
      if (i.direction === 'negative') return -s;
      return 0;
    };
    result.sort((a, b) => state.sortOrder === 'up' ? signed(b) - signed(a) : signed(a) - signed(b));
  } else {
    result.sort((a, b) => {
      const ta = a.time ? new Date(a.time).getTime() : 0;
      const tb = b.time ? new Date(b.time).getTime() : 0;
      return tb - ta;
    });
  }

  return result;
}

/* ===== バッジ生成ヘルパー ===== */

function createBadge(text, className) {
  const span = document.createElement('span');
  span.className = 'badge ' + className;
  span.textContent = text;
  return span;
}

/* ===== 方向バッジ生成(強い上昇/下落は「急騰期待/急落警戒」で強調) ===== */

const DIR_LABELS = { positive: '▲ 上昇', negative: '▼ 下落', neutral: '─ 中立', unknown: '? 不明' };

function isHotDirection(item) {
  const dirKey = item.direction || 'neutral';
  const score  = Number(item.score) || 0;
  return (dirKey === 'positive' || dirKey === 'negative') && score >= 80;
}

function createDirectionBadge(item) {
  const dirKey = item.direction || 'neutral';
  if (isHotDirection(item)) {
    const text = dirKey === 'positive' ? '▲▲ 急騰期待' : '▼▼ 急落警戒';
    return createBadge(text, `badge-direction-${dirKey} badge-direction-strong badge-direction-hot`);
  }
  return createBadge(DIR_LABELS[dirKey] ?? dirKey, `badge-direction-${dirKey} badge-direction-strong`);
}

/* ===== 行3用の小型アイコンリンク (PDF / チャート) ===== */

function createActionIconSvg(kind) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '14');
  svg.setAttribute('height', '14');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  if (kind === 'pdf') {
    const p1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p1.setAttribute('d', 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z');
    const p2 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    p2.setAttribute('points', '14 2 14 8 20 8');
    svg.appendChild(p1);
    svg.appendChild(p2);
  } else {
    const p1 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    p1.setAttribute('points', '23 6 13.5 15.5 8.5 10.5 1 18');
    const p2 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    p2.setAttribute('points', '17 6 23 6 23 12');
    svg.appendChild(p1);
    svg.appendChild(p2);
  }
  return svg;
}

/* ===== スコア数値 (impact 色の太字数値のみ・リング廃止) ===== */

function createScoreNumber(score, impact) {
  const safeScore = Math.max(0, Math.min(100, Number(score) || 0));
  const span = document.createElement('span');
  span.className = 'score-num';
  span.dataset.impact = impact || 'low';
  span.setAttribute('title', `スコア: ${safeScore}`);
  span.setAttribute('aria-label', `スコア ${safeScore}`);
  span.textContent = String(safeScore);
  return span;
}

/* ===== 決算サマリー ===== */

function createEarningsSummary(earnings) {
  const details = document.createElement('details');
  details.className = 'earnings-details';

  const summary = document.createElement('summary');
  summary.className = 'earnings-summary-toggle';
  summary.textContent = '📊 決算サマリー';
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'earnings-body';

  if (earnings.period) {
    body.appendChild(createTextEl('p', earnings.period, 'earnings-period'));
  }

  if (Array.isArray(earnings.figures) && earnings.figures.length > 0) {
    const table = document.createElement('table');
    table.className = 'earnings-table';

    const thead = document.createElement('thead');
    const hRow  = document.createElement('tr');
    ['項目', '値', '前期比'].forEach((h) => hRow.appendChild(createTextEl('th', h)));
    thead.appendChild(hRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    for (const fig of earnings.figures) {
      const tr = document.createElement('tr');
      tr.appendChild(createTextEl('td', fig.label ?? '', 'earnings-label'));
      tr.appendChild(createTextEl('td', fig.value ?? '', 'earnings-value'));

      const yoyTd  = document.createElement('td');
      yoyTd.className = 'earnings-yoy';
      const yoyStr = String(fig.yoy ?? '');
      if (yoyStr.startsWith('+')) yoyTd.classList.add('yoy-positive');
      else if (yoyStr.startsWith('-')) yoyTd.classList.add('yoy-negative');
      else yoyTd.classList.add('yoy-neutral');
      yoyTd.textContent = yoyStr;
      tr.appendChild(yoyTd);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    body.appendChild(table);
  }

  const addMetaRow = (label, value) => {
    if (!value) return;
    const row = document.createElement('p');
    row.className = 'earnings-meta-row';
    row.appendChild(createTextEl('span', label, 'earnings-meta-label'));
    row.appendChild(createTextEl('span', value, 'earnings-meta-value'));
    body.appendChild(row);
  };

  addMetaRow('配当: ',    earnings.dividend);
  addMetaRow('業績予想: ', earnings.forecast);

  if (earnings.comment) {
    body.appendChild(createTextEl('p', earnings.comment, 'earnings-comment'));
  }

  details.appendChild(body);
  return details;
}

/* ===== 詳細展開パネル ===== */

function createDetailPanel(item, pdfUrl, code4) {
  const panel = document.createElement('div');
  panel.className = 'card-detail-panel';
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-label', '開示詳細');

  // タイトル全文
  const titleFull = createTextEl('p', item.title ?? '', 'card-detail-title');
  panel.appendChild(titleFull);

  // 公開日時 + 市場情報(全文)
  {
    const metaParts = [];
    if (item.time) metaParts.push(`公開: ${formatUpdatedAt(item.time)}`);
    const exch = [item.exchange, item.markets].filter(Boolean).join(' ');
    if (exch) metaParts.push(exch);
    if (metaParts.length > 0) {
      panel.appendChild(createTextEl('p', metaParts.join(' ・ '), 'card-detail-date'));
    }
  }

  // 要約
  if (item.summary) {
    panel.appendChild(createTextEl('p', item.summary, 'card-detail-summary'));
  }

  // 重要度・緊急バッジ(一覧では出さず、ここ=展開時に表示)
  const metaRow = document.createElement('div');
  metaRow.className = 'card-detail-badges';
  if (item.urgent === true) {
    metaRow.appendChild(createBadge('⚡ 緊急', 'badge-urgent'));
  }
  if (item.is_correction === true) {
    metaRow.appendChild(createBadge('訂正/続報', 'badge-correction'));
  }
  const impLabels = { high: '高', medium: '中', low: '低' };
  const impKey = item.impact || 'low';
  metaRow.appendChild(createBadge(`重要度: ${impLabels[impKey] ?? impKey}`, `badge-impact-${impKey}`));
  metaRow.appendChild(createDirectionBadge(item));
  if (typeof item.confidence === 'number') {
    metaRow.appendChild(createBadge(`確度 ${item.confidence}%`, 'badge-tag'));
  }
  panel.appendChild(metaRow);

  // 決算サマリー(全文)
  if (item.earnings && typeof item.earnings === 'object') {
    panel.appendChild(createEarningsSummary(item.earnings));
  }

  // 全 reasons
  if (Array.isArray(item.reasons) && item.reasons.length > 0) {
    const reasonsWrap = document.createElement('div');
    reasonsWrap.className = 'card-detail-section';
    reasonsWrap.appendChild(createTextEl('p', '評価理由', 'card-detail-section-label'));
    const ul = document.createElement('ul');
    ul.className = 'card-detail-reasons';
    for (const r of item.reasons) {
      ul.appendChild(createTextEl('li', String(r), 'card-detail-reason-item'));
    }
    reasonsWrap.appendChild(ul);
    panel.appendChild(reasonsWrap);
  }

  // 全 tags
  if (Array.isArray(item.tags) && item.tags.length > 0) {
    const tagsWrap = document.createElement('div');
    tagsWrap.className = 'card-detail-section';
    tagsWrap.appendChild(createTextEl('p', 'タグ', 'card-detail-section-label'));
    const tagsRow = document.createElement('div');
    tagsRow.className = 'card-detail-tags';
    for (const t of item.tags) {
      if (t) tagsRow.appendChild(createBadge(String(t), 'badge-tag'));
    }
    tagsWrap.appendChild(tagsRow);
    panel.appendChild(tagsWrap);
  }

  // リンク行 (chart + pdf)
  const linksRow = document.createElement('div');
  linksRow.className = 'card-detail-links';

  if (code4) {
    const chartLink = document.createElement('a');
    chartLink.className = 'detail-link detail-link--chart';
    chartLink.href    = `https://kabutan.jp/stock/?code=${encodeURIComponent(code4)}`;
    chartLink.target  = '_blank';
    chartLink.rel     = 'noopener noreferrer';
    chartLink.setAttribute('aria-label', `${item.company ?? code4} の株探チャートを開く`);
    chartLink.addEventListener('click', (e) => e.stopPropagation());
    chartLink.textContent = '📈 チャート';
    linksRow.appendChild(chartLink);
  }

  if (pdfUrl) {
    const pdfLink = document.createElement('a');
    pdfLink.className = 'detail-link detail-link--pdf';
    pdfLink.href    = pdfUrl;
    pdfLink.target  = '_blank';
    pdfLink.rel     = 'noopener noreferrer';
    pdfLink.setAttribute('aria-label', 'PDFを開く');
    pdfLink.addEventListener('click', (e) => e.stopPropagation());
    pdfLink.textContent = '📄 PDF';
    linksRow.appendChild(pdfLink);
  }

  // 共有ボタン
  const shareBtn = document.createElement('button');
  shareBtn.type = 'button';
  shareBtn.className = 'detail-link detail-link--share';
  shareBtn.setAttribute('aria-label', 'この開示を共有する');
  shareBtn.textContent = '🔗 共有';
  shareBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    // 共有/コピーするURLは情報の大元(TDnetの開示PDF)。無ければアプリURL。
    const sourceUrl = safePdfUrl(item.pdf_url) || window.location.href;
    const shareData = {
      title: `${item.company ?? ''} — ${item.title ?? ''}`,
      text:  `${item.company ?? ''} (${item.code ?? ''}) の適時開示: ${item.title ?? ''}`,
      url:   sourceUrl,
    };
    if (navigator.share) {
      try { await navigator.share(shareData); } catch { /* cancelled */ }
    } else {
      try {
        await navigator.clipboard.writeText(`${shareData.title}\n${sourceUrl}`);
        showToast('リンクをコピーしました');
      } catch {
        showToast('コピーできませんでした');
      }
    }
  });
  linksRow.appendChild(shareBtn);

  if (linksRow.children.length > 0) panel.appendChild(linksRow);

  return panel;
}

/* ===== カード生成 ===== */

function createCard(item, index) {
  const card = document.createElement('article');
  card.className = 'card';
  card.dataset.impact = item.impact || 'low';
  card.dataset.direction = item.direction || 'neutral';
  card.dataset.strong = isHotDirection(item) ? '1' : '0';
  // スタガーアニメーション用インデックス
  card.style.setProperty('--card-index', String(Math.min(index, 19)));

  const code = String(item.code ?? '');
  const code4 = normalizeCode4(code);
  if (code && state.watchlist.has(code)) {
    card.classList.add('is-watchlisted');
  }

  // カード展開状態
  let isExpanded = false;

  const { hhmm, date, ts } = parseTime(item.time);

  /* --- 行1: 時刻 + コード + 会社名 + NEW + ⚡ + スコア + ★ --- */
  const row1 = document.createElement('div');
  row1.className = 'card-row1';

  const hhmmSpan = createTextEl('span', hhmm, 'row1-time');
  hhmmSpan.setAttribute('title', formatUpdatedAt(item.time));
  row1.appendChild(hhmmSpan);

  // 過去日付(アーカイブ)表示時のみ M/D を行1に出す。ライブ当日表示では省略(詳細パネルに全文表示)。
  if (state.selectedDate && date) {
    row1.appendChild(createTextEl('span', date, 'row1-date'));
  }

  row1.appendChild(createTextEl('span', code, 'row1-code'));

  // 会社名ボタン(銘柄絞り込みトリガー) — 1行省略
  const nameBtn = document.createElement('button');
  nameBtn.className = 'row1-company';
  nameBtn.type = 'button';
  nameBtn.setAttribute('aria-label', `${item.company ?? ''} のみ表示`);
  const nameSpan = createTextEl('span', item.company ?? '（不明）', 'row1-company-text');
  nameSpan.title = item.company ?? '';
  nameBtn.appendChild(nameSpan);
  nameBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (code) onStockFilter(code, item.company ?? code);
  });
  row1.appendChild(nameBtn);

  // 新着バッジ
  if (ts && ts > state.lastSeenTs && state.lastSeenTs > 0) {
    const newBadge = createTextEl('span', 'NEW', 'new-badge');
    newBadge.setAttribute('aria-label', '新着');
    row1.appendChild(newBadge);
  }

  // 緊急フラグ(⚡)
  if (item.urgent === true) {
    const flag = createTextEl('span', '⚡', 'urgent-flag');
    flag.setAttribute('aria-label', '緊急');
    flag.setAttribute('title', '緊急開示');
    row1.appendChild(flag);
  }

  // スコア数値(impact 色の太字数値)
  row1.appendChild(createScoreNumber(item.score, item.impact));

  // ★ ウォッチリストトグル
  const btnStar = document.createElement('button');
  btnStar.type = 'button';
  btnStar.className = 'row1-star' + (code && state.watchlist.has(code) ? ' starred' : '');
  btnStar.setAttribute('aria-label', `${item.company ?? code} をウォッチリストに追加`);
  btnStar.setAttribute('aria-pressed', String(code && state.watchlist.has(code)));
  const starSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  starSvg.setAttribute('width', '16');
  starSvg.setAttribute('height', '16');
  starSvg.setAttribute('viewBox', '0 0 24 24');
  starSvg.setAttribute('fill', 'none');
  starSvg.setAttribute('stroke', 'currentColor');
  starSvg.setAttribute('stroke-width', '2');
  starSvg.setAttribute('stroke-linecap', 'round');
  starSvg.setAttribute('stroke-linejoin', 'round');
  starSvg.setAttribute('aria-hidden', 'true');
  const starPoly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  starPoly.setAttribute('points', '12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2');
  starSvg.appendChild(starPoly);
  btnStar.appendChild(starSvg);
  btnStar.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleWatchlist(code);
    const starred = state.watchlist.has(code);
    btnStar.classList.toggle('starred', starred);
    btnStar.setAttribute('aria-pressed', String(starred));
    if (starred) {
      starSvg.setAttribute('fill', 'currentColor');
      card.classList.add('is-watchlisted');
    } else {
      starSvg.setAttribute('fill', 'none');
      card.classList.remove('is-watchlisted');
    }
    if (state.filterWatchlist) renderCards();
  });
  if (code && state.watchlist.has(code)) {
    starSvg.setAttribute('fill', 'currentColor');
  }
  row1.appendChild(btnStar);

  card.appendChild(row1);

  /* --- 行2: タイトル(1行省略) --- */
  const row2 = createTextEl('p', item.title ?? '（タイトルなし）', 'card-row2');
  row2.title = item.title ?? '';
  card.appendChild(row2);

  /* --- 行3: 方向バッジ + カテゴリ + タグ(最大2) + 相対時刻 + PDF/チャートアイコン --- */
  const row3 = document.createElement('div');
  row3.className = 'card-row3';

  row3.appendChild(createDirectionBadge(item));

  if (item.category) {
    row3.appendChild(createBadge(item.category, 'badge-category'));
  }

  if (item.earnings && typeof item.earnings === 'object') {
    row3.appendChild(createBadge('📊 決算', 'badge-earnings'));
  }

  if (Array.isArray(item.tags) && item.tags.length > 0) {
    for (const tag of item.tags.slice(0, 2)) {
      if (tag) row3.appendChild(createBadge(String(tag), 'badge-tag'));
    }
  }

  const relSpan = createTextEl('span', relativeTime(ts), 'row3-rel time-rel');
  relSpan.setAttribute('data-ts', String(ts));
  relSpan.setAttribute('title', formatUpdatedAt(item.time));
  row3.appendChild(relSpan);

  // 右端: PDF / チャートの小アイコンリンク(タップ領域32px)
  const actions = document.createElement('div');
  actions.className = 'row3-actions';

  const pdfUrl = safePdfUrl(item.pdf_url);
  if (pdfUrl) {
    const pdfA = document.createElement('a');
    pdfA.className = 'action-icon action-icon--pdf';
    pdfA.href    = pdfUrl;
    pdfA.target  = '_blank';
    pdfA.rel     = 'noopener noreferrer';
    pdfA.setAttribute('aria-label', 'PDFを開く');
    pdfA.title = 'PDF';
    pdfA.appendChild(createActionIconSvg('pdf'));
    pdfA.addEventListener('click', (e) => e.stopPropagation());
    actions.appendChild(pdfA);
  }

  if (code4) {
    const chartA = document.createElement('a');
    chartA.className = 'action-icon action-icon--chart';
    chartA.href    = `https://kabutan.jp/stock/?code=${encodeURIComponent(code4)}`;
    chartA.target  = '_blank';
    chartA.rel     = 'noopener noreferrer';
    chartA.setAttribute('aria-label', `${item.company ?? code4} の株探チャート`);
    chartA.title = 'チャート';
    chartA.appendChild(createActionIconSvg('chart'));
    chartA.addEventListener('click', (e) => e.stopPropagation());
    actions.appendChild(chartA);
  }

  if (actions.children.length > 0) row3.appendChild(actions);

  card.appendChild(row3);

  /* --- 詳細展開パネル(全情報) --- */
  const detailPanel = createDetailPanel(item, pdfUrl, code4);
  detailPanel.hidden = true;
  card.appendChild(detailPanel);

  /* --- カードクリックで展開/折りたたみ --- */
  card.setAttribute('aria-expanded', 'false');
  card.style.cursor = 'pointer';
  card.addEventListener('click', (e) => {
    // ボタン/リンク/select/input のクリックは伝播させない
    if (e.target.closest('button, a, select, input, details, summary, label')) return;
    isExpanded = !isExpanded;
    card.setAttribute('aria-expanded', String(isExpanded));
    detailPanel.hidden = !isExpanded;
    card.classList.toggle('card--expanded', isExpanded);
  });

  return card;
}

/* ===== スケルトンローディング ===== */

function createSkeletonCard() {
  const card = document.createElement('div');
  card.className = 'skeleton-card';

  const row = document.createElement('div');
  row.className = 'skel-row';
  const col = document.createElement('div');
  col.className = 'skel-col';
  col.appendChild(Object.assign(document.createElement('div'), { className: 'skel skel-line skel-line--short' }));
  col.appendChild(Object.assign(document.createElement('div'), { className: 'skel skel-line skel-line--mid' }));
  row.appendChild(col);
  row.appendChild(Object.assign(document.createElement('div'), { className: 'skel skel-block' }));
  card.appendChild(row);

  card.appendChild(Object.assign(document.createElement('div'), { className: 'skel skel-line skel-line--full' }));
  card.appendChild(Object.assign(document.createElement('div'), { className: 'skel skel-line skel-line--long' }));
  card.appendChild(Object.assign(document.createElement('div'), { className: 'skel skel-line skel-line--mid' }));
  return card;
}

function showSkeleton(n = 4) {
  const list = el.cardList;
  while (list.firstChild) list.removeChild(list.firstChild);
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) frag.appendChild(createSkeletonCard());
  list.appendChild(frag);
}

/* ===== 空状態 ===== */

function showEmptyState(title, sub, isError = false) {
  const list = el.cardList;
  while (list.firstChild) list.removeChild(list.firstChild);

  const empty = document.createElement('div');
  empty.className = 'empty-state';
  empty.setAttribute('role', 'alert');

  const iconWrap = document.createElement('div');
  iconWrap.className = 'empty-icon';
  iconWrap.setAttribute('aria-hidden', 'true');

  const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  iconSvg.setAttribute('width', '24');
  iconSvg.setAttribute('height', '24');
  iconSvg.setAttribute('viewBox', '0 0 24 24');
  iconSvg.setAttribute('fill', 'none');
  iconSvg.setAttribute('stroke', 'currentColor');
  iconSvg.setAttribute('stroke-width', '1.5');
  iconSvg.setAttribute('stroke-linecap', 'round');
  iconSvg.setAttribute('stroke-linejoin', 'round');

  if (isError) {
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', '12'); circle.setAttribute('cy', '12'); circle.setAttribute('r', '10');
    const line1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line1.setAttribute('x1', '12'); line1.setAttribute('y1', '8'); line1.setAttribute('x2', '12'); line1.setAttribute('y2', '12');
    const line2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line2.setAttribute('x1', '12'); line2.setAttribute('y1', '16'); line2.setAttribute('x2', '12.01'); line2.setAttribute('y2', '16');
    iconSvg.appendChild(circle); iconSvg.appendChild(line1); iconSvg.appendChild(line2);
  } else {
    const inbox = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    inbox.setAttribute('points', '22 12 16 12 14 15 10 15 8 12 2 12');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z');
    iconSvg.appendChild(inbox); iconSvg.appendChild(path);
  }

  iconWrap.appendChild(iconSvg);
  empty.appendChild(iconWrap);
  empty.appendChild(createTextEl('p', title, 'empty-title'));
  if (sub) empty.appendChild(createTextEl('p', sub, 'empty-sub'));
  list.appendChild(empty);
}

/* ===== UI 更新 ===== */

function renderCards() {
  const filtered = applyFilters();
  el.resultCount.textContent = `${filtered.length} 件表示`;

  if (state.loading && state.items.length === 0) {
    showSkeleton(4);
    return;
  }

  if (filtered.length === 0) {
    if (state.items.length === 0) {
      showEmptyState('データがありません', 'しばらく待ってからページを更新してください。');
    } else {
      showEmptyState('条件に一致する開示がありません', 'フィルタを変更してお試しください。');
    }
    return;
  }

  const list = el.cardList;
  while (list.firstChild) list.removeChild(list.firstChild);
  const frag = document.createDocumentFragment();
  filtered.forEach((item, i) => frag.appendChild(createCard(item, i)));
  list.appendChild(frag);
}

function renderHeader() {
  el.updatedAt.textContent = state.updatedAt ? formatUpdatedAt(state.updatedAt) : '—';
}

function updateSummaryStrip() {
  renderSummary(state.items);
}

function setStatus(msg, type) {
  el.statusMsg.textContent = msg;
  el.statusMsg.className   = 'status-msg' + (type ? ' ' + type : '');
}

/* ===== 銘柄絞り込み ===== */

function onStockFilter(code, name) {
  if (state.filterStockCode === code) {
    clearStockFilter();
    return;
  }
  state.filterStockCode = code;
  const bar = document.getElementById('stock-filter-bar');
  if (bar) bar.hidden = false;
  const nameEl = document.getElementById('stock-filter-name');
  if (nameEl) nameEl.textContent = `${name} (${code})`;
  showToast(`${name} (${code}) で絞り込み中`);
  renderCards();
}

function clearStockFilter() {
  state.filterStockCode = null;
  const bar = document.getElementById('stock-filter-bar');
  if (bar) bar.hidden = true;
  showToast('銘柄フィルタを解除しました');
  renderCards();
}

/* ===== データ取得 ===== */

async function fetchData({ silent = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  el.refreshBtn.disabled = true;

  if (!silent) {
    const spin = document.createElement('span');
    spin.className = 'spinner';
    spin.id = 'refresh-spinner';
    el.refreshBtn.prepend(spin);
    if (state.items.length === 0) showSkeleton(4);
    setStatus('取得中…', 'loading');
  }

  const url = state.selectedDate
    ? `${ARCHIVE_BASE_URL}${state.selectedDate}.json?t=${Date.now()}`
    : `${DATA_URL}?t=${Date.now()}`;

  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    const json = await resp.json();

    const prevIds = new Set(state.items.map((i) => String(i.id ?? '')));
    state.items      = Array.isArray(json.items) ? json.items : [];
    state.updatedAt  = typeof json.updated_at === 'string' ? json.updated_at : null;
    state.totalCount = typeof json.count === 'number' ? json.count : state.items.length;
    state.error      = null;

    if (silent) {
      const newItems = state.items.filter((i) => !prevIds.has(String(i.id ?? '')));
      checkNewUrgent(newItems);
    }

    buildCategoryOptions();
    restoreCategoryFilter();
    renderHeader();
    updateSummaryStrip();
    renderCards();
    setStatus('', '');
  } catch (err) {
    state.error = err.message;
    if (state.items.length === 0) {
      showEmptyState(
        'データの取得に失敗しました',
        `エラー: ${err.message}`,
        true
      );
      el.resultCount.textContent = '0 件表示';
    }
    setStatus(`取得エラー: ${err.message}`, 'error');
    console.error('[開示レーダー] fetch error:', err);
  } finally {
    state.loading = false;
    el.refreshBtn.disabled = false;
    const spin = document.getElementById('refresh-spinner');
    if (spin) spin.remove();
  }
}

/* ===== 日付セレクタ構築 ===== */

async function buildDateSelector() {
  try {
    const resp = await fetch(`${ARCHIVE_INDEX_URL}?t=${Date.now()}`);
    if (!resp.ok) return;
    const json = await resp.json();
    if (!Array.isArray(json.dates) || json.dates.length === 0) return;

    const sel    = el.dateSelector;
    const sorted = [...json.dates].sort((a, b) => String(b.date).localeCompare(String(a.date)));

    for (const entry of sorted) {
      if (!entry.date) continue;
      const opt = document.createElement('option');
      opt.value    = String(entry.date);
      const cnt    = typeof entry.count === 'number' ? ` (${entry.count}件)` : '';
      opt.textContent = `${entry.date}${cnt}`;
      sel.appendChild(opt);
    }
  } catch (err) {
    console.warn('[開示レーダー] archive/index.json 取得失敗:', err);
  }
}

/* ===== イベントハンドラ ===== */

function onDateSelectorChange() {
  const value = el.dateSelector.value;
  if (value === 'live') {
    state.selectedDate = null;
    startAutoRefresh();
  } else {
    state.selectedDate = value;
    stopAutoRefresh();
  }
  state.filterCategory = 'all';
  el.categorySelect.value = 'all';
  fetchData();
}

function onImpactToggle(e) {
  const btn    = e.currentTarget;
  const impact = btn.dataset.impact;
  state.filterImpact = (state.filterImpact === impact) ? 'all' : impact;
  el.impactBtns.forEach((b) => {
    b.classList.toggle('active', b.dataset.impact === state.filterImpact);
    b.setAttribute('aria-pressed', String(b.dataset.impact === state.filterImpact));
  });
  saveFilters();
  renderCards();
}

function onCategoryChange() {
  state.filterCategory = el.categorySelect.value;
  saveFilters();
  renderCards();
}

function onUrgentToggle() {
  state.filterUrgent = el.urgentCheck.checked;
  saveFilters();
  renderCards();
}

function onSearchInput() {
  state.filterKeyword = el.searchInput.value;
  renderCards();
}

function onSortChange(e) {
  const btn = e.currentTarget;
  state.sortOrder = btn.dataset.sort;
  el.sortBtns.forEach((b) => {
    b.classList.toggle('active', b.dataset.sort === state.sortOrder);
    b.setAttribute('aria-pressed', String(b.dataset.sort === state.sortOrder));
  });
  saveFilters();
  renderCards();
}

function onWatchlistToggle() {
  state.filterWatchlist = !state.filterWatchlist;
  el.btnWatchlist.classList.toggle('active', state.filterWatchlist);
  el.btnWatchlist.setAttribute('aria-pressed', String(state.filterWatchlist));
  saveFilters();
  renderCards();
}

function onNewOnlyToggle() {
  state.filterNewOnly = !state.filterNewOnly;
  if (el.btnNewOnly) {
    el.btnNewOnly.classList.toggle('active', state.filterNewOnly);
    el.btnNewOnly.setAttribute('aria-pressed', String(state.filterNewOnly));
  }
  renderCards();
}

function onScrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function onWindowScroll() {
  el.scrollTopBtn.classList.toggle('visible', window.scrollY > 300);
}

/* ===== サマリーストリップ クリックハンドラ ===== */

function onStatHighClick() {
  // 高インパクトフィルタをトグル
  state.filterImpact = state.filterImpact === 'high' ? 'all' : 'high';
  el.impactBtns.forEach((b) => {
    b.classList.toggle('active', b.dataset.impact === state.filterImpact);
    b.setAttribute('aria-pressed', String(b.dataset.impact === state.filterImpact));
  });
  saveFilters();
  updateSummaryActiveStates();
  renderCards();
}

function onStatUrgentClick() {
  state.filterUrgent = !state.filterUrgent;
  if (el.urgentCheck) el.urgentCheck.checked = state.filterUrgent;
  saveFilters();
  updateSummaryActiveStates();
  renderCards();
}

function onStatCategoryClick() {
  const catEl = document.getElementById('stat-category');
  if (!catEl) return;
  const topCat = catEl.textContent;
  if (!topCat || topCat === '—') return;
  if (state.filterCategory === topCat) {
    state.filterCategory = 'all';
    if (el.categorySelect) el.categorySelect.value = 'all';
  } else {
    state.filterCategory = topCat;
    if (el.categorySelect) el.categorySelect.value = topCat;
  }
  saveFilters();
  updateSummaryActiveStates();
  renderCards();
}

/* ===== キーボードショートカット ===== */

function onKeyDown(e) {
  // ESC でヘルプ/モーダル以外の処理
  if (e.key === 'Escape' && document.activeElement === el.searchInput) {
    el.searchInput.value = '';
    state.filterKeyword = '';
    renderCards();
    return;
  }
  // '/' キーで検索フォーカス
  if (e.key === '/' && document.activeElement !== el.searchInput) {
    e.preventDefault();
    el.searchInput.focus();
    el.searchInput.select();
  }
}

/* ===== Service Worker 登録 ===== */

function registerSW() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('./sw.js').then((reg) => {
    console.log('[開示レーダー] SW registered:', reg.scope);
  }).catch((err) => {
    // SW 未対応 or 失敗でも本体は動作
    console.warn('[開示レーダー] SW registration failed:', err);
  });
}

/* ===== 初期化 ===== */

function initDOM() {
  el.updatedAt      = document.getElementById('updated-at');
  el.refreshBtn     = document.getElementById('btn-refresh');
  el.impactBtns     = document.querySelectorAll('[data-impact]');
  el.categorySelect = document.getElementById('filter-category');
  el.urgentCheck    = document.getElementById('filter-urgent');
  el.searchInput    = document.getElementById('search-input');
  el.sortBtns       = document.querySelectorAll('[data-sort]');
  el.cardList       = document.getElementById('card-list');
  el.resultCount    = document.getElementById('result-count');
  el.statusMsg      = document.getElementById('status-msg');
  el.scrollTopBtn   = document.getElementById('scroll-top-btn');
  el.dateSelector   = document.getElementById('date-selector');
  el.liveIndicator  = document.getElementById('live-indicator');
  el.btnTheme       = document.getElementById('btn-theme');
  el.btnWatchlist   = document.getElementById('btn-watchlist');
  el.btnNotify      = document.getElementById('btn-notify');
  el.btnHelp        = document.getElementById('btn-help');
  el.btnNewOnly     = document.getElementById('btn-new-only');
}

function initEvents() {
  el.refreshBtn.addEventListener('click', () => fetchData());
  el.impactBtns.forEach((btn) => {
    if (btn.dataset.impact) btn.addEventListener('click', onImpactToggle);
  });
  el.categorySelect.addEventListener('change', onCategoryChange);
  el.urgentCheck.addEventListener('change', onUrgentToggle);
  el.searchInput.addEventListener('input', onSearchInput);
  el.sortBtns.forEach((btn) => btn.addEventListener('click', onSortChange));
  el.scrollTopBtn.addEventListener('click', onScrollTop);
  window.addEventListener('scroll', onWindowScroll, { passive: true });
  el.dateSelector.addEventListener('change', onDateSelectorChange);
  el.btnTheme.addEventListener('click', toggleTheme);
  if (el.btnWatchlist) el.btnWatchlist.addEventListener('click', onWatchlistToggle);
  if (el.btnNotify)    el.btnNotify.addEventListener('click', toggleNotify);
  if (el.btnHelp)      el.btnHelp.addEventListener('click', openHelp);
  if (el.btnNewOnly)   el.btnNewOnly.addEventListener('click', onNewOnlyToggle);
  document.addEventListener('keydown', onKeyDown);

  const stockClearBtn = document.getElementById('stock-filter-clear');
  if (stockClearBtn) stockClearBtn.addEventListener('click', () => clearStockFilter());

  // サマリーストリップのクリック
  const statBtnHigh     = document.getElementById('stat-btn-high');
  const statBtnUrgent   = document.getElementById('stat-btn-urgent');
  const statBtnCategory = document.getElementById('stat-btn-category');
  if (statBtnHigh)     statBtnHigh.addEventListener('click',     onStatHighClick);
  if (statBtnUrgent)   statBtnUrgent.addEventListener('click',   onStatUrgentClick);
  if (statBtnCategory) statBtnCategory.addEventListener('click', onStatCategoryClick);
}

async function init() {
  // テーマを先に適用（FOUC防止）
  initTheme();

  initDOM();

  // フィルタ永続化読み込み
  loadFilters();

  initEvents();

  // 永続データ読み込み
  loadWatchlist();
  loadLastSeen();
  loadNotifyPref();

  // フィルタUI同期(永続化から復元した状態を反映)
  syncFilterUI();

  // アーカイブセレクタ構築
  await buildDateSelector();

  // ライブモードで自動更新開始
  if (state.selectedDate === null) {
    startAutoRefresh();
  }

  // 初回フェッチ
  await fetchData();

  // 初回表示完了後に lastSeen を更新
  saveLastSeen();

  // Service Worker 登録
  registerSW();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
