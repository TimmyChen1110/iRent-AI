// 產生 App 用的 3D 車輛模型（GLB）：白色四門轎車（sedan，對應 TOYOTA ALTIS HYBRID）與掀背車（hatchback，對應 Prius c / Yaris）。
//
// 為什麼自己產生：專案內沒有授權明確的 Altis 模型；舊版 Kenney 掀背車已隨舊 Dashboard 移除。
// 以 three.js（MIT，與 fleet-ops-center 同版 0.186）在 Node 端用程式建模、GLTFExporter 匯出，模型完全自有、無授權疑慮。
// 與實車差異（內部紀錄）：比例參考 Altis（4.63 × 1.78 × 1.435 m），輪廓為簡化造型，非原廠 CAD；燈組、水箱罩、輪框為示意。
//
// 座標：glTF Y-up；車頭朝 +X、車輛右側 = +Z、地面 y = 0、車身中心在原點。網格以部位命名（body_*, glass_*, wheel_*, plate_front/rear …），
// App 端以「擊中點座標」分區（車頭／車尾／左／右／車頂），不依賴網格名稱，換模型也可用。
//
// 用法（repo 根目錄）：node frontend-user/irent-app/tools/vehicle3d/build_models.mjs
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const THREE_DIR = resolve(HERE, '../../../../fleet-ops-center/node_modules/three');
const THREE = await import(`${THREE_DIR}/build/three.module.js`);
const { GLTFExporter } = await import(`${THREE_DIR}/examples/jsm/exporters/GLTFExporter.js`);
const { mergeVertices } = await import(`${THREE_DIR}/examples/jsm/utils/BufferGeometryUtils.js`);

// GLTFExporter（binary）用 FileReader 讀 Blob；Node 沒有 → 最小 polyfill
globalThis.FileReader = class {
  readAsArrayBuffer(blob) { blob.arrayBuffer().then((b) => { this.result = b; this.onloadend?.({ target: this }); this.onload?.({ target: this }); }); }
  readAsDataURL(blob) { blob.arrayBuffer().then((b) => { this.result = `data:${blob.type};base64,${Buffer.from(b).toString('base64')}`; this.onloadend?.({ target: this }); this.onload?.({ target: this }); }); }
};

const OUT = resolve(HERE, '../../irent-app/Vehicle3D');
mkdirSync(OUT, { recursive: true });

// ---------- 材質 ----------
const M = {
  paint: new THREE.MeshPhysicalMaterial({ name: 'paint', color: 0xf3f4f6, roughness: 0.28, metalness: 0.12, clearcoat: 1, clearcoatRoughness: 0.08 }),
  glass: new THREE.MeshPhysicalMaterial({ name: 'glass', color: 0x1b2430, roughness: 0.06, metalness: 0.3, clearcoat: 1, clearcoatRoughness: 0.02 }),
  trim: new THREE.MeshStandardMaterial({ name: 'trim', color: 0x15181d, roughness: 0.8, metalness: 0.1 }),
  chrome: new THREE.MeshStandardMaterial({ name: 'chrome', color: 0xd3d8e0, roughness: 0.18, metalness: 1 }),
  tire: new THREE.MeshStandardMaterial({ name: 'tire', color: 0x111316, roughness: 0.92, metalness: 0 }),
  rim: new THREE.MeshStandardMaterial({ name: 'rim', color: 0xb4bbc6, roughness: 0.28, metalness: 0.95 }),
  headlight: new THREE.MeshStandardMaterial({ name: 'headlight', color: 0xeef4ff, emissive: 0xc8dcff, emissiveIntensity: 0.9, roughness: 0.1, metalness: 0.2 }),
  taillight: new THREE.MeshStandardMaterial({ name: 'taillight', color: 0xb3162b, emissive: 0xff2b44, emissiveIntensity: 0.7, roughness: 0.2 }),
  amber: new THREE.MeshStandardMaterial({ name: 'amber', color: 0xf0a43a, emissive: 0xf59e0b, emissiveIntensity: 0.4, roughness: 0.3 }),
  plate: new THREE.MeshStandardMaterial({ name: 'plate', color: 0xffffff, roughness: 0.5, metalness: 0 }),
};

// ---------- 車型參數 ----------
// body: 車身側面輪廓（x 長、y 高），底緣在輪拱處挖圓弧；cabin: 玻璃車廂輪廓；roof: 車頂鋼板範圍
const STYLES = {
  sedan: {
    length: 4.6, width: 1.78, wheelR: 0.33, wheelX: [1.38, -1.36], track: 0.79,
    body: [
      [-2.0, 0.27], [-2.24, 0.31], [-2.31, 0.48], [-2.31, 0.74], [-2.25, 0.9], [-2.1, 0.98],
      [-1.45, 1.0], [-1.2, 1.0], [0.95, 0.99], [1.25, 0.96], [1.75, 0.88], [2.12, 0.79],
      [2.27, 0.66], [2.31, 0.5], [2.27, 0.33], [2.0, 0.27],
    ],
    cabin: [[-1.48, 0.97], [-0.98, 1.37], [-0.55, 1.445], [0.22, 1.445], [0.55, 1.4], [1.08, 0.97]],
    roof: [-0.62, 0.3], cabinWidth: 1.46,
    pillars: [1.0, -0.05, -1.33], doorSeams: [0.98, -0.05, -1.12], handles: [0.38, -0.7],
  },
  hatchback: {
    length: 4.0, width: 1.7, wheelR: 0.31, wheelX: [1.25, -1.25], track: 0.75,
    body: [
      [-1.75, 0.27], [-1.96, 0.31], [-2.02, 0.48], [-2.02, 0.8], [-1.98, 0.98], [-1.88, 1.03],
      [-1.2, 1.03], [0.85, 1.0], [1.15, 0.95], [1.6, 0.86], [1.9, 0.76],
      [2.0, 0.62], [2.02, 0.48], [1.98, 0.33], [1.75, 0.27],
    ],
    cabin: [[-1.9, 1.0], [-1.72, 1.36], [-1.45, 1.47], [0.15, 1.47], [0.5, 1.4], [1.0, 1.0]],
    roof: [-1.55, 0.2], cabinWidth: 1.4,
    pillars: [0.95, -0.12, -1.55], doorSeams: [0.92, -0.12, -1.18], handles: [0.3, -0.75],
  },
};

function shapeFrom(points) {
  const s = new THREE.Shape();
  points.forEach(([x, y], i) => (i === 0 ? s.moveTo(x, y) : s.lineTo(x, y)));
  s.closePath();
  return s;
}

/** 車身側面輪廓（底緣含兩個輪拱）。點序：從前保桿底沿頂部到後保桿底，再沿底緣（挖輪拱）回到前方。 */
function bodyShape(st) {
  const top = st.body;
  const s = new THREE.Shape();
  // 底緣從後往前：後保桿底 → 後輪拱 → 前輪拱 → 前保桿底
  const [fx, rx] = st.wheelX;
  const archR = st.wheelR + 0.06;
  const cy = st.wheelR;
  s.moveTo(top[0][0], top[0][1]);
  for (let i = 1; i < top.length; i++) s.lineTo(top[i][0], top[i][1]);
  // 回到底緣（top 最後一點在前保桿底），往後走
  s.lineTo(fx + archR, 0.27);
  s.absarc(fx, cy, archR, 0, Math.PI, false);
  s.lineTo(rx + archR, 0.27);
  s.absarc(rx, cy, archR, 0, Math.PI, false);
  s.lineTo(top[0][0], top[0][1]);
  return s;
}

function extrudeCentered(shape, width, bevel, segs = 6, curveSegments = 24) {
  const depth = width - 2 * bevel;
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel * 0.75, bevelSegments: segs, curveSegments });
  g.translate(0, 0, -depth / 2);
  g.computeVertexNormals();
  return g;
}

function mesh(name, geo, mat, pos = [0, 0, 0], rot = [0, 0, 0]) {
  const m = new THREE.Mesh(geo, mat);
  m.name = name;
  m.position.set(...pos);
  m.rotation.set(...rot);
  return m;
}

function wheel(name, x, y, z, r, side) {
  const g = new THREE.Group();
  g.name = name;
  const tire = mesh(`${name}_tire`, new THREE.CylinderGeometry(r, r, 0.22, 40, 1), M.tire, [0, 0, 0], [Math.PI / 2, 0, 0]);
  const sidewall = mesh(`${name}_sidewall`, new THREE.TorusGeometry(r * 0.82, r * 0.16, 12, 40), M.tire, [0, 0, side * 0.1]);
  const rim = mesh(`${name}_rim`, new THREE.CylinderGeometry(r * 0.68, r * 0.68, 0.05, 36), M.rim, [0, 0, side * 0.1], [Math.PI / 2, 0, 0]);
  const hub = mesh(`${name}_hub`, new THREE.CylinderGeometry(r * 0.16, r * 0.16, 0.06, 20), M.chrome, [0, 0, side * 0.13], [Math.PI / 2, 0, 0]);
  g.add(tire, sidewall, rim, hub);
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * Math.PI * 2;
    const spoke = mesh(`${name}_spoke${i}`, new THREE.BoxGeometry(r * 0.12, r * 0.55, 0.035), M.chrome, [Math.sin(a) * r * 0.36, Math.cos(a) * r * 0.36, side * 0.125], [0, 0, -a]);
    g.add(spoke);
  }
  g.position.set(x, y, z);
  return g;
}

function buildCar(styleName) {
  const st = STYLES[styleName];
  const L = st.length, W = st.width, half = W / 2;
  const car = new THREE.Group();
  car.name = `irent_${styleName}`;

  // 車身（白色烤漆）。倒角會讓外緣比輪廓多出 bevelSize，前後零件一律以實際包圍盒定位。
  const shell = mesh('body_shell', extrudeCentered(bodyShape(st), W, 0.14, 8, 20), M.paint);
  car.add(shell);
  shell.geometry.computeBoundingBox();
  const bb = shell.geometry.boundingBox;
  // 玻璃車廂（略窄，形成肩線）
  car.add(mesh('glass_cabin', extrudeCentered(shapeFrom(st.cabin), st.cabinWidth, 0.09, 5, 12), M.glass));
  // 車頂鋼板
  const [r0, r1] = st.roof;
  const roofTop = Math.max(...st.cabin.map((p) => p[1]));
  car.add(mesh('body_roof', new THREE.BoxGeometry(r1 - r0, 0.035, st.cabinWidth - 0.1), M.paint, [(r0 + r1) / 2, roofTop + 0.005, 0]));
  // 窗框與 A/B/C 柱（黑色飾條）
  const sideZ = st.cabinWidth / 2 + 0.004;
  for (const s of [-1, 1]) {
    // B 柱（前後門窗之間）
    car.add(mesh(`trim_pillar_B_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.075, 0.4, 0.012), M.trim, [st.pillars[1] - 0.03, 1.17, s * sideZ]));
    // 窗沿鍍鉻
    car.add(mesh(`trim_beltline_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(st.cabin[st.cabin.length - 1][0] - st.cabin[0][0] - 0.35, 0.022, 0.012), M.chrome,
      [(st.cabin[st.cabin.length - 1][0] + st.cabin[0][0]) / 2 - 0.05, 0.995, s * (st.cabinWidth / 2 + 0.003)]));
    // 車門縫
    const doorZ = s * (half + 0.0015);
    st.doorSeams.forEach((dx, i) => car.add(mesh(`seam_${i}_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.008, 0.6, 0.004), M.trim, [dx, 0.66, doorZ])));
    car.add(mesh(`seam_bottom_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(st.doorSeams[0] - st.doorSeams[2], 0.008, 0.004), M.trim, [(st.doorSeams[0] + st.doorSeams[2]) / 2, 0.38, doorZ]));
    // 門把
    st.handles.forEach((hx, i) => car.add(mesh(`handle_${i}_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.17, 0.035, 0.03), M.chrome, [hx, 0.87, s * (half + 0.012)])));
    // 後照鏡
    const mx = st.cabin[st.cabin.length - 1][0] - 0.12;
    car.add(mesh(`mirror_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.18, 0.1, 0.12), M.paint, [mx, 1.04, s * (half + 0.03)]));
    car.add(mesh(`mirror_glass_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.01, 0.075, 0.1), M.trim, [mx - 0.09, 1.04, s * (half + 0.035)]));
    // 側方向燈（葉子板）
    car.add(mesh(`side_marker_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.08, 0.025, 0.01), M.amber, [st.wheelX[0] + 0.45, 0.82, s * (half + 0.002)]));
    // 輪眉（黑色塑件）
    for (const wx of st.wheelX) {
      const arch = new THREE.TorusGeometry(st.wheelR + 0.07, 0.025, 8, 32, Math.PI);
      car.add(mesh(`arch_${wx > 0 ? 'F' : 'R'}_${s > 0 ? 'R' : 'L'}`, arch, M.trim, [wx, st.wheelR, s * (half + 0.0)]));
    }
    // 輪胎
    for (const wx of st.wheelX) car.add(wheel(`wheel_${wx > 0 ? 'F' : 'R'}${s > 0 ? 'R' : 'L'}`, wx, st.wheelR, s * (st.track + 0.005), st.wheelR, s));
  }

  const front = bb.max.x;
  const rear = bb.min.x;
  // 頭燈（左右）、日行燈條、水箱罩、下進氣、前車牌
  for (const s of [-1, 1]) {
    car.add(mesh(`headlight_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.3, 0.075, 0.42), M.headlight, [front - 0.1, 0.72, s * (half - 0.3)], [0, s * 0.28, -0.3]));
    car.add(mesh(`taillight_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.1, 0.11, 0.44), M.taillight, [rear + 0.04, 0.84, s * (half - 0.25)], [0, -s * 0.22, 0]));
    car.add(mesh(`foglight_${s > 0 ? 'R' : 'L'}`, new THREE.BoxGeometry(0.03, 0.06, 0.16), M.headlight, [front + 0.005, 0.42, s * (half - 0.28)]));
  }
  car.add(mesh('grille_upper', new THREE.BoxGeometry(0.05, 0.07, 0.62), M.trim, [front - 0.05, 0.73, 0]));
  car.add(mesh('grille_chrome', new THREE.BoxGeometry(0.03, 0.015, 0.66), M.chrome, [front - 0.03, 0.77, 0]));
  car.add(mesh('grille_lower', new THREE.BoxGeometry(0.05, 0.17, 1.0), M.trim, [front + 0.0, 0.46, 0]));
  car.add(mesh('plate_front', new THREE.BoxGeometry(0.012, 0.12, 0.44), M.plate, [front + 0.03, 0.58, 0]));
  car.add(mesh('emblem_front', new THREE.CylinderGeometry(0.05, 0.05, 0.015, 24), M.chrome, [front - 0.02, 0.75, 0], [0, 0, Math.PI / 2]));
  // 車尾：後車牌、後保桿下擾流、尾門飾條、三燈
  car.add(mesh('plate_rear', new THREE.BoxGeometry(0.012, 0.12, 0.44), M.plate, [rear - 0.008, 0.62, 0]));
  car.add(mesh('rear_diffuser', new THREE.BoxGeometry(0.05, 0.08, 1.2), M.trim, [rear + 0.03, 0.36, 0]));
  car.add(mesh('trunk_chrome', new THREE.BoxGeometry(0.02, 0.025, 0.7), M.chrome, [rear - 0.002, 0.78, 0]));
  car.add(mesh('emblem_rear', new THREE.CylinderGeometry(0.045, 0.045, 0.015, 24), M.chrome, [rear - 0.004, 0.86, 0], [0, 0, Math.PI / 2]));
  // 鯊魚鰭天線
  car.add(mesh('antenna', new THREE.ConeGeometry(0.035, 0.07, 12), M.trim, [r0 + 0.08, roofTop + 0.055, 0]));

  // ---- 造型變形：俯視收窄車頭／車尾、車廂上緣內傾（tumblehome）、下裙微內收 ----
  // 對車身與貼在車身上的零件一起套用（車輪除外），零件因此維持貼合曲面。
  const xf0 = front - 0.62, xr0 = rear + 0.5;
  const squeeze = (x, y) => {
    let k = 1;
    if (x > xf0) k *= 1 - 0.16 * Math.pow((x - xf0) / (front - xf0), 2);
    if (x < xr0) k *= 1 - 0.11 * Math.pow((xr0 - x) / (xr0 - rear), 2);
    if (y > 0.98) k *= 1 - 0.2 * Math.min(1, (y - 0.98) / 0.5);
    else if (y < 0.42) k *= 1 - 0.05 * ((0.42 - y) / 0.42);
    return k;
  };
  const lift = (x, y) => {
    // 引擎蓋前緣下壓、行李箱尾端圓滑
    if (y > 0.6 && x > front - 0.5) return -0.06 * Math.pow((x - (front - 0.5)) / 0.5, 2) * ((y - 0.6) / 0.4);
    return 0;
  };
  car.updateMatrixWorld(true);
  const v = new THREE.Vector3();
  car.traverse((o) => {
    if (!o.isMesh || /^wheel_/.test(o.parent?.name || '') ) return;
    const g = o.geometry.clone();
    const pos = g.attributes.position;
    const inv = o.matrixWorld.clone().invert();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
      const k = squeeze(v.x, v.y);
      v.z *= k;
      v.y += lift(v.x, v.y);
      v.applyMatrix4(inv);
      pos.setXYZ(i, v.x, v.y, v.z);
    }
    o.geometry = g;
  });
  car.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; o.geometry = mergeVertices(o.geometry, 1e-5); o.geometry.computeVertexNormals(); } });
  car.userData = { style: styleName, length: L, width: W, generator: 'tools/vehicle3d/build_models.mjs', license: 'self-authored (project), three.js MIT' };
  return car;
}

const exporter = new GLTFExporter();
for (const style of Object.keys(STYLES)) {
  const scene = new THREE.Scene();
  scene.add(buildCar(style));
  const glb = await exporter.parseAsync(scene, { binary: true });
  const path = resolve(OUT, `car_${style}.glb`);
  writeFileSync(path, Buffer.from(glb));
  console.log(`${style}: ${path} (${(glb.byteLength / 1024).toFixed(0)} KB)`);
}
