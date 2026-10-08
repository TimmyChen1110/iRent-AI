"""產生取車／還車檢查四個外觀角度的 SVG 圖示（左前、右前、左後、右後）。

做法：用幾個凸多面體拼一台簡化轎車（下車身 + 車艙），從車輛四個角落約 45°、俯角約 24°
做正交投影，背面剔除後用 shapely 依深度裁切出每個面實際看得到的區域，所以四張圖是各自
投影出來的真實視角，不是同一張側視圖翻轉。

車頭／車尾靠細節區分：車頭＝較長的引擎蓋＋雙頭燈＋水箱罩；車尾＝較短的行李廂＋橫向尾燈＋車牌。

輸出為單色 SVG（fill 只用 #000 搭配不同 opacity），放進 asset catalog 以 template 模式渲染，
顏色交給 SwiftUI 的 foregroundStyle（未拍＝灰、完成＝accent）。

    python3 -m venv /tmp/v && /tmp/v/bin/pip install shapely
    /tmp/v/bin/python tools/angle_icons/generate.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "irent-app" / "Assets.xcassets"

VIEW_W, VIEW_H, PAD = 64.0, 48.0, 2.5
STROKE = 1.3
PITCH = math.radians(24)

# 座標：x 往車頭、y 往車輛左側、z 往上（公尺）
# 下車身：側面輪廓往 y 方向擠出
# 比例刻意比真車短胖，讓 45° 下車頭／車尾面夠大、燈具在小尺寸仍看得到
BODY_PROFILE = [(-1.90, 0.30), (1.90, 0.30), (1.94, 0.80), (-1.92, 0.98)]
BODY_HALF_W = 0.96
# 車艙：底面在腰線，頂面往內縮（tumblehome），位置偏後 → 引擎蓋比行李廂長
CABIN_BOTTOM = (-1.26, 0.70, 0.86, 0.95)  # x0, x1, 半寬, z
CABIN_TOP = (-0.98, -0.10, 0.68, 1.55)

WHEEL_X, WHEEL_R, WHEEL_Z = 1.20, 0.38, 0.34

VIEWS = {
    # 檔名: 觀看者所在方位（x=+1 車頭方向、y=+1 車輛左側）
    "inspection-angle-left-front": (1, 1),
    "inspection-angle-right-front": (1, -1),
    "inspection-angle-left-rear": (-1, 1),
    "inspection-angle-right-rear": (-1, -1),
}

# 各類面的填色透明度（template 模式下 alpha 會保留，產生明暗層次）
FILL = {"top": 0.06, "side": 0.12, "end": 0.24, "glass": 0.50, "roof": 0.10}


def body_faces():
    pts = BODY_PROFILE
    n = len(pts)
    faces = []
    left = [(x, BODY_HALF_W, z) for x, z in pts]
    right = [(x, -BODY_HALF_W, z) for x, z in pts]
    faces.append(("side", left))
    faces.append(("side", right))
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        quad = [(a[0], BODY_HALF_W, a[1]), (b[0], BODY_HALF_W, b[1]), (b[0], -BODY_HALF_W, b[1]), (a[0], -BODY_HALF_W, a[1])]
        nx, nz = b[1] - a[1], -(b[0] - a[0])  # 逆時針輪廓的外法向
        kind = "top" if nz > abs(nx) else "end"
        faces.append((kind, quad))
    return faces


def cabin_faces():
    bx0, bx1, bw, bz = CABIN_BOTTOM
    tx0, tx1, tw, tz = CABIN_TOP
    b = [(bx0, bw, bz), (bx1, bw, bz), (bx1, -bw, bz), (bx0, -bw, bz)]
    t = [(tx0, tw, tz), (tx1, tw, tz), (tx1, -tw, tz), (tx0, -tw, tz)]
    return [
        ("roof", t),
        ("glass", [b[1], b[2], t[2], t[1]]),  # 擋風玻璃
        ("glass", [b[3], b[0], t[0], t[3]]),  # 後擋
        ("cabin_side", [b[0], b[1], t[1], t[0]]),  # 左
        ("cabin_side", [b[2], b[3], t[3], t[2]]),  # 右
    ]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def centroid(pts):
    return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))


class Camera:
    def __init__(self, vx, vy):
        h = math.hypot(vx, vy)
        fx, fy = -vx / h, -vy / h  # 水平視線（朝車）
        self.right = (fy, -fx, 0.0)
        self.up = (fx * math.sin(PITCH), fy * math.sin(PITCH), math.cos(PITCH))
        self.toward = (-fx * math.cos(PITCH), -fy * math.cos(PITCH), math.sin(PITCH))  # 指向觀看者

    def project(self, p):
        return (dot(p, self.right), -dot(p, self.up))

    def near(self, p):
        return dot(p, self.toward)


def outward_visible(face, solid_center, cam):
    n = cross(sub(face[1], face[0]), sub(face[2], face[0]))
    if dot(n, sub(centroid(face), solid_center)) < 0:
        n = (-n[0], -n[1], -n[2])
    return dot(n, cam.toward) > 1e-9


def circle3d(cx, y, cz, r, steps=28):
    return [(cx + r * math.cos(2 * math.pi * i / steps), y, cz + r * math.sin(2 * math.pi * i / steps)) for i in range(steps)]


def end_details(front: bool):
    """車頭：兩顆斜切頭燈＋水箱罩；車尾：橫向尾燈＋車牌。回傳 (實心, 半透明) 多邊形（3D）。"""
    # 端面是 (±1.90, 0.30)→(1.94, 0.80)／(-1.92, 0.98) 的略斜平面；細節貼在面上再往外推一點
    def at(y, z):
        x = 1.90 + (0.04 * (z - 0.30) / 0.50 if front else 0.02 * (z - 0.30) / 0.68) + 0.004
        return (x if front else -x, y, z)

    filled, translucent = [], []
    if front:
        # 兩顆分開、內側斜切的頭燈＋中間水箱罩
        for s in (1, -1):
            filled.append([at(s * 0.88, 0.75), at(s * 0.36, 0.75), at(s * 0.46, 0.52), at(s * 0.88, 0.54)])
        translucent.append([at(0.24, 0.62), at(-0.24, 0.62), at(-0.22, 0.42), at(0.22, 0.42)])
    else:
        # 貫穿式橫向尾燈條＋下方車牌
        filled.append([at(0.88, 0.90), at(-0.88, 0.90), at(-0.88, 0.70), at(0.88, 0.70)])
        translucent.append([at(0.28, 0.60), at(-0.28, 0.60), at(-0.28, 0.42), at(0.28, 0.42)])
    return filled, translucent


def side_windows(sign):
    """車艙側面內縮的側窗（含 B 柱分隔）。"""
    bx0, bx1, bw, bz = CABIN_BOTTOM
    tx0, tx1, tw, tz = CABIN_TOP

    def lerp_edge(t_height, t_len):
        # 在車艙側面上取參數點：t_height 0=底、1=頂；t_len 沿車長
        x0 = bx0 + (tx0 - bx0) * t_height
        x1 = bx1 + (tx1 - bx1) * t_height
        w = bw + (tw - bw) * t_height
        z = bz + (tz - bz) * t_height
        return (x0 + (x1 - x0) * t_len, sign * w, z)

    h0, h1 = 0.14, 0.86
    rear = [lerp_edge(h0, 0.08), lerp_edge(h0, 0.47), lerp_edge(h1, 0.47), lerp_edge(h1, 0.10)]
    front = [lerp_edge(h0, 0.53), lerp_edge(h0, 0.92), lerp_edge(h1, 0.88), lerp_edge(h1, 0.53)]
    return [rear, front]


def poly2d(cam, pts):
    return Polygon([cam.project(p) for p in pts]).buffer(0)


def render(vx, vy):
    cam = Camera(vx, vy)
    body_center = (0.0, 0.0, 0.63)
    cabin_center = (-0.4, 0.0, 1.2)
    cabin = [("side" if k == "cabin_side" else k, p) for k, p in cabin_faces() if outward_visible(p, cabin_center, cam)]
    body = [(k, p) for k, p in body_faces() if outward_visible(p, body_center, cam)]
    # 車艙坐在下車身上且比車身窄，從上方看只會是車艙擋車身；各自內部再依深度排序
    faces = sorted(cabin, key=lambda f: -cam.near(centroid(f[1]))) + sorted(body, key=lambda f: -cam.near(centroid(f[1])))

    # 由近到遠裁切：每個面只保留沒被更近的面擋住的部分
    shapes = []  # (kind, geom, pts)
    covered = None
    for kind, pts in faces:
        g = poly2d(cam, pts)
        vis = g if covered is None else g.difference(covered)
        covered = g if covered is None else unary_union([covered, g])
        if not vis.is_empty:
            shapes.append((kind, vis, pts))
    car_silhouette = covered

    layers = []  # (geom, fill_opacity, stroke)
    # 遠側輪胎：只露出車身下緣
    vis_side = 1 if vy > 0 else -1
    for wx in (WHEEL_X, -WHEEL_X):
        far = poly2d(cam, circle3d(wx, -vis_side * BODY_HALF_W * 0.92, WHEEL_Z, WHEEL_R)).difference(car_silhouette)
        if not far.is_empty:
            layers.append((far, 0.55, False))

    for kind, g, _ in reversed(shapes):
        layers.append((g, FILL[kind], True))

    # 側窗
    for w in side_windows(vis_side):
        layers.append((poly2d(cam, w).intersection(car_silhouette), FILL["glass"], False))

    # 車頭或車尾細節
    filled, translucent = end_details(front=vx > 0)
    for p in filled:
        layers.append((poly2d(cam, p), 1.0, False))
    for p in translucent:
        layers.append((poly2d(cam, p), 0.55, False))

    # 近側輪胎：外圈實心、輪框挖空後淡填（template 模式不能用背景色蓋）
    for wx in (WHEEL_X, -WHEEL_X):
        y = vis_side * (BODY_HALF_W + 0.002)
        tire = poly2d(cam, circle3d(wx, y, WHEEL_Z, WHEEL_R))
        hub = poly2d(cam, circle3d(wx, y, WHEEL_Z, WHEEL_R * 0.5))
        layers.append((tire.difference(hub), 1.0, False))
        layers.append((hub, 0.3, False))
    return layers


def geoms_bounds(all_layers):
    xs, ys = [], []
    for layers in all_layers:
        for g, _, _ in layers:
            x0, y0, x1, y1 = g.bounds
            xs += [x0, x1]
            ys += [y0, y1]
    return min(xs), min(ys), max(xs), max(ys)


def path_d(geom, tf):
    polys = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    parts = []
    for poly in polys:
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)[:-1]
            pts = [tf(x, y) for x, y in coords]
            parts.append("M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z")
    return " ".join(parts)


def to_svg(layers, tf):
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{VIEW_W:g}" height="{VIEW_H:g}" viewBox="0 0 {VIEW_W:g} {VIEW_H:g}">']
    for g, fill, stroke in layers:
        if g.is_empty:
            continue
        d = path_d(g, tf)
        if not d:
            continue
        attrs = f'fill="#000000" fill-opacity="{fill:g}"' if fill else 'fill="none"'
        if stroke:
            attrs += f' stroke="#000000" stroke-width="{STROKE}" stroke-linejoin="round" stroke-linecap="round"'
        out.append(f'<path d="{d}" {attrs}/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    rendered = {name: render(*v) for name, v in VIEWS.items()}
    x0, y0, x1, y1 = geoms_bounds(rendered.values())
    s = min((VIEW_W - 2 * PAD) / (x1 - x0), (VIEW_H - 2 * PAD) / (y1 - y0))
    ox = (VIEW_W - (x1 - x0) * s) / 2 - x0 * s
    oy = (VIEW_H - (y1 - y0) * s) / 2 - y0 * s

    def tf(x, y):
        return (x * s + ox, y * s + oy)

    for name, layers in rendered.items():
        svg = to_svg(layers, tf)
        imageset = ASSETS / f"{name}.imageset"
        imageset.mkdir(exist_ok=True)
        (imageset / f"{name}.svg").write_text(svg)
        (imageset / "Contents.json").write_text(json.dumps({
            "images": [{"filename": f"{name}.svg", "idiom": "universal"}],
            "info": {"author": "xcode", "version": 1},
            "properties": {"preserves-vector-representation": True, "template-rendering-intent": "template"},
        }, indent=2) + "\n")
        print("wrote", imageset.relative_to(ROOT))


if __name__ == "__main__":
    main()
