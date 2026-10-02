// main.js — Owner: A（統合）
// 方針: 各モジュールの新旧APIどちらでも動くよう、任意機能は存在チェックしてから使う（並行開発での破損を防ぐ）。
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { NEWS, WINGS } from './data/news.js';
import { buildMuseum } from './museum.js';
import { createFX } from './fx.js';
import { createPost } from './post.js';
import { createControls } from './controls.js';
import { createUI } from './ui.js';
import { createAudio } from './audio.js';
import { createPerf } from './perf.js';

const canvas = document.getElementById('gl');
const nextFrame = () => new Promise(r => requestAnimationFrame(() => r()));
const call = (o, fn, ...a) => (o && typeof o[fn] === 'function') ? o[fn](...a) : undefined;

function fatal(msg, err) {
  const l = document.getElementById('load-label'); if (l) l.textContent = msg;
  console.error(msg, err || '');
}

async function boot() {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance', stencil: false });
  } catch (e) { fatal('WEBGL NOT AVAILABLE', e); return; }
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping; // 白壁の再現性重視（C提案）
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap; // r186: PCFSoftShadowMap は削除済み（警告が出る）→ 柔らかさは light.shadow.radius で
  renderer.setSize(innerWidth, innerHeight);

  const perf = createPerf(renderer);
  perf.apply();

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xcfc8bd);
  scene.fog = new THREE.FogExp2(0xd9d3c9, 0.010);
  const camera = new THREE.PerspectiveCamera(58, innerWidth / innerHeight, 0.05, 200);

  const audio = createAudio();
  let controls, museum, fx, post;

  const ui = createUI({
    news: NEWS, wings: WINGS,
    onStart: start,
    onTap: () => call(audio, 'tick'),
    onNext: () => controls?.next(),
    onPrev: () => controls?.prev(),
    onSelect: (i) => controls?.goTo(i),
    onToggleSound: () => audio.toggle(),
    onInfo: () => document.getElementById('about')?.classList.add('show'),
  });
  document.getElementById('about')?.addEventListener('click', (e) => e.currentTarget.classList.remove('show'));
  document.getElementById('card')?.addEventListener('click', () => call(ui, 'toggleCard'));

  // ---- 段階ロード ----
  call(ui, 'setLoading', 0.05, 'ENVIRONMENT');
  try { await document.fonts?.ready; } catch {}
  await nextFrame();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envRT = pmrem.fromScene(new RoomEnvironment(), 0.04);
  scene.environment = envRT.texture;
  scene.environmentIntensity = 0.45;
  pmrem.dispose();
  call(ui, 'setLoading', 0.2, 'ARCHITECTURE'); await nextFrame();

  museum = buildMuseum(scene, NEWS, renderer);
  call(ui, 'setLoading', 0.6, 'ATMOSPHERE'); await nextFrame();

  const endZ = museum.endZ ?? -200;
  const len = -endZ + 20;
  fx = createFX(scene, renderer, { length: len, z0: 12, skylights: museum.skylights, hall: museum.hall });
  call(ui, 'setLoading', 0.72, 'OPTICS'); await nextFrame();

  post = createPost(renderer, scene, camera, perf.quality);
  controls = createControls(camera, canvas, museum);

  // ---- 影: 静的部分が多いので更新は必要時のみ ----
  renderer.shadowMap.autoUpdate = false;
  let shadowDirty = 3;
  const markShadow = (n = 2) => { shadowDirty = Math.max(shadowDirty, n); };

  // 展示ライト: 注視中の1灯だけ影を落とす（性能予算: 影ライト最大2灯）
  const exhibitLights = (museum.exhibits || []).map(e => e.mesh?.userData?.light || null);
  let shadowLightIdx = -1;
  function setShadowExhibit(i) {
    if (i === shadowLightIdx) return;
    exhibitLights.forEach((L, k) => { if (L) L.castShadow = (k === i) && renderer.shadowMap.enabled; });
    shadowLightIdx = i; markShadow();
  }

  const applyQ = (q, p) => {
    const prof = p || perf.profile || {};
    call(post, 'setQuality', q);
    call(fx, 'setDensity', prof.particles ?? (q === 'high' ? 1 : q === 'mid' ? 0.6 : 0.35));
    call(fx, 'setPixelRatio', renderer.getPixelRatio());
    call(museum, 'setQuality', q, prof);
    if (prof.shadowMap) scene.traverse(o => { if (o.isLight && o.shadow && o.castShadow && o.shadow.mapSize.x !== prof.shadowMap) { o.shadow.mapSize.set(prof.shadowMap, prof.shadowMap); o.shadow.map?.dispose(); o.shadow.map = null; } });
    const k = shadowLightIdx; shadowLightIdx = -2; setShadowExhibit(k);
    post.resize(innerWidth, innerHeight);
    markShadow();
  };
  perf.onChange(applyQ); applyQ(perf.quality, perf.profile);

  // ---- シェーダ事前コンパイル ----
  call(ui, 'setLoading', 0.85, 'COMPILING SHADERS'); await nextFrame();
  try { await renderer.compileAsync(scene, camera); } catch { try { renderer.compile(scene, camera); } catch {} }
  renderer.shadowMap.needsUpdate = true;
  post.render(0, 0.016);
  call(ui, 'setLoading', 1, 'READY'); call(ui, 'ready');

  // ---- HUD 連携 ----
  const stops = museum.stops;
  const wingOf = (stop) => {
    if (stop.kind === 'exhibit') return WINGS.find(w => w.id === NEWS[stop.index].wing);
    if (stop.kind === 'finale') return { id: 'end', name: 'EPILOGUE', sub: 'そして、次の50日へ', color: '#c9a46a' };
    return { id: 'intro', name: 'ENTRANCE', sub: '入館', color: '#c9a46a' };
  };
  const syncHud = (i) => {
    call(ui, 'setStop', i, stops.length, wingOf(stops[i]));
    call(ui, 'setProgress', i / (stops.length - 1));
  };
  const focusWorld = new THREE.Vector3();
  function exhibitFocus(idx) {
    const ud = museum.exhibits[idx]?.mesh?.userData || {};
    if (ud.sculpt) return ud.sculpt.getWorldPosition(focusWorld);
    if (ud.focus) { museum.exhibits[idx].mesh.localToWorld(focusWorld.copy(ud.focus)); return focusWorld; }
    return focusWorld.copy(museum.exhibits[idx].anchor);
  }

  controls.onDepart((i) => {
    call(ui, 'setMoving', true);
    call(ui, 'hideNews'); call(ui, 'showFinale', false); call(fx, 'finale', false); syncHud(i);
    call(post, 'setMotion', 1); call(audio, 'whoosh', 1.4);
  });
  controls.onArrive((i) => {
    call(ui, 'setMoving', false);
    call(post, 'setMotion', 0);
    const s = stops[i];
    if (s.kind === 'exhibit') {
      const n = NEWS[s.index];
      call(ui, 'showNews', n); call(audio, 'chime', s.index);
      setShadowExhibit(s.index);
      call(fx, 'burst', exhibitFocus(s.index).clone(), n.color);
      call(audio, 'setIntensity', s.index / NEWS.length);
      call(audio, 'setPan', museum.exhibits[s.index].side ?? 0);
    } else if (s.kind === 'finale') {
      call(ui, 'showFinale', true); call(post, 'flash', 0.25); call(fx, 'finale', true);
      if (typeof audio.finale === 'function') audio.finale(); else call(audio, 'chime', 99);
    }
    markShadow();
  });
  document.getElementById('btn-restart')?.addEventListener('click', (e) => { e.stopPropagation(); controls.goTo(0); });
  syncHud(0);

  // ---- 開始（全画面＋横固定） ----
  let started = false;
  async function start() {
    if (started) return; started = true;
    const el = document.documentElement;
    try {
      if (!document.fullscreenElement && el.requestFullscreen) await el.requestFullscreen({ navigationUI: 'hide' });
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    } catch {}
    try { await screen.orientation?.lock?.('landscape'); } catch {}
    try { if (typeof DeviceOrientationEvent?.requestPermission === 'function') await DeviceOrientationEvent.requestPermission(); } catch {}
    audio.start(); call(ui, 'started');
    call(post, 'fadeIn'); call(post, 'flash', 0.5);
    setTimeout(() => controls.goTo(1), 1800);
  }
  // 自動テスト/デモ用: ?autostart
  if (new URLSearchParams(location.search).has('autostart')) { started = true; call(ui, 'started'); call(post, 'fadeIn'); setTimeout(() => controls.goTo(1), 500); }

  // ---- リサイズ ----
  const onResize = () => {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); post.resize(w, h); markShadow();
  };
  addEventListener('resize', onResize);
  screen.orientation?.addEventListener?.('change', () => setTimeout(onResize, 250));

  // ---- メインループ ----
  let last = performance.now(), t = 0, running = true, frameNo = 0;
  document.addEventListener('visibilitychange', () => {
    running = !document.hidden;
    if (running) { last = performance.now(); call(audio, 'resume'); requestAnimationFrame(loop); } else call(audio, 'suspend');
  });
  function loop(now) {
    if (!running) return;
    const dt = Math.min(0.05, Math.max(0, (now - last) / 1000)); last = now; t += dt;
    controls.update(dt, t);
    const s = stops[controls.index];
    const focus = s.kind === 'exhibit' && !controls.moving ? s.index : -1;
    museum.update(t, dt, focus, camera);
    fx.update(t, dt, camera);
    if (focus >= 0) call(post, 'setFocusWorld', exhibitFocus(focus)); else call(post, 'setFocusWorld', null);
    if ((++frameNo & 3) === 0) markShadow(1); // 回転彫刻の影を1/4レートで更新
    if (shadowDirty > 0) { renderer.shadowMap.needsUpdate = true; shadowDirty--; }
    post.render(t, dt);
    perf.tick(dt);
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  window.__FT = { renderer, scene, camera, controls, museum, perf, fx, post };
}

boot().catch(e => fatal('BOOT ERROR: ' + (e?.message || e), e));
