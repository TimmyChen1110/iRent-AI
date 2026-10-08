// iRent 3D 車輛檢視器（App 內 WKWebView 載入，所有檔案皆隨 App 打包，不連外網）。
// App → JS：window.iRent3D.apply(config)；JS → App：webkit.messageHandlers.irent3d.postMessage({type, ...})
//   type: ready | error | pick {part, region} | marker {id}
// 座標：車頭 +X、車輛右側 +Z、地面 y=0（與 tools/vehicle3d/build_models.mjs 一致）。
import * as THREE from 'three';
import { GLTFLoader } from './GLTFLoader.js';
import { OrbitControls } from './OrbitControls.js';
import { RoomEnvironment } from './RoomEnvironment.js';

const post = (m) => {
  try { window.webkit.messageHandlers.irent3d.postMessage(m); }
  catch { console.log('[irent3d]', JSON.stringify(m)); document.title = JSON.stringify(m); }   // 瀏覽器預覽：結果寫進 title 方便自動化驗證
};

// ---------- 車身分區 ----------
// 區域 id 與後端 body_regions.py / fleet-ops-center HotspotLocation 同一組；錨點以 sedan（4.6 m）為基準，依車長縮放。
const ANCHORS = {
  'front-bumper': [2.32, 0.46, 0], 'rear-bumper': [-2.32, 0.52, 0], 'hood': [1.65, 0.93, 0], 'roof': [-0.15, 1.47, 0],
  'windshield': [0.8, 1.2, 0],
  'left-front-door': [0.45, 0.68, -0.9], 'right-front-door': [0.45, 0.68, 0.9],
  'left-rear-door': [-0.6, 0.68, -0.9], 'right-rear-door': [-0.6, 0.68, 0.9],
  'left-front-fender': [1.6, 0.74, -0.86], 'right-front-fender': [1.6, 0.74, 0.86],
  'left-rear-quarter': [-1.65, 0.76, -0.86], 'right-rear-quarter': [-1.65, 0.76, 0.86],
};
const PART_REGIONS = {
  front: ['front-bumper', 'hood', 'windshield'], rear: ['rear-bumper'], roof: ['roof'],
  left: ['left-front-door', 'left-rear-door', 'left-front-fender', 'left-rear-quarter'],
  right: ['right-front-door', 'right-rear-door', 'right-front-fender', 'right-rear-quarter'],
};
// 鏡頭方向：部位與拍攝角度（左前＝車輛左前角＝-Z、+X）
const VIEWS = {
  front: [1, 0.32, 0], rear: [-1, 0.32, 0], left: [0, 0.32, -1], right: [0, 0.32, 1], roof: [0.35, 1.7, 0.3],
  FRONT_LEFT: [1, 0.36, -1], FRONT_RIGHT: [1, 0.36, 1], REAR_LEFT: [-1, 0.36, -1], REAR_RIGHT: [-1, 0.36, 1],
  INTERIOR: [0.15, 1.25, -0.9], overview: [1, 0.42, 0.9],
};

// ---------- 場景 ----------
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa3b2, 0.55));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(3, 6, 4);
scene.add(sun);

const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.enablePan = false;
controls.minDistance = 4.2;
controls.maxDistance = 11;
controls.maxPolarAngle = Math.PI * 0.49;
controls.rotateSpeed = 0.8;
controls.target.set(0, 0.62, 0);

// 地面接觸陰影（徑向漸層貼圖，手機友善，不開即時陰影）
function shadowTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(128, 128, 10, 128, 128, 128);
  grd.addColorStop(0, 'rgba(0,0,0,0.55)'); grd.addColorStop(0.55, 'rgba(0,0,0,0.25)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: shadowTexture(), transparent: true, depthWrite: false }));
shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.002;
scene.add(shadow);

// 拍攝站位提示（guide 模式）：地面圓盤 + 指向車輛的箭頭
const standGroup = new THREE.Group();
const standDisc = new THREE.Mesh(new THREE.RingGeometry(0.22, 0.32, 40), new THREE.MeshBasicMaterial({ color: 0x2f6bed, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false }));
standDisc.rotation.x = -Math.PI / 2;
const standDot = new THREE.Mesh(new THREE.CircleGeometry(0.12, 32), new THREE.MeshBasicMaterial({ color: 0x2f6bed, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
standDot.rotation.x = -Math.PI / 2;
const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.28, 3), new THREE.MeshBasicMaterial({ color: 0x2f6bed }));
arrow.rotation.z = -Math.PI / 2; arrow.position.set(0.5, 0.02, 0);
const standArrowPivot = new THREE.Group(); standArrowPivot.add(arrow);
standGroup.add(standDisc, standDot, standArrowPivot);
standGroup.visible = false;
scene.add(standGroup);

const markerGroup = new THREE.Group(); scene.add(markerGroup);
const doneGroup = new THREE.Group(); scene.add(doneGroup);
const pickRing = new THREE.Mesh(new THREE.RingGeometry(0.07, 0.11, 32), new THREE.MeshBasicMaterial({ color: 0x2f6bed, transparent: true, opacity: 0.95, side: THREE.DoubleSide, depthTest: false }));
pickRing.renderOrder = 10; pickRing.visible = false; scene.add(pickRing);

let car = null, carStyle = null, scaleX = 1, scaleZ = 1, roofTop = 1.45, halfLen = 2.3;
let config = {};
let lastFocusToken = null;
const loader = new GLTFLoader();
const modelCache = {};

function anchor(region) {
  const a = ANCHORS[region];
  return a ? new THREE.Vector3(a[0] * scaleX, a[1], a[2] * scaleZ) : null;
}

function plateTexture(text) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, 512, 128);
  g.strokeStyle = '#1a1a1a'; g.lineWidth = 8; g.strokeRect(6, 6, 500, 116);
  g.fillStyle = '#111'; g.font = 'bold 84px "Helvetica Neue", Arial, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text || '', 256, 70);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}

function applyPlate(text) {
  if (!car) return;
  car.traverse((o) => {
    if (!o.isMesh || !/^plate_(front|rear)/.test(o.name)) return;
    const tex = plateTexture(text);
    const front = o.name.startsWith('plate_front');
    // BoxGeometry 的 ±X 面（材質 index 0/1）才是車牌正面；其他面維持白色
    const blank = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.5 });
    const face = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.45 });
    if (front) { tex.wrapS = THREE.RepeatWrapping; tex.repeat.x = 1; }
    else { tex.wrapS = THREE.RepeatWrapping; tex.repeat.x = 1; }
    o.material = [front ? face : blank, front ? blank : face, blank, blank, blank, blank];
    if (o.geometry.groups.length === 0) {
      // GLB 匯出後合併成單一群組：依法向量重建 6 個群組
      const g = o.geometry, n = g.attributes.normal, idx = g.index;
      const groups = [[], [], [], [], [], []];
      for (let i = 0; i < idx.count; i += 3) {
        const vi = idx.getX(i);
        const nx = n.getX(vi), ny = n.getY(vi), nz = n.getZ(vi);
        const f = Math.abs(nx) > 0.9 ? (nx > 0 ? 0 : 1) : Math.abs(ny) > 0.9 ? (ny > 0 ? 2 : 3) : (nz > 0 ? 4 : 5);
        groups[f].push(idx.getX(i), idx.getX(i + 1), idx.getX(i + 2));
      }
      const all = []; g.clearGroups();
      groups.forEach((tri, f) => { if (tri.length) { g.addGroup(all.length, tri.length, f); all.push(...tri); } });
      g.setIndex(all);
    }
  });
}

function applyPaint(hex) {
  if (!car || !hex) return;
  car.traverse((o) => { if (o.isMesh && o.material && o.material.name === 'paint') o.material.color.set(hex); });
}

async function loadModel(style) {
  if (carStyle === style && car) return;
  const url = `./car_${style === 'hatchback' ? 'hatchback' : 'sedan'}.glb`;
  const gltf = modelCache[url] || (modelCache[url] = await loader.loadAsync(url));
  if (car) scene.remove(car);
  car = gltf.scene;
  carStyle = style;
  scene.add(car);
  const box = new THREE.Box3().setFromObject(car);
  const size = box.getSize(new THREE.Vector3());
  halfLen = size.x / 2; scaleX = size.x / 4.66; scaleZ = size.z / 1.82;
  roofTop = box.max.y;
  shadow.scale.set(size.x * 1.35, size.z * 1.9, 1);
  car.traverse((o) => {
    if (o.isMesh && o.material && o.material.name === 'glass') { o.material.transparent = true; o.material.opacity = 0.9; }
    if (o.isMesh && o.material && o.material.name === 'paint') { o.material.envMapIntensity = 1.15; }
  });
}

// ---------- 鏡頭動畫 ----------
let tween = null;
function focus(view, immediate = false) {
  const dir = VIEWS[view] || VIEWS.overview;
  const d = new THREE.Vector3(...dir).normalize();
  const dist = view === 'roof' ? 6.8 : view === 'INTERIOR' ? 6.2 : view === 'overview' ? 8.2 : 7.0;
  const to = d.multiplyScalar(dist).add(new THREE.Vector3(0, 0.62, 0));
  if (immediate) { camera.position.copy(to); controls.update(); return; }
  tween = { from: camera.position.clone(), to, t: 0 };
}

// ---------- 標記 ----------
const SEVERITY_COLOR = { high: 0xd92d20, medium: 0xe8590c, low: 0xf59f00, existing: 0x667085 };
function markerSprite(color, label) {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,0.95)'; g.beginPath(); g.arc(64, 64, 54, 0, Math.PI * 2); g.fill();
  g.fillStyle = '#' + color.toString(16).padStart(6, '0'); g.beginPath(); g.arc(64, 64, 44, 0, Math.PI * 2); g.fill();
  g.fillStyle = '#fff'; g.font = 'bold 60px Arial'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(label, 64, 68);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true }));
  s.renderOrder = 20; s.scale.set(0.4, 0.4, 1);
  return s;
}

function setMarkers(markers = []) {
  markerGroup.clear();
  const used = {};
  for (const m of markers) {
    const p = anchor(m.region);
    if (!p) continue;              // 沒有可確認的區域 → 不畫（不產生假標記）
    const k = used[m.region] = (used[m.region] || 0) + 1;
    const s = markerSprite(SEVERITY_COLOR[m.severity] || SEVERITY_COLOR.medium, m.kind === 'existing' ? '·' : '!');
    const outward = p.clone().setY(0).normalize().multiplyScalar(0.1);
    s.position.copy(p).add(outward).add(new THREE.Vector3(0, 0.3 * (k - 1), (k - 1) % 2 ? 0.25 : -0.25 * Math.sign(k - 1)));
    s.userData = { markerId: m.id };
    markerGroup.add(s);
  }
}

function setGuide(guide) {
  doneGroup.clear();
  standGroup.visible = false;
  if (!guide) return;
  for (const code of guide.done || []) {
    const dir = VIEWS[code]; if (!dir || code === 'INTERIOR') continue;
    const s = markerSprite(0x12a150, '✓');
    s.material.depthTest = true;
    s.scale.set(0.3, 0.3, 1);
    s.position.set(dir[0] * (halfLen + 0.55), 0.2, dir[2] * 1.45);
    doneGroup.add(s);
  }
  const cur = guide.current && VIEWS[guide.current];
  if (cur && guide.current !== 'INTERIOR') {
    const d = new THREE.Vector3(cur[0], 0, cur[2]).normalize();
    standGroup.position.set(d.x * (halfLen + 0.5), 0.01, d.z * 1.45);
    standArrowPivot.rotation.y = Math.atan2(d.z, -d.x);
    standGroup.visible = true;
  }
}

// ---------- 點選 ----------
const raycaster = new THREE.Raycaster();
const ndc = new THREE.Vector2();
let down = null;
canvas.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; stopAuto(); });
canvas.addEventListener('pointerup', (e) => {
  if (!down) return;
  const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
  const quick = performance.now() - down.t < 450;
  down = null;
  if (moved > 8 || !quick) return;
  const r = canvas.getBoundingClientRect();
  ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const mk = raycaster.intersectObjects(markerGroup.children, false)[0];
  if (mk) { post({ type: 'marker', id: mk.object.userData.markerId }); return; }
  if (!car || config.selectable === false) return;
  const hit = raycaster.intersectObject(car, true)[0];
  if (!hit) return;
  const p = hit.point;
  const part = p.y > roofTop - 0.16 ? 'roof' : p.x > halfLen * 0.62 ? 'front' : p.x < -halfLen * 0.62 ? 'rear' : p.z >= 0 ? 'right' : 'left';
  let region = null, best = Infinity;
  for (const id of PART_REGIONS[part]) { const a = anchor(id); const d = a.distanceTo(p); if (d < best) { best = d; region = id; } }
  pickRing.position.copy(p).add(hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld).multiplyScalar(0.01) : new THREE.Vector3());
  pickRing.lookAt(p.clone().add(hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3(0, 1, 0)));
  pickRing.visible = true;
  if (config.focusOnPick !== false) focus(part);
  post({ type: 'pick', part, region });
});

let autoTimer = null;
function stopAuto() { controls.autoRotate = false; clearTimeout(autoTimer); if (config.autoRotate) autoTimer = setTimeout(() => { controls.autoRotate = true; }, 6000); }

// ---------- App API ----------
window.iRent3D = {
  async apply(next) {
    config = { ...config, ...next };
    try {
      await loadModel(config.style || 'sedan');
      applyPlate(config.plate);
      applyPaint(config.paint);
      controls.autoRotate = !!config.autoRotate;
      controls.autoRotateSpeed = 0.9;
      setMarkers(config.markers || []);
      setGuide(config.guide || null);
      if (config.clearPick) pickRing.visible = false;
      const token = config.focusToken ?? config.focus;
      if (config.focus && token !== lastFocusToken) { focus(config.focus, lastFocusToken === null); lastFocusToken = token; }
      else if (lastFocusToken === null) { focus('overview', true); lastFocusToken = '__init'; }
      if (!this._ready) { this._ready = true; post({ type: 'ready', style: carStyle }); }
    } catch (err) {
      post({ type: 'error', reason: 'load', detail: String(err && err.message || err) });
    }
  },
};

function resize() {
  const w = canvas.clientWidth || window.innerWidth, h = canvas.clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.05);
  if (tween) {
    tween.t = Math.min(1, tween.t + dt / 0.7);
    const k = 1 - Math.pow(1 - tween.t, 3);
    // 以球面插值移動，避免穿過車身
    const a = tween.from.clone().sub(controls.target), b = tween.to.clone().sub(controls.target);
    const ra = a.length(), rb = b.length();
    const v = new THREE.Vector3().copy(a.normalize()).lerp(b.normalize(), k).normalize().multiplyScalar(ra + (rb - ra) * k);
    camera.position.copy(controls.target).add(v);
    if (tween.t >= 1) tween = null;
  }
  const pulse = 1 + Math.sin(performance.now() / 260) * 0.12;
  standDisc.scale.setScalar(pulse);
  controls.update();
  renderer.render(scene, camera);
});

// App 內：通知 Swift 模組已就緒，由 App 送 config；獨立開啟（瀏覽器預覽）時自動套用預設
if (window.webkit?.messageHandlers?.irent3d) {
  post({ type: 'boot' });
} else {
  const q = new URLSearchParams(location.search);
  window.iRent3D.apply({ style: q.get('style') || 'sedan', plate: q.get('plate') || 'RFY-1753', autoRotate: q.has('spin'),
    focus: q.get('focus') || undefined, guide: q.get('guide') ? { current: q.get('guide'), done: (q.get('done') || '').split(',').filter(Boolean) } : null,
    markers: q.get('markers') ? q.get('markers').split(',').map((r, i) => ({ id: 'm' + i, region: r, severity: i ? 'medium' : 'high' })) : [] })
    .then(() => {
      // ?tap=x,y（0–1 畫面比例）：模擬點擊，驗證 raycasting 分區
      if (!q.get('tap') && !q.get('tapMarker')) return;
      let [fx, fy] = (q.get('tap') || '0,0').split(',').map(Number);
      if (q.get('tapMarker')) {
        const m = markerGroup.children.find((c) => c.userData.markerId === q.get('tapMarker'));
        if (m) { camera.updateMatrixWorld(); const v = m.position.clone().project(camera); fx = (v.x + 1) / 2; fy = (1 - v.y) / 2; }
      }
      setTimeout(() => {
        const r = canvas.getBoundingClientRect();
        const ev = (type) => new PointerEvent(type, { clientX: r.left + r.width * fx, clientY: r.top + r.height * fy, bubbles: true });
        canvas.dispatchEvent(ev('pointerdown')); canvas.dispatchEvent(ev('pointerup'));
      }, 1500);
    });
}
