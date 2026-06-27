/**
 * TDnet 適時開示ダッシュボード — app.js
 * Vanilla JS, no build step.
 */

'use strict';

/* ===== 定数 ===== */
const DATA_URL        = './data/disclosures.json';
const AUTO_REFRESH_MS = 60_000; // 60秒

/* ===== 状態 ===== */
const state = {
  items:       [],   // raw items from JSON
  updatedAt:   null, // string
  totalCount:  0,

  filterImpact:    'all',  // 'all' | 'high' | 'medium' | 'low'
  filterCategory:  'all',
  filterUrgent:    false,
  filterKeyword:   '',
  sortOrder:       'time', // 'time' | 'score'

  loading:  false,
  error:    null,
};

/* ===== DOM 参照キャッシュ ===== */
const el = {};

/* ===== ユーティリティ ===== */

/**
 * Date を "M/D HH:MM" 形式 (JST) に変換
 * @param {string} iso
 * @returns {{hhmm: string, date: string}}
 */
function parseTime(iso) {
  if (!iso) return { hhmm: '--:--', date: '' };
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return { hhmm: '--:--', date: '' };
    const pad = (n) => String(n).padStart(2, '0');
    // JST = UTC+9
    const jst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
    const hhmm = `${pad(jst.getUTCHours())}:${pad(jst.getUTCMinutes())}`;
    const date  = `${jst.getUTCMonth() + 1}/${jst.getUTCDate()}`;
    return { hhmm, date };
  } catch {
    return { hhmm: '--:--', date: '' };
  }
}

/**
 * "2026-06-27T15:01:00+09:00" → "2026/06/27 15:01 JST"
 * @param {string} iso
 * @returns {string}
 */
function formatUpdatedAt(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, '0');
    const jst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
    return `${jst.getUTCFullYear()}/${pad(jst.getUTCMonth()+1)}/${pad(jst.getUTCDate())} `
         + `${pad(jst.getUTCHours())}:${pad(jst.getUTCMinutes())} JST`;
  } catch {
    return iso;
  }
}

/**
 * URL を安全に検証して返す（javascript: 等を拒否）
 * @param {string} url
 * @returns {string|null}
 */
function safePdfUrl(url) {
  if (!url || typeof url !== 'string') return null;
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
    // PDF URL として基本的に tdnet か主要ドメインのみ許可
    return u.href;
  } catch {
    return null;
  }
}

/**
 * XSS-safe なテキストノードを作成して要素に追加
 * @param {HTMLElement} parent
 * @param {string} tag
 * @param {string} text
 * @param {string} [className]
 * @returns {HTMLElement}
 */
function createTextEl(tag, text, className) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.textContent = String(text ?? '');
  return el;
}

/* ===== カテゴリ一覧を items から動的生成 ===== */
function buildCategoryOptions() {
  const categories = new Set();
  for (const item of state.items) {
    if (item.category) categories.add(item.category);
  }
  const sel = el.categorySelect;
  // 現在の選択を保持
  const current = sel.value;
  // all 以外の option を削除
  while (sel.options.length > 1) sel.remove(1);
  for (const cat of [...categories].sort()) {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    sel.appendChild(opt);
  }
  // 前の選択を復元（存在すれば）
  if ([...categories].includes(current)) {
    sel.value = current;
  }
}

/* ===== フィルタ & ソート ===== */
function applyFilters() {
  let result = state.items.slice();

  // impact フィルタ
  if (state.filterImpact !== 'all') {
    result = result.filter((i) => i.impact === state.filterImpact);
  }

  // category フィルタ
  if (state.filterCategory !== 'all') {
    result = result.filter((i) => i.category === state.filterCategory);
  }

  // urgent フィルタ
  if (state.filterUrgent) {
    result = result.filter((i) => i.urgent === true);
  }

  // キーワードフィルタ（会社名/コード/タイトル/要約）
  const kw = state.filterKeyword.trim().toLowerCase();
  if (kw) {
    result = result.filter((i) => {
      return (
        (i.company  && i.company.toLowerCase().includes(kw))  ||
        (i.code     && i.code.toLowerCase().includes(kw))     ||
        (i.title    && i.title.toLowerCase().includes(kw))    ||
        (i.summary  && i.summary.toLowerCase().includes(kw))
      );
    });
  }

  // ソート
  if (state.sortOrder === 'score') {
    result.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  } else {
    // time 降順（デフォルト）
    result.sort((a, b) => {
      const ta = a.time ? new Date(a.time).getTime() : 0;
      const tb = b.time ? new Date(b.time).getTime() : 0;
      return tb - ta;
    });
  }

  return result;
}

/* ===== カード描画 ===== */

/**
 * impact / direction / urgent などのバッジを作成
 */
function createBadge(text, className) {
  const span = document.createElement('span');
  span.className = 'badge ' + className;
  span.textContent = text;
  return span;
}

/**
 * スコアリング SVG サークル
 */
function createScoreRing(score, impact) {
  const safeScore = Math.max(0, Math.min(100, Number(score) || 0));
  const r = 18;
  const circ = 2 * Math.PI * r;
  const offset = circ - (safeScore / 100) * circ;

  const wrapper = document.createElement('div');
  wrapper.className = 'score-ring';
  wrapper.dataset.impact = impact || 'low';

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

/**
 * 1件分のカード要素を生成（XSS 安全、innerHTML 不使用）
 */
function createCard(item) {
  const card = document.createElement('article');
  card.className = 'card';
  card.dataset.impact = item.impact || 'low';

  /* --- 上部行: 時刻 / 会社情報 / スコアリング --- */
  const cardTop = document.createElement('div');
  cardTop.className = 'card-top';

  // 時刻
  const { hhmm, date } = parseTime(item.time);
  const timeDiv = document.createElement('div');
  timeDiv.className = 'card-time';
  const hhmmSpan = document.createElement('span');
  hhmmSpan.className = 'time-hhmm';
  hhmmSpan.textContent = hhmm;
  const dateSpan = document.createElement('span');
  dateSpan.textContent = date;
  timeDiv.appendChild(hhmmSpan);
  timeDiv.appendChild(dateSpan);

  // 会社情報
  const companyDiv = document.createElement('div');
  companyDiv.className = 'card-company';
  const codeSpan = createTextEl('span', `${item.code ?? ''}  ${item.exchange ?? ''}${item.markets ? ' ' + item.markets : ''}`, 'company-code');
  const nameSpan = createTextEl('span', item.company ?? '（不明）', 'company-name');
  nameSpan.title = item.company ?? '';
  companyDiv.appendChild(codeSpan);
  companyDiv.appendChild(nameSpan);

  // スコアリング
  const scoreRing = createScoreRing(item.score, item.impact);
  scoreRing.setAttribute('title', `スコア: ${item.score ?? 0}`);

  cardTop.appendChild(timeDiv);
  cardTop.appendChild(companyDiv);
  cardTop.appendChild(scoreRing);
  card.appendChild(cardTop);

  /* --- タイトル --- */
  card.appendChild(createTextEl('p', item.title ?? '（タイトルなし）', 'card-title'));

  /* --- 要約 --- */
  if (item.summary) {
    card.appendChild(createTextEl('p', item.summary, 'card-summary'));
  }

  /* --- バッジ群 --- */
  const badgesDiv = document.createElement('div');
  badgesDiv.className = 'card-badges';

  // urgent
  if (item.urgent === true) {
    badgesDiv.appendChild(createBadge('🔥 緊急', 'badge-urgent'));
  }

  // impact
  const impactLabels = { high: '高', medium: '中', low: '低' };
  const impactKey = item.impact || 'low';
  badgesDiv.appendChild(createBadge(
    `重要度: ${impactLabels[impactKey] ?? impactKey}`,
    `badge badge-impact-${impactKey}`
  ));

  // direction
  const dirLabels    = { positive: '▲ 上昇', negative: '▼ 下落', neutral: '─ 中立' };
  const dirKey       = item.direction || 'neutral';
  badgesDiv.appendChild(createBadge(
    dirLabels[dirKey] ?? dirKey,
    `badge badge-direction-${dirKey}`
  ));

  // category
  if (item.category) {
    badgesDiv.appendChild(createBadge(item.category, 'badge badge-category'));
  }

  card.appendChild(badgesDiv);

  /* --- フッター: reasons / PDF リンク --- */
  const footer = document.createElement('div');
  footer.className = 'card-footer';

  if (item.reasons && item.reasons.length > 0) {
    const reasons = createTextEl('span', `理由: ${item.reasons.join(' / ')}`, 'card-reasons');
    footer.appendChild(reasons);
  } else {
    footer.appendChild(document.createElement('span')); // spacer
  }

  const pdfUrl = safePdfUrl(item.pdf_url);
  if (pdfUrl) {
    const a = document.createElement('a');
    a.className = 'pdf-link';
    a.href = pdfUrl;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = '📄 PDF';
    footer.appendChild(a);
  }

  card.appendChild(footer);
  return card;
}

/* ===== UI 更新 ===== */

function renderCards() {
  const filtered = applyFilters();
  const list = el.cardList;

  // 結果件数
  el.resultCount.textContent = `${filtered.length} 件表示`;

  // リストをクリア
  while (list.firstChild) list.removeChild(list.firstChild);

  if (filtered.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    const icon = document.createElement('div');
    icon.className = 'empty-icon';
    icon.textContent = '📭';
    const msg = document.createElement('p');
    msg.textContent = 'データがありません';
    empty.appendChild(icon);
    empty.appendChild(msg);
    list.appendChild(empty);
    return;
  }

  const frag = document.createDocumentFragment();
  for (const item of filtered) {
    frag.appendChild(createCard(item));
  }
  list.appendChild(frag);
}

function renderHeader() {
  el.updatedAt.textContent  = state.updatedAt ? formatUpdatedAt(state.updatedAt) : '—';
  el.countBadge.textContent = `全 ${state.totalCount} 件`;
}

function setStatus(msg, type) {
  // type: '' | 'loading' | 'error'
  el.statusMsg.textContent = msg;
  el.statusMsg.className   = 'status-msg' + (type ? ' ' + type : '');
}

/* ===== データ取得 ===== */

async function fetchData() {
  if (state.loading) return;
  state.loading = true;
  el.refreshBtn.disabled = true;

  const spinnerSpan = document.createElement('span');
  spinnerSpan.className = 'spinner';
  el.refreshBtn.prepend(spinnerSpan);
  setStatus('データを取得中…', 'loading');

  try {
    const url  = `${DATA_URL}?t=${Date.now()}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }
    const json = await resp.json();

    state.items      = Array.isArray(json.items) ? json.items : [];
    state.updatedAt  = typeof json.updated_at === 'string' ? json.updated_at : null;
    state.totalCount = typeof json.count === 'number' ? json.count : state.items.length;
    state.error      = null;

    buildCategoryOptions();
    renderHeader();
    renderCards();
    setStatus(`${formatUpdatedAt(new Date().toISOString())} 更新`, '');
  } catch (err) {
    state.error = err.message;
    // データが既にある場合は既存表示を維持し、エラーのみ伝える
    if (state.items.length === 0) {
      const list = el.cardList;
      while (list.firstChild) list.removeChild(list.firstChild);
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      const icon = document.createElement('div');
      icon.className = 'empty-icon';
      icon.textContent = '⚠️';
      const msg = document.createElement('p');
      msg.textContent = 'データがありません（取得失敗）';
      empty.appendChild(icon);
      empty.appendChild(msg);
      list.appendChild(empty);
      el.resultCount.textContent = '0 件表示';
    }
    setStatus(`取得エラー: ${err.message}`, 'error');
    console.error('[TDnet Dashboard] fetch error:', err);
  } finally {
    state.loading = false;
    el.refreshBtn.disabled = false;
    if (el.refreshBtn.firstChild && el.refreshBtn.firstChild.classList &&
        el.refreshBtn.firstChild.classList.contains('spinner')) {
      el.refreshBtn.removeChild(el.refreshBtn.firstChild);
    }
  }
}

/* ===== イベントハンドラ ===== */

function onImpactToggle(e) {
  const btn = e.currentTarget;
  const impact = btn.dataset.impact;

  // active 状態の切替（同じボタン再クリックで 'all' に戻す）
  if (state.filterImpact === impact) {
    state.filterImpact = 'all';
  } else {
    state.filterImpact = impact;
  }

  // ボタンの active クラス更新
  el.impactBtns.forEach((b) => {
    b.classList.toggle('active', b.dataset.impact === state.filterImpact);
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
  el.sortBtns.forEach((b) => b.classList.toggle('active', b.dataset.sort === state.sortOrder));
  renderCards();
}

function onScrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function onWindowScroll() {
  if (window.scrollY > 300) {
    el.scrollTopBtn.classList.add('visible');
  } else {
    el.scrollTopBtn.classList.remove('visible');
  }
}

/* ===== 初期化 ===== */

function initDOM() {
  el.updatedAt    = document.getElementById('updated-at');
  el.countBadge   = document.getElementById('count-badge');
  el.refreshBtn   = document.getElementById('btn-refresh');
  el.impactBtns   = document.querySelectorAll('[data-impact]');
  el.categorySelect = document.getElementById('filter-category');
  el.urgentCheck  = document.getElementById('filter-urgent');
  el.searchInput  = document.getElementById('search-input');
  el.sortBtns     = document.querySelectorAll('[data-sort]');
  el.cardList     = document.getElementById('card-list');
  el.resultCount  = document.getElementById('result-count');
  el.statusMsg    = document.getElementById('status-msg');
  el.scrollTopBtn = document.getElementById('scroll-top-btn');
}

function initEvents() {
  el.refreshBtn.addEventListener('click', fetchData);

  el.impactBtns.forEach((btn) => {
    if (btn.dataset.impact) btn.addEventListener('click', onImpactToggle);
  });

  el.categorySelect.addEventListener('change', onCategoryChange);
  el.urgentCheck.addEventListener('change', onUrgentToggle);
  el.searchInput.addEventListener('input', onSearchInput);

  el.sortBtns.forEach((btn) => {
    btn.addEventListener('click', onSortChange);
  });

  el.scrollTopBtn.addEventListener('click', onScrollTop);
  window.addEventListener('scroll', onWindowScroll, { passive: true });
}

function initAutoRefresh() {
  setInterval(fetchData, AUTO_REFRESH_MS);
}

function init() {
  initDOM();
  initEvents();
  initAutoRefresh();
  fetchData();
}

// DOM 準備完了後に起動
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
