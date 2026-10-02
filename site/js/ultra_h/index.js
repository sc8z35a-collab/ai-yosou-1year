// ultra_h/index.js — Owner: H（アートディレクター）
// 「白い箱の連続」を「章ごとに色と旗を持つ美術館」へ。既存ファイル無変更・install(ctx) フック契約準拠。
//  1) ROOM PAINT   : 各展示室の側壁を顔料色で塗装（巾木上〜ピクチャーレール 4.2m）。上部と間仕切りは白漆喰のまま残し、
//                    「白いポータル → 色の部屋 → 白いポータル」の律動をつくる。端部は漆喰色の見切り材。
//  2) LABEL BOARD  : 壁面キャプションの背面に生成りのラベルボード（影目地付き）→ 濃色壁でも墨文字が読める。
//  3) BANNERS      : 各室入口直後に左右一対の吊り旗（顔料色の織物・真鍮ロッド・縦書き和文・ローマ数字）。微風で揺れる。
//  4) LOBBY BANNERS: ロビーに館の大旗（THE MUSEUM OF AI HEADLINES / AIの50日）。
//  5) THRESHOLD    : 各ポータル床に真鍮の見切り（2本）。
// 契約: install(ctx) -> { update(t,dt), setQuality(q), dispose() }。ctx は README の拡張フック契約。
//       ctx.museum = { exhibits:[{mesh,side,news}], hall:{width,height}, endZ, root? }
import * as THREE from 'three';

// 章の顔料（美術館の壁色として実在しうる低彩度・中〜深明度。WINGS.color の色相を継承）
export const ROOM_PAINT = {
  summer:    { wall: '#c2a27c', banner: '#8f6a45', name: 'Raw Sienna Wash' },
  tectonics: { wall: '#6f8270', banner: '#4c5e4e', name: 'Lichen' },
  surge:     { wall: '#a8644a', banner: '#8a4630', name: 'Terracotta' },
  bounds:    { wall: '#536379', banner: '#36445a', name: 'Slate' },
  converge:  { wall: '#7f6049', banner: '#5c412f', name: 'Tobacco' },
  threshold: { wall: '#6a2c2e', banner: '#4e1a1d', name: 'Oxblood' },
};
const FALLBACK = { wall: '#9a8f80', banner: '#6f6556' };
const F_EN = '"Cormorant Garamond","Times New Roman",serif';
const F_JP = '"Shippori Mincho","Noto Serif JP","Hiragino Mincho ProN","Yu Mincho",serif';
const F_SANS = '"Inter","Helvetica Neue",Arial,sans-serif';
const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'];
const PAINT_TOP = 4.2, PAINT_BOT = 0.118;

function rng(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
const ls = (g, px) => { if ('letterSpacing' in g) g.letterSpacing = `${px}px`; };

// ---- 織物（旗の地）: 経糸緯糸の細かい綾 + 縦方向の襞の陰影 ----
function weave(g, W, H, hex, seed) {
  const r = rng(seed);
  g.fillStyle = hex; g.fillRect(0, 0, W, H);
  for (let y = 0; y < H; y += 3) { g.fillStyle = `rgba(0,0,0,${0.035 + r() * 0.03})`; g.fillRect(0, y, W, 1); }
  for (let x = 0; x < W; x += 3) { g.fillStyle = `rgba(255,255,255,${0.02 + r() * 0.02})`; g.fillRect(x, 0, 1, H); }
  // 襞: 横方向にゆるい明暗（ジオメトリの襞と位相を合わせる: 3山）
  const gr = g.createLinearGradient(0, 0, W, 0);
  for (let k = 0; k <= 12; k++) { const a = Math.sin(k / 12 * Math.PI * 6); gr.addColorStop(k / 12, a > 0 ? `rgba(255,248,235,${a * 0.06})` : `rgba(0,0,0,${-a * 0.12})`); }
  g.fillStyle = gr; g.fillRect(0, 0, W, H);
  // 上下の吊り袋（ロッドを通す袋縫い）
  g.fillStyle = 'rgba(0,0,0,0.18)'; g.fillRect(0, 34, W, 3); g.fillRect(0, H - 40, W, 3);
}

// 縦書き（和文）。長音・ダッシュは縦用に置換
function drawTategaki(g, text, x, y, size, gap = 1.12) {
  const map = { 'ー': '丨', '—': '︱', '–': '︱', '-': '︱', '、': '︑', '。': '︒', '「': '﹁', '」': '﹂' };
  g.textAlign = 'center'; g.textBaseline = 'middle';
  let yy = y;
  for (const ch of text) {
    if (ch === ' ') { yy += size * 0.5; continue; }
    g.fillText(map[ch] || ch, x, yy + size / 2); yy += size * gap;
  }
  return yy;
}

function bannerTexture({ hex, numeral, nameEn, subJp, range, kicker = 'ROOM', seed = 1, anisotropy = 8 }) {
  const W = 512, H = 1536, c = document.createElement('canvas'); c.width = W; c.height = H; const g = c.getContext('2d');
  weave(g, W, H, hex, seed);
  const cream = '#f1e8d6', gold = '#d6b77c';
  // 縁取りの細い金糸
  g.strokeStyle = 'rgba(214,183,124,0.55)'; g.lineWidth = 2; g.strokeRect(26, 62, W - 52, H - 124);
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillStyle = gold; g.font = `600 30px ${F_SANS}`; ls(g, 14); g.fillText(kicker, W / 2 + 7, 150); ls(g, 0);
  g.fillStyle = cream; g.font = `500 ${numeral.length > 3 ? 150 : 210}px ${F_EN}`; g.fillText(numeral, W / 2, 300);
  g.fillStyle = gold; g.fillRect(W / 2 - 60, 425, 120, 3);
  // 縦書きの副題（— の前後で2行=2列にする）
  const parts = String(subJp || '').split(/\s*[—–]\s*/).filter(Boolean);
  g.fillStyle = cream;
  if (parts.length >= 2) {
    g.font = `700 76px ${F_JP}`; drawTategaki(g, parts[0], W / 2 + 62, 490, 76, 1.08);
    g.font = `500 50px ${F_JP}`; drawTategaki(g, parts[1], W / 2 - 66, 560, 50, 1.16);
  } else if (parts.length === 1) { g.font = `700 76px ${F_JP}`; drawTategaki(g, parts[0], W / 2, 490, 76, 1.08); }
  // 英題（下部・字間広め）、期間
  const words = String(nameEn || '').split(' ');
  g.fillStyle = cream; g.font = `500 52px ${F_EN}`; ls(g, 10);
  const lines = words.length > 1 && g.measureText(nameEn).width > W - 90 ? words : [nameEn];
  let y = H - 300 - (lines.length - 1) * 64;
  lines.forEach((l) => { g.fillText(l, W / 2 + 5, y); y += 64; });
  ls(g, 0);
  if (range) { g.fillStyle = gold; g.font = `500 30px ${F_SANS}`; ls(g, 8); g.fillText(range.replace(/—/g, '–'), W / 2 + 4, H - 170); ls(g, 0); }
  g.fillStyle = 'rgba(214,183,124,0.7)'; g.font = `500 22px ${F_SANS}`; ls(g, 10); g.fillText('FLAT TRAIL', W / 2 + 5, H - 112); ls(g, 0);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = anisotropy; return t;
}

// 布の襞＋風の揺れ（頂点シェーダで z 方向に変位。上端は固定＝吊り元からの距離の二乗で振幅）
function clothMaterial(params, uniforms) {
  const m = new THREE.MeshStandardMaterial({ roughness: 0.92, metalness: 0, envMapIntensity: 0.5, ...params });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uTime = uniforms.uTime; sh.uniforms.uPhase = { value: uniforms.phase };
    sh.vertexShader = 'uniform float uTime; uniform float uPhase;\n' + sh.vertexShader.replace('#include <begin_vertex>', `
      vec3 transformed = vec3(position);
      float hang = 1.0 - uv.y; // 0=上端 1=下端
      float fold = sin(uv.x * 18.85) * 0.018;                // 3山の静的な襞
      float wind = sin(uTime * 0.9 + uPhase + uv.y * 2.2) * 0.05 + sin(uTime * 2.3 + uPhase * 1.7 + uv.x * 3.0) * 0.012;
      transformed.z += fold + wind * hang * hang;
      transformed.x += sin(uTime * 0.7 + uPhase) * 0.01 * hang;`);
  };
  m.customProgramCacheKey = () => 'h-cloth';
  return m;
}

export function install(ctx) {
  const museum = ctx?.museum; if (!museum?.exhibits?.length) return {};
  const { scene, renderer, NEWS = [], WINGS = [] } = ctx;
  const root = new THREE.Group(); root.name = 'ultra_h'; scene.add(root);
  const W = museum.hall?.width ?? 10, H = museum.hall?.height ?? 6;
  const aniso = Math.min(8, renderer?.capabilities?.getMaxAnisotropy?.() || 1);
  const disposables = [];
  const keep = (o) => { disposables.push(o); return o; };
  const uniforms = { uTime: { value: 0 } };

  // ---------- 展示室の区間を exhibits から導出（museum_f の配置と独立に頑健） ----------
  const ex = museum.exhibits;
  const rooms = [];
  ex.forEach((e, i) => {
    const wing = e.news?.wing ?? NEWS[i]?.wing;
    const z = e.mesh.getWorldPosition(new THREE.Vector3()).z;
    let r = rooms[rooms.length - 1];
    if (!r || r.wing !== wing) { r = { wing, first: z, last: z, items: [] }; rooms.push(r); }
    r.last = z; r.items.push(e);
  });
  // ゲート位置: museum.gates があれば正、無ければ museum_f の規約（室の先頭展示の ROOM_GAP/2 手前）
  const HALF_GAP = 3.75, PART = 0.36;
  const gateZ = (k) => (k === 0 ? 0 : Math.min(rooms[k - 1].last - 0.5, rooms[k].first + HALF_GAP));
  rooms.forEach((r, k) => {
    r.z0 = gateZ(k) - (k === 0 ? 0.35 : PART);                                 // 入口ポータルの奥側の面
    r.z1 = k === rooms.length - 1 ? r.last - 5 : gateZ(k + 1) + PART;          // 次ゲートの手前面 or アトリウム境界
    r.info = WINGS.find((w) => w.id === r.wing) || {};
    r.paint = ROOM_PAINT[r.wing] || FALLBACK;
  });

  // ---------- 1) ROOM PAINT ----------
  const unit = keep(new THREE.BoxGeometry(1, 1, 1));
  const trimMat = keep(new THREE.MeshStandardMaterial({ color: 0xefe8db, roughness: 0.7 }));
  const railMat = keep(new THREE.MeshStandardMaterial({ color: 0xc9a46a, roughness: 0.34, metalness: 1, envMapIntensity: 1.2 }));
  // 塗装は「平面を重ねる」と展示の壁面要素（光だまり 4mm・キャプション 3mm）と深度が競合するため、
  // museum の側壁メッシュのマテリアルを複製し、ワールドZの室区間×高さ帯で顔料色に塗り替える（ジオメトリ追加ゼロ）。
  const MAXR = 8;
  const uZ0 = { value: new Array(MAXR).fill(-1e6) }, uZ1 = { value: new Array(MAXR).fill(-1e6) };
  const uC = { value: Array.from({ length: MAXR }, () => new THREE.Color(1, 1, 1)) };
  rooms.slice(0, MAXR).forEach((r, k) => { uZ0.value[k] = r.z0; uZ1.value[k] = r.z1; uC.value[k] = new THREE.Color(r.paint.wall); });
  const uBand = { value: new THREE.Vector2(PAINT_BOT, PAINT_TOP) };
  const painted = [];
  (museum.root || scene).traverse((o) => {
    const gp = o.geometry?.parameters;
    if (!o.isMesh || o.geometry?.type !== 'PlaneGeometry' || !gp || gp.width < 40 || Math.abs(gp.height - H) > 0.01) return;
    if (Math.abs(Math.abs(o.position.x) - W / 2) > 0.05) return;
    const base = o.material, m = keep(base.clone());
    m.onBeforeCompile = (sh) => {
      Object.assign(sh.uniforms, { uZ0, uZ1, uC, uBand });
      sh.vertexShader = 'varying vec3 vHW;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\n  vHW = (modelMatrix * vec4(transformed, 1.0)).xyz;');
      sh.fragmentShader = `varying vec3 vHW; uniform float uZ0[${MAXR}]; uniform float uZ1[${MAXR}]; uniform vec3 uC[${MAXR}]; uniform vec2 uBand;\n` +
        sh.fragmentShader.replace('#include <map_fragment>', `#include <map_fragment>
        {
          vec3 paint = vec3(1.0); float on = 0.0;
          for (int i = 0; i < ${MAXR}; i++) { if (vHW.z < uZ0[i] && vHW.z > uZ1[i]) { paint = uC[i]; on = 1.0; } }
          on *= step(uBand.x, vHW.y) * step(vHW.y, uBand.y);
          // 漆喰の凹凸（map の輝度ゆらぎ）を塗装面にも 40% だけ残す＝ローラー塗りのマット感
          float grain = dot(diffuseColor.rgb, vec3(0.333)) / 0.62;
          diffuseColor.rgb = mix(diffuseColor.rgb, paint * mix(1.0, grain, 0.4), on);
        }`);
    };
    m.customProgramCacheKey = () => 'h-roompaint';
    o.material = m; painted.push({ o, base });
  });
  rooms.forEach((r) => {
    const len = Math.abs(r.z0 - r.z1), zc = (r.z0 + r.z1) / 2;
    [-1, 1].forEach((s) => {
      // ピクチャーレール（漆喰色の竿縁＋真鍮の細い吊り竿）= 塗装帯の上端の見切り
      const rail = new THREE.Mesh(unit, trimMat); rail.scale.set(0.035, 0.07, len); rail.position.set(s * (W / 2 - 0.0175), PAINT_TOP + 0.035, zc); rail.castShadow = true; root.add(rail);
      const rod = new THREE.Mesh(unit, railMat); rod.scale.set(0.012, 0.012, len); rod.position.set(s * (W / 2 - 0.045), PAINT_TOP + 0.02, zc); root.add(rod);
      // 端部の見切り（縦）
      [r.z0, r.z1].forEach((zz) => { const v = new THREE.Mesh(unit, trimMat); v.scale.set(0.03, PAINT_TOP - PAINT_BOT, 0.05); v.position.set(s * (W / 2 - 0.015), (PAINT_TOP + PAINT_BOT) / 2, zz); root.add(v); });
    });
  });

  // ---------- 2) LABEL BOARD（キャプション背面の生成りボード） ----------
  const boardMat = keep(new THREE.MeshStandardMaterial({ color: 0xf2ece0, roughness: 0.82 }));
  const shadowMat = keep(new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.16, depthWrite: false }));
  ex.forEach((e) => {
    const g = e.mesh;
    const label = g.children.find((o) => o.isMesh && o.renderOrder === 2 && o.geometry?.type === 'PlaneGeometry' && (o.geometry.parameters?.width ?? 9) < 1.4);
    const w = (label?.geometry.parameters.width ?? 0.9) + 0.14, h = (label?.geometry.parameters.height ?? 0.9) + 0.14;
    const pos = label ? label.position.clone() : new THREE.Vector3(1.3, 1.72, -0.547);
    const board = new THREE.Mesh(keep(new THREE.BoxGeometry(w, h, 0.004)), boardMat);
    board.position.set(pos.x, pos.y, pos.z - 0.003); board.receiveShadow = true; g.add(board);
    const sh = new THREE.Mesh(keep(new THREE.PlaneGeometry(w + 0.03, h + 0.03)), shadowMat);
    sh.position.set(pos.x + 0.012, pos.y - 0.018, pos.z - 0.0015); g.add(sh);
  });

  // ---------- 3) BANNERS ----------
  const rodGeo = keep(new THREE.CylinderGeometry(0.014, 0.014, 1.0, 12)); rodGeo.rotateZ(Math.PI / 2);
  const capGeo = keep(new THREE.SphereGeometry(0.024, 12, 8));
  const wireGeo = keep(new THREE.CylinderGeometry(0.0025, 0.0025, 1, 4));
  const wireMat = keep(new THREE.MeshStandardMaterial({ color: 0x3a3631, roughness: 0.5, metalness: 0.6 }));
  const banners = [];
  function hangBanner(tex, backHex, x, z, yTop, w, h, yaw, phase) {
    const grp = new THREE.Group(); grp.position.set(x, yTop, z); grp.rotation.y = yaw; root.add(grp);
    const geo = keep(new THREE.PlaneGeometry(w, h, 6, 18)); geo.translate(0, -h / 2, 0);
    const front = new THREE.Mesh(geo, keep(clothMaterial({ map: tex }, { ...uniforms, phase })));
    front.castShadow = true; front.receiveShadow = true; grp.add(front);
    const backTex = keep((() => { const c = document.createElement('canvas'); c.width = 128; c.height = 384; weave(c.getContext('2d'), 128, 384, backHex, 7); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; })());
    const back = new THREE.Mesh(geo, keep(clothMaterial({ map: backTex, side: THREE.BackSide }, { ...uniforms, phase })));
    grp.add(back);
    // 真鍮ロッド（上下）＋ 吊りワイヤ
    [0.0, -h].forEach((yy, k) => {
      const rod = new THREE.Mesh(rodGeo, railMat); rod.scale.set(w + 0.08, 1, 1); rod.position.set(0, yy - (k ? 0.0 : 0.015), k ? 0.01 : 0); grp.add(rod);
      if (!k) [-1, 1].forEach((s) => { const cp = new THREE.Mesh(capGeo, railMat); cp.position.set(s * (w / 2 + 0.05), -0.015, 0); grp.add(cp); });
    });
    const wireLen = H - yTop + 0.05;
    [-1, 1].forEach((s) => { const wr = new THREE.Mesh(wireGeo, wireMat); wr.scale.y = wireLen; wr.position.set(s * w * 0.42, wireLen / 2, 0); grp.add(wr); });
    banners.push({ grp, bottomRod: grp.children[2] });
    return grp;
  }
  rooms.forEach((r, k) => {
    const tex = keep(bannerTexture({ hex: r.paint.banner, numeral: ROMAN[k] || String(k + 1), nameEn: r.info.name || '', subJp: r.info.sub || '', range: r.info.range || '', seed: 101 + k, anisotropy: aniso }));
    const zb = r.z0 - 1.1;
    [-1, 1].forEach((s) => hangBanner(tex, r.paint.banner, s * 3.35, zb, H - 0.35, 0.86, 2.58, -s * 0.2, k * 1.7 + (s > 0 ? 0.9 : 0)));
  });
  // ---------- 4) LOBBY BANNERS ----------
  const n = NEWS.length || ex.length;
  const lobbyTex = keep(bannerTexture({ hex: '#2c2925', numeral: '50', kicker: 'DAYS OF AI', nameEn: 'THE MUSEUM OF AI HEADLINES', subJp: 'AIの五十日 — 二〇二六 晩夏から秋', range: `08.12 — 10.01 · ${n}`, seed: 77, anisotropy: aniso }));
  [-1, 1].forEach((s) => hangBanner(lobbyTex, '#2c2925', s * 3.5, 4.0, H - 0.25, 1.0, 3.0, -s * 0.32, s * 2.1));

  // ---------- 5) THRESHOLD（ポータル床の真鍮見切り） ----------
  rooms.forEach((r) => [0.36, -0.36].forEach((dz) => {
    const th = new THREE.Mesh(unit, railMat); th.scale.set(3.4, 0.006, 0.05); th.position.set(0, 0.003, gateZ(rooms.indexOf(r)) + dz); root.add(th);
  }));

  if (renderer?.shadowMap) renderer.shadowMap.needsUpdate = true;
  let q = ctx.quality || 'high';
  return {
    rooms,
    update(t) { uniforms.uTime.value = t; },
    setQuality(nq) { q = nq; banners.forEach((b) => b.grp.traverse((o) => { if (o.isMesh) o.castShadow = q !== 'low' && o.material?.map != null; })); },
    dispose() { painted.forEach(({ o, base }) => { o.material = base; }); scene.remove(root); disposables.forEach((d) => d.dispose?.()); },
  };
}
