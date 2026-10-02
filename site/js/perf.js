// perf.js — Owner: F
// 動的画質制御
//  - 起動時: GPU名(WEBGL_debug_renderer_info)・端末メモリ・コア数・画面から初期品質を推定
//  - 実行時: フレーム時間の移動平均を監視し high ↔ mid ↔ low を自動切替（ヒステリシス＋クールダウン）
//  - 各品質のプロファイル(profile)を公開: 他モジュールはこれを見て影/ポスト/粒子数を決められる
//  - URL: ?q=high|mid|low で固定, ?debug で FPS/描画統計オーバーレイ
// API（INTERFACES互換）: createPerf(renderer) -> { quality, tick(dt), onChange(cb), apply(), profile, fps, locked }
// 2026-10-02 ULTRA（ユーザー指示「機種性能無視の超高グラフィック」）:
//  - 既定で ultra=true（?ultra=0 で従来挙動）。quality 文字列は low|mid|high のまま（既存モジュール互換）。
//  - ultra 時は high を初期値にし、high のプロファイルを ULTRA_PROFILE で上書き（DPR2/影2048/粒子1.5…）。
//  - 自動降格は「本当に破綻している時」だけ（<20fps が4秒続いた時）。昇格は従来通り。
//  - 追加API: perf.ultra(bool), perf.tier ('ultra'|'high'|'mid'|'low'), PROFILES.ultra

export const PROFILES = {
  low:  { pixelRatio: 1.0,  shadows: false, shadowMap: 512,  bloom: false, dof: false, ssao: false, particles: 0.35, aniso: 2 },
  mid:  { pixelRatio: 1.35, shadows: true,  shadowMap: 1024, bloom: true,  dof: false, ssao: false, particles: 0.6,  aniso: 4 },
  high: { pixelRatio: 1.5,  shadows: true,  shadowMap: 1024, bloom: true,  dof: true,  ssao: true,  particles: 1.0,  aniso: 8 },
};
// ultra: high の上位互換。追加キーは任意利用（ultra_* 拡張が見る: ssr/taa/volumetricSteps/envRes/maxAniso）
export const ULTRA_PROFILE = { pixelRatio: 2.0, shadows: true, shadowMap: 2048, bloom: true, dof: true, ssao: true, particles: 1.5, aniso: 16,
  ssr: true, taa: true, volumetricSteps: 48, envRes: 512 };
PROFILES.ultra = ULTRA_PROFILE;
const LEVELS = ['low', 'mid', 'high'];

function detectGPU(renderer) {
  let name = '';
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    name = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  } catch {}
  return String(name || '');
}

function initialLevel(gpu) {
  const g = gpu.toLowerCase();
  const mobile = matchMedia('(pointer:coarse)').matches || /android|iphone|ipad/i.test(navigator.userAgent);
  const mem = navigator.deviceMemory || 4, cores = navigator.hardwareConcurrency || 4;
  if (/swiftshader|llvmpipe|software|basic render/.test(g)) return 'low';
  if (/mali-[gt]?[0-9]{2}\b|adreno \(tm\) [3-5]\d\d|powervr|sgx/.test(g)) return 'low';
  if (mobile) {
    // Apple A15+ / Adreno 7xx+ / Mali-G7xx+ / Xclipse は mid から開始し、余裕があれば high に上がる
    if (mem <= 3 || cores <= 4) return 'low';
    return 'mid';
  }
  if (/intel/.test(g) && !/arc/.test(g)) return 'mid';
  return 'high';
}

export function createPerf(renderer, { initial } = {}) {
  const qs = new URLSearchParams(location.search);
  const gpu = detectGPU(renderer);
  const forced = qs.get('q');
  const ultra = qs.get('ultra') !== '0' && forced !== 'low' && forced !== 'mid';
  const locked = LEVELS.includes(forced) || forced === 'ultra';
  let idx = LEVELS.indexOf(forced === 'ultra' ? 'high' : locked ? forced : (initial || (ultra ? 'high' : initialLevel(gpu))));
  if (idx < 0) idx = 1;

  const cbs = [];
  let acc = 0, frames = 0, cooldown = 3, lowCount = 0, highCount = 0, fps = 60, worst = 0;
  let maxReached = idx; // 一度落ちた品質へ戻る際は慎重に（ピンポン防止）
  let downgrades = 0;

  const prof = () => (ultra && LEVELS[idx] === 'high') ? ULTRA_PROFILE : PROFILES[LEVELS[idx]];
  const apply = () => {
    const q = LEVELS[idx], p = prof();
    // リーダー決定(7): スマホは DPR 上限 1.5。デスクトップ high のみ 1.75 まで許可（ultra 時は DPR 2.0）
    const cap = p === ULTRA_PROFILE ? p.pixelRatio : (q === 'high' && !matchMedia('(pointer:coarse)').matches) ? 1.75 : p.pixelRatio;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap));
    if (renderer.shadowMap) renderer.shadowMap.enabled = p.shadows;
    cbs.forEach(cb => { try { cb(q, p); } catch (e) { console.error('[perf] onChange', e); } });
    if (dbg) dbg.dataset.q = q;
  };

  // ---- デバッグオーバーレイ ----
  let dbg = null;
  if (qs.has('debug')) {
    dbg = document.createElement('div');
    dbg.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:9999;font:11px/1.35 ui-monospace,monospace;color:#2b2620;background:rgba(245,240,230,.85);padding:6px 8px;border-radius:4px;pointer-events:none;white-space:pre';
    document.body.appendChild(dbg);
  }

  return {
    get quality() { return LEVELS[idx]; },
    get profile() { return prof(); },
    get tier() { return prof() === ULTRA_PROFILE ? 'ultra' : LEVELS[idx]; },
    ultra,
    get fps() { return fps; },
    get gpu() { return gpu; },
    locked,
    onChange(cb) { cbs.push(cb); },
    apply,
    set(q) { const i = LEVELS.indexOf(q); if (i >= 0 && i !== idx) { idx = i; apply(); } },
    tick(dt) {
      if (dt > 0.5 || document.hidden) return; // タブ復帰などの外れ値は無視
      acc += dt; frames++; cooldown -= dt; worst = Math.max(worst, dt);
      if (acc < 1) return;
      fps = frames / acc;
      if (dbg) {
        const i = renderer.info;
        dbg.textContent = `${fps.toFixed(0)} fps  worst ${(worst * 1000).toFixed(0)}ms  q:${prof() === ULTRA_PROFILE ? 'ultra' : LEVELS[idx]}${locked ? '(locked)' : ''}\n` +
          `calls ${i.render.calls}  tris ${(i.render.triangles / 1000).toFixed(0)}k  tex ${i.memory.textures}  geo ${i.memory.geometries}\n` +
          `pr ${renderer.getPixelRatio().toFixed(2)}  ${gpu.slice(0, 48)}`;
      }
      acc = 0; frames = 0; worst = 0;
      if (locked || cooldown > 0) return;
      const lowFps = ultra ? 20 : 40, needLow = ultra ? 4 : 2;
      if (fps < lowFps) { lowCount++; highCount = 0; }
      else if (fps > 57) { highCount++; lowCount = 0; }
      else { lowCount = Math.max(0, lowCount - 1); highCount = 0; }
      if (lowCount >= needLow && idx > 0) {
        idx--; downgrades++; lowCount = 0; cooldown = 4; apply();
      } else if (idx < 2 && highCount >= (idx + 1 > maxReached ? 8 : 5) + downgrades * 4) {
        idx++; maxReached = Math.max(maxReached, idx); highCount = 0; cooldown = 6; apply();
      }
    },
  };
}
