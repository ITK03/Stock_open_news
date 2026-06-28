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

/* ===== localStorage キー (名前衝突回避) ===== */
const LS_THEME     = 'kaiji.theme';
const LS_WATCHLIST = 'kaiji.watchlist';
const LS_LAST_SEEN = 'kaiji.lastSeen';
const LS_NOTIFY    = 'kaiji.notify';

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
  filterStockCode: null, // 銘柄絞り込み
  sortOrder:       'time',

  loading:      false,
  error:        null,
  selectedDate: null, // null = ライブ

  // 新着チェック用（前回訪問時刻）
  lastSeenTs:   0,

  // ウォッチリスト: Set<code string>
  watchlist:    new Set(),

  // 通知許可状態
  notifyEnabled: false,

  // 前回の urgent アイテム ID set (通知の重複防止)
  notifiedIds: new Set(),
};

/* ===== 自動更新タイマー ===== */
let autoRefreshTimer = null;

function startAutoRefresh() {
  stopAutoRefresh();
  autoRefreshTimer = setInterval(() => fetchData({ silent: true }), AUTO_REFRESH_MS);
  updateLiveIndicator(true);
}

function stopAutoRefresh() {
  if (autoRefreshTimer !== null) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
  updateLiveIndicator(false);
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

/**
 * 相対時刻を返す
 * @param {number} ts — epoch ms
 * @returns {string}
 */
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

function createTextEl(tag, text, className) {
  const elem = document.createElement(tag);
  if (className) elem.className = className;
  elem.textContent = String(text ?? '');
  return elem;
}

/* ===== テーマ管理 ===== */

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  // PWA theme-color
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
    // prefers-color-scheme の初期値
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
      if (Array.isArray(arr)) {
        state.watchlist = new Set(arr);
        return;
      }
    }
  } catch { /* ok */ }
  state.watchlist = new Set();
}

function saveWatchlist() {
  try {
    localStorage.setItem(LS_WATCHLIST, JSON.stringify([...state.watchlist]));
  } catch { /* ok */ }
}

function toggleWatchlist(code) {
  if (!code) return;
  if (state.watchlist.has(code)) {
    state.watchlist.delete(code);
  } else {
    state.watchlist.add(code);
  }
  saveWatchlist();
}

/* ===== 前回訪問時刻 ===== */

function loadLastSeen() {
  try {
    const raw = localStorage.getItem(LS_LAST_SEEN);
    state.lastSeenTs = raw ? parseInt(raw, 10) : 0;
  } catch {
    state.lastSeenTs = 0;
  }
}

function saveLastSeen() {
  try {
    localStorage.setItem(LS_LAST_SEEN, String(Date.now()));
  } catch { /* ok */ }
}

/* ===== ブラウザ通知 ===== */

function loadNotifyPref() {
  try {
    const raw = localStorage.getItem(LS_NOTIFY);
    state.notifyEnabled = raw === '1' && Notification.permission === 'granted';
  } catch {
    state.notifyEnabled = false;
  }
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
    // 無効化
    state.notifyEnabled = false;
    try { localStorage.setItem(LS_NOTIFY, '0'); } catch { /* ok */ }
    updateNotifyBtn();
    return;
  }

  // 有効化リクエスト
  if (Notification.permission === 'granted') {
    state.notifyEnabled = true;
    try { localStorage.setItem(LS_NOTIFY, '1'); } catch { /* ok */ }
    updateNotifyBtn();
    return;
  }

  if (Notification.permission === 'denied') {
    // 拒否済み — 静かに何もしない
    return;
  }

  // default → 要求
  const perm = await Notification.requestPermission().catch(() => 'denied');
  if (perm === 'granted') {
    state.notifyEnabled = true;
    try { localStorage.setItem(LS_NOTIFY, '1'); } catch { /* ok */ }
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

  // 上位カテゴリ
  const catCount = {};
  for (const item of items) {
    if (item.category) catCount[item.category] = (catCount[item.category] || 0) + 1;
  }
  const topCat = Object.entries(catCount).sort((a, b) => b[1] - a[1])[0];

  const setText = (id, text) => {
    const el2 = document.getElementById(id);
    if (el2) el2.textContent = text;
  };

  setText('stat-total',    total);
  setText('stat-high',     high);
  setText('stat-urgent',   urgent);
  setText('stat-category', topCat ? topCat[0] : '—');
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

/* ===== スコアリング SVG サークル ===== */

function createScoreRing(score, impact) {
  const safeScore = Math.max(0, Math.min(100, Number(score) || 0));
  const r    = 18;
  const circ = 2 * Math.PI * r;
  const offset = circ - (safeScore / 100) * circ;

  const wrapper = document.createElement('div');
  wrapper.className = 'score-ring';
  wrapper.dataset.impact = impact || 'low';
  wrapper.setAttribute('title', `スコア: ${safeScore}`);
  wrapper.setAttribute('aria-label', `スコア ${safeScore}`);

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '44');
  svg.setAttribute('height', '44');
  svg.setAttribute('viewBox', '0 0 44 44');
  svg.setAttribute('aria-hidden', 'true');

  const track = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  track.setAttribute('class', 'score-track');
  track.setAttribute('cx', '22');
  track.setAttribute('cy', '22');
  track.setAttribute('r', String(r));
  track.setAttribute('stroke-width', '3');

  const fill = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  fill.setAttribute('class', 'score-fill');
  fill.setAttribute('cx', '22');
  fill.setAttribute('cy', '22');
  fill.setAttribute('r', String(r));
  fill.setAttribute('stroke-width', '3');
  fill.setAttribute('stroke-dasharray', String(circ));
  fill.setAttribute('stroke-dashoffset', String(offset));

  svg.appendChild(track);
  svg.appendChild(fill);

  const scoreText = document.createElement('span');
  scoreText.className = 'score-value';
  scoreText.textContent = String(safeScore);

  wrapper.appendChild(svg);
  wrapper.appendChild(scoreText);
  return wrapper;
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
    const row   = document.createElement('p');
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

/* ===== カード生成 ===== */

function createCard(item) {
  const card = document.createElement('article');
  card.className = 'card';
  card.dataset.impact = item.impact || 'low';

  const code = String(item.code ?? '');
  if (code && state.watchlist.has(code)) {
    card.classList.add('is-watchlisted');
  }

  /* --- カードトップ --- */
  const cardTop = document.createElement('div');
  cardTop.className = 'card-top';

  // 時刻
  const { hhmm, date, ts } = parseTime(item.time);
  const timeDiv = document.createElement('div');
  timeDiv.className = 'card-time';
  const hhmmSpan = document.createElement('span');
  hhmmSpan.className = 'time-hhmm';
  hhmmSpan.textContent = hhmm;
  const dateSpan = document.createElement('span');
  dateSpan.className = 'time-date';
  dateSpan.textContent = date;
  const relSpan = document.createElement('span');
  relSpan.className = 'time-rel';
  relSpan.textContent = relativeTime(ts);
  relSpan.setAttribute('title', formatUpdatedAt(item.time));
  timeDiv.appendChild(hhmmSpan);
  timeDiv.appendChild(dateSpan);
  timeDiv.appendChild(relSpan);

  // 会社情報
  const companyDiv = document.createElement('div');
  companyDiv.className = 'card-company';

  const codeLineDiv = document.createElement('div');
  codeLineDiv.className = 'company-code-line';
  const codeSpan = createTextEl('span', code, 'company-code');
  codeLineDiv.appendChild(codeSpan);

  if (item.exchange || item.markets) {
    const exchSpan = createTextEl('span',
      [item.exchange, item.markets].filter(Boolean).join(' '),
      'company-exchange'
    );
    codeLineDiv.appendChild(exchSpan);
  }
  companyDiv.appendChild(codeLineDiv);

  // 会社名ボタン(銘柄絞り込みトリガー)
  const nameBtn = document.createElement('button');
  nameBtn.className = 'company-name-btn';
  nameBtn.type = 'button';
  nameBtn.setAttribute('aria-label', `${item.company ?? ''} のみ表示`);

  const nameSpan = createTextEl('span', item.company ?? '（不明）', 'company-name');
  nameSpan.title = item.company ?? '';
  nameBtn.appendChild(nameSpan);
  nameBtn.addEventListener('click', () => {
    if (code) onStockFilter(code, item.company ?? code);
  });
  companyDiv.appendChild(nameBtn);

  // 右クラスター（★ + スコアリング）
  const topRight = document.createElement('div');
  topRight.className = 'card-top-right';

  // ★ ウォッチリストトグル
  const btnStar = document.createElement('button');
  btnStar.type = 'button';
  btnStar.className = 'btn-star' + (code && state.watchlist.has(code) ? ' starred' : '');
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
    // カードとボタンのスター状態を更新
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
    // お気に入りフィルタ中は再描画
    if (state.filterWatchlist) renderCards();
  });
  if (code && state.watchlist.has(code)) {
    starSvg.setAttribute('fill', 'currentColor');
  }

  // スコアリング
  const scoreRing = createScoreRing(item.score, item.impact);

  topRight.appendChild(btnStar);
  topRight.appendChild(scoreRing);

  // 確信度
  if (typeof item.confidence === 'number') {
    const confEl = createTextEl('span', `確度 ${item.confidence}%`, 'confidence-label');
    topRight.appendChild(confEl);
  }

  cardTop.appendChild(timeDiv);
  cardTop.appendChild(companyDiv);
  cardTop.appendChild(topRight);
  card.appendChild(cardTop);

  /* --- タイトル --- */
  const titleLine = document.createElement('p');
  titleLine.className = 'card-title';
  titleLine.textContent = item.title ?? '（タイトルなし）';

  // 新着バッジ
  if (ts && ts > state.lastSeenTs && state.lastSeenTs > 0) {
    const newBadge = document.createElement('span');
    newBadge.className = 'new-badge';
    newBadge.textContent = 'NEW';
    newBadge.setAttribute('aria-label', '新着');
    titleLine.appendChild(newBadge);
  }

  card.appendChild(titleLine);

  /* --- 要約 --- */
  if (item.summary) {
    card.appendChild(createTextEl('p', item.summary, 'card-summary'));
  }

  /* --- バッジ群 --- */
  const badgesDiv = document.createElement('div');
  badgesDiv.className = 'card-badges';

  // urgent
  if (item.urgent === true) {
    badgesDiv.appendChild(createBadge('⚡ 緊急', 'badge-urgent'));
  }

  // is_correction (任意)
  if (item.is_correction === true) {
    badgesDiv.appendChild(createBadge('訂正/続報', 'badge-correction'));
  }

  // impact
  const impactLabels = { high: '高', medium: '中', low: '低' };
  const impactKey = item.impact || 'low';
  badgesDiv.appendChild(createBadge(
    `重要度: ${impactLabels[impactKey] ?? impactKey}`,
    `badge-impact-${impactKey}`
  ));

  // direction
  const dirLabels = { positive: '▲ 上昇', negative: '▼ 下落', neutral: '─ 中立', unknown: '? 不明' };
  const dirKey    = item.direction || 'neutral';
  badgesDiv.appendChild(createBadge(dirLabels[dirKey] ?? dirKey, `badge-direction-${dirKey}`));

  // category
  if (item.category) {
    badgesDiv.appendChild(createBadge(item.category, 'badge-category'));
  }

  // tags (任意)
  if (Array.isArray(item.tags) && item.tags.length > 0) {
    for (const tag of item.tags.slice(0, 4)) {
      if (tag) badgesDiv.appendChild(createBadge(String(tag), 'badge-tag'));
    }
  }

  card.appendChild(badgesDiv);

  /* --- 決算サマリー --- */
  if (item.earnings && typeof item.earnings === 'object') {
    card.appendChild(createEarningsSummary(item.earnings));
  }

  /* --- フッター: reasons / PDF --- */
  const footer = document.createElement('div');
  footer.className = 'card-footer';

  if (item.reasons && item.reasons.length > 0) {
    footer.appendChild(createTextEl('span', `理由: ${item.reasons.join(' / ')}`, 'card-reasons'));
  } else {
    footer.appendChild(document.createElement('span'));
  }

  const pdfUrl = safePdfUrl(item.pdf_url);
  if (pdfUrl) {
    const a = document.createElement('a');
    a.className = 'pdf-link';
    a.href      = pdfUrl;
    a.target    = '_blank';
    a.rel       = 'noopener noreferrer';
    // PDF link内容をSVGとtextで構成
    const pdfSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    pdfSvg.setAttribute('width', '12');
    pdfSvg.setAttribute('height', '12');
    pdfSvg.setAttribute('viewBox', '0 0 24 24');
    pdfSvg.setAttribute('fill', 'none');
    pdfSvg.setAttribute('stroke', 'currentColor');
    pdfSvg.setAttribute('stroke-width', '2');
    pdfSvg.setAttribute('stroke-linecap', 'round');
    pdfSvg.setAttribute('stroke-linejoin', 'round');
    pdfSvg.setAttribute('aria-hidden', 'true');
    const pathEl1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    pathEl1.setAttribute('d', 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z');
    const polyEl = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    polyEl.setAttribute('points', '14 2 14 8 20 8');
    pdfSvg.appendChild(pathEl1);
    pdfSvg.appendChild(polyEl);
    a.appendChild(pdfSvg);
    a.appendChild(document.createTextNode(' PDF'));
    footer.appendChild(a);
  }

  card.appendChild(footer);
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

  // SVG icon
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
  for (const item of filtered) {
    frag.appendChild(createCard(item));
  }
  list.appendChild(frag);
}

function renderHeader() {
  el.updatedAt.textContent  = state.updatedAt ? formatUpdatedAt(state.updatedAt) : '—';
}

function updateSummaryStrip() {
  // サマリーはフィルタ前の全件で計算
  renderSummary(state.items);
}

function setStatus(msg, type) {
  el.statusMsg.textContent = msg;
  el.statusMsg.className   = 'status-msg' + (type ? ' ' + type : '');
}

/* ===== 銘柄絞り込み ===== */

function onStockFilter(code, name) {
  if (state.filterStockCode === code) {
    // 再クリックで解除
    clearStockFilter();
    return;
  }
  state.filterStockCode = code;
  const bar = document.getElementById('stock-filter-bar');
  if (bar) bar.hidden = false;
  const nameEl = document.getElementById('stock-filter-name');
  if (nameEl) nameEl.textContent = `${name} (${code})`;
  renderCards();
}

function clearStockFilter() {
  state.filterStockCode = null;
  const bar = document.getElementById('stock-filter-bar');
  if (bar) bar.hidden = true;
  renderCards();
}

/* ===== データ取得 ===== */

async function fetchData({ silent = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  el.refreshBtn.disabled = true;

  if (!silent) {
    // スピナーをボタンに追加
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

    // 新規 urgent チェック（前回になかったアイテムのみ）
    if (silent) {
      const newItems = state.items.filter((i) => !prevIds.has(String(i.id ?? '')));
      checkNewUrgent(newItems);
    }

    buildCategoryOptions();
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
      const opt    = document.createElement('option');
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
  renderCards();
}

function onCategoryChange() {
  state.filterCategory = el.categorySelect.value;
  renderCards();
}

function onUrgentToggle() {
  state.filterUrgent = el.urgentCheck.checked;
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
  renderCards();
}

function onWatchlistToggle() {
  state.filterWatchlist = !state.filterWatchlist;
  el.btnWatchlist.classList.toggle('active', state.filterWatchlist);
  el.btnWatchlist.setAttribute('aria-pressed', String(state.filterWatchlist));
  renderCards();
}

function onScrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function onWindowScroll() {
  el.scrollTopBtn.classList.toggle('visible', window.scrollY > 300);
}

/* ===== キーボードショートカット ===== */

function onKeyDown(e) {
  // '/' キーで検索フォーカス (入力中は無視)
  if (e.key === '/' && document.activeElement !== el.searchInput) {
    e.preventDefault();
    el.searchInput.focus();
    el.searchInput.select();
  }
  // Escape で検索クリア
  if (e.key === 'Escape' && document.activeElement === el.searchInput) {
    el.searchInput.value = '';
    state.filterKeyword = '';
    renderCards();
  }
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
  document.addEventListener('keydown', onKeyDown);

  const stockClearBtn = document.getElementById('stock-filter-clear');
  if (stockClearBtn) stockClearBtn.addEventListener('click', clearStockFilter);
}

async function init() {
  // テーマを先に適用（FOUC防止）
  initTheme();

  initDOM();
  initEvents();

  // 永続データ読み込み
  loadWatchlist();
  loadLastSeen();
  loadNotifyPref();

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
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
