// ultra_g/index.js — Owner: G（デザイン総監修）
// 既存 UI(E) の DOM を壊さず「意匠レイヤ」を重ねる。ui.js の再描画にも追従（MutationObserver・冪等）。
// 単体で動く（<script type="module" src="js/ultra_g/index.js">）。ロールシステムズのフック契約 install(ctx) にも対応。
// ?g=0 で無効化（比較用）。
import { NEWS, WINGS } from '../data/news.js';

const Q = new URLSearchParams(location.search);
const ENABLED = Q.get('g') !== '0';
const ROMAN = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'];
const T0 = Date.UTC(2026, 7, 12), T1 = Date.UTC(2026, 9, 1), DAY = 864e5;
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const parse = (s) => { const m = String(s ?? '').match(/(\d{4})\D(\d{1,2})(?:\D(\d{1,2}))?/); return m ? Date.UTC(+m[1], +m[2] - 1, m[3] ? +m[3] : 15) : null; };
const pos = (t) => Math.max(0, Math.min(100, ((t - T0) / (T1 - T0)) * 100));

let installed = false;
const observers = [];

function ensureCSS() {
  if ($('link[data-g]')) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.dataset.g = '1';
  l.href = new URL('../../css/ultra_g.css', import.meta.url).href;
  document.head.appendChild(l);
}

// ---------- 1. タイトル（特別展ポスター） ----------
function decorateIntro() {
  const intro = $('#intro'); if (!intro) return;
  if (!$('.g-plate', intro)) {
    intro.insertAdjacentHTML('afterbegin', `
      <figure class="g-plate" aria-hidden="true">
        <div class="g-frame"><div class="g-img"></div></div>
        <figcaption class="g-cap"><span><b>PLATE I</b>　Michelangelo, <i>The Creation of Adam</i> (detail), c.1512</span></figcaption>
      </figure>
      <div class="g-spine" aria-hidden="true"></div>
      <div class="g-tate" aria-hidden="true">人工知能、五十日の軌跡<small>特別展　二〇二六年秋</small><span class="g-seal">軌</span></div>
      <div class="g-meta tl" aria-hidden="true"><b>FLAT TRAIL</b><span class="g-dot"></span>SPECIAL EXHIBITION<span class="g-dot"></span>${WINGS.length} ROOMS · ${NEWS.length} WORKS</div>
      `);
  }
  const eb = $('.eyebrow');
  if (eb && !eb.dataset.g) { eb.dataset.g = '1'; eb.innerHTML = `Special Exhibition<em>— fifty days in AI</em>`; }
  const tj = $('.tagline-jp');
  if (tj && !tj.dataset.g && /50日/.test(tj.textContent)) { tj.dataset.g = '1'; tj.innerHTML = `2026.8.12 — 10.1　AIが動いた50日間、${NEWS.length}の展示`; }
  const hint = $('.hint');
  if (hint && !hint.dataset.g) { hint.dataset.g = '1'; hint.innerHTML = 'タップで全画面・横向き表示<br>スワイプ／右下のボタンで次へ　ドラッグで見回し'; }
  const btn = $('#btn-start');
  if (btn && !$('.g-arrow', btn)) btn.insertAdjacentHTML('beforeend', '<span class="g-arrow">→</span>');
}

// ---------- 2. 定規: 展示室ブラケット ----------
const roomEls = {};
function decorateTimeline() {
  const tl = $('#timeline'); if (!tl || $('.g-room', tl)) return;
  WINGS.forEach((w, wi) => {
    const ts = NEWS.filter(n => n.wing === w.id).map(n => parse(n.date)).filter(v => v != null);
    if (!ts.length) return;
    const a = pos(Math.min(...ts)), b = pos(Math.max(...ts));
    const pad = 0.55; // %
    const e = document.createElement('div');
    e.className = 'g-room';
    e.style.left = `${Math.max(0, a - pad)}%`; e.style.width = `${Math.max(1.6, b - a + pad * 2)}%`;
    e.style.setProperty('--c', w.color);
    e.innerHTML = `<span>${ROMAN[wi + 1]}</span>`;
    e.title = w.name;
    tl.appendChild(e); roomEls[w.id] = e;
  });
}
function syncRoom() {
  const id = $('#hud-wing')?.dataset.id;
  for (const k in roomEls) roomEls[k].classList.toggle('on', k === id);
}

// ---------- 3. キャプション: 展示室ライン ----------
function decorateCard() {
  const card = $('#card'); if (!card) return;
  const no = $('#card-no')?.textContent?.trim();
  const n = NEWS.find(x => x.no === no); if (!n) return;
  let line = $('.g-card-room', card);
  if (!line) { line = document.createElement('div'); line.className = 'g-card-room'; card.prepend(line); }
  if (line.dataset.no === no) return;
  line.dataset.no = no;
  const wi = WINGS.findIndex(w => w.id === n.wing);
  const k = NEWS.filter(x => x.wing === n.wing).indexOf(n) + 1;
  const tot = NEWS.filter(x => x.wing === n.wing).length;
  line.innerHTML = `<span>ROOM <b>${ROMAN[wi + 1] || ''}</b></span><span>${esc(WINGS[wi]?.name || '')}</span><span>${k} / ${tot}</span>`;
}

// ---------- 4. 章扉 ----------
function decorateRoomTitle() {
  const rt = $('#room-title'); if (!rt) return;
  const no = $('.rt-no', rt);
  if (no && !no.dataset.g) {
    no.dataset.g = '1';
    const m = no.textContent.match(/ROOM\s+(\S+)/);
    if (m) no.innerHTML = `<span class="g-rn-label">ROOM</span><span class="g-rn">${esc(m[1])}</span>`;
  }
  const nm = $('.rt-name', rt);
  if (nm && !nm.dataset.g) {
    nm.dataset.g = '1';
    nm.innerHTML = [...nm.textContent].map((c, i) => c === ' ' ? ' ' : `<span class="g-l" style="--i:${i}">${esc(c)}</span>`).join('');
  }
}

function observe(sel, fn, opts = { childList: true, subtree: true, characterData: true }) {
  const target = typeof sel === 'string' ? $(sel) : sel; if (!target) return;
  const mo = new MutationObserver(() => { mo.disconnect(); try { fn(); } finally { mo.observe(target, opts); } });
  mo.observe(target, opts); observers.push(mo);
}

function apply() {
  if (installed || !ENABLED) return;
  installed = true;
  document.documentElement.classList.add('g');
  ensureCSS();
  if (!$('#g-grade')) { const g = document.createElement('div'); g.id = 'g-grade'; document.body.insertBefore(g, $('#intro')); }
  decorateIntro(); decorateTimeline(); decorateCard(); decorateRoomTitle(); syncRoom();
  observe('#intro', decorateIntro);
  observe('#timeline', () => { decorateTimeline(); syncRoom(); }, { childList: true });
  observe('#hud-wing', syncRoom, { attributes: true, attributeFilter: ['data-id'] });
  observe('#card', decorateCard);
  observe('#hud', () => { if ($('#room-title')) { decorateRoomTitle(); } }, { childList: true });
  const rt = $('#room-title'); if (rt) observe(rt, decorateRoomTitle);
  else { const mo = new MutationObserver(() => { const r = $('#room-title'); if (r) { mo.disconnect(); decorateRoomTitle(); observe(r, decorateRoomTitle); } }); mo.observe($('#hud') || document.body, { childList: true }); observers.push(mo); }
  $('#btn-start')?.addEventListener('click', () => document.body.classList.add('g-enter'));
}

/** ロールシステムズ フック契約 */
export function install(ctx = {}) {
  apply();
  return {
    dispose() { observers.forEach(o => o.disconnect()); document.documentElement.classList.remove('g'); },
  };
}

// 単体読込でも動作（ui.js の初期 DOM 生成を待つ）
if (ENABLED) {
  const go = () => setTimeout(apply, 0);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
}
