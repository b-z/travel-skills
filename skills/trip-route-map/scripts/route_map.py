#!/usr/bin/env python3
"""行程路线示意图：把一条或多条路线画在真实海岸线底图上，每条路线一张小地图。

用法:
  python3 route_map.py SPEC.json --out OUTDIR [--png] [--pdf] [--svg] [--fragment]

输出（都在 OUTDIR 下）:
  maps.html            独立网页（浅色/深色主题自适应），总是生成
  maps.pdf             --pdf：整页 PDF（需要 Chrome/Chromium）
  map-<id>.png         --png：每条路线一张 2 倍图（需要 Chrome/Chromium）
  map-<id>.svg         --svg：每条路线一个独立 SVG
  maps.fragment.html   --fragment：只有地图网格的 HTML 片段 + maps.css，用来嵌进已有页面
  labels.json          每个标注最后放在哪个方位，方便手动微调

只用 Python 标准库。底图是 Natural Earth 1:10m（world-atlas@2.0.2），首次运行下载到缓存目录。
SPEC 格式见 references/spec.md。
"""
import argparse, html, json, math, os, re, shutil, subprocess, sys, tempfile, time
import urllib.parse, urllib.request

WORLD_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-{res}.json'
UA = {'User-Agent': 'trip-route-map/1.0 (travel route sketch)'}
PALETTE = [('#A3195B', '#E46CA6'), ('#46703A', '#95C480'), ('#2B6A8A', '#7DB8D7'), ('#93600F', '#E4AF5E'),
           ('#5A4F8F', '#B2A8E3'), ('#B4462B', '#F08A6C'), ('#2F7F78', '#6FC7BE')]
MODES = ('train', 'car', 'flight', 'ferry', 'bus', 'day', 'walk', 'transfer')
TEXT = {
    'zh': {'legend': '图例', 'train': '火车', 'car': '自驾', 'flight': '航班', 'ferry': '渡轮', 'bus': '大巴 / 跟团',
           'day': '一日游（往返）', 'walk': '步行', 'transfer': '接送车 / 机场线', 'night': '住几晚', 'pass': '途经点',
           'air': '机场', 'foot': '线路是示意，按途经点连直线，不是实际道路。底图：Natural Earth 1:10m。'},
    'en': {'legend': 'Legend', 'train': 'Train', 'car': 'Drive', 'flight': 'Flight', 'ferry': 'Ferry', 'bus': 'Coach / tour',
           'day': 'Day trip (return)', 'walk': 'Walk', 'transfer': 'Transfer', 'night': 'Nights', 'pass': 'Stop',
           'air': 'Airport', 'foot': 'Schematic: straight lines between waypoints, not actual roads. Base map: Natural Earth 1:10m.'},
}
RENDER_W = 420.0  # 估算标注尺寸时假定的地图显示宽度（CSS 像素）
TEXT_SCALES = [1.0, 0.85, 0.72, 0.6]  # text_scale=auto 时依次尝试


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


# ---------------- 数据与地理编码 ----------------

def http_get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(int(e.headers.get('Retry-After') or 0) or 6 * (i + 1))


def load_world(cache, res):
    path = os.path.join(cache, f'countries-{res}.json')
    if not os.path.exists(path):
        log(f'下载底图 countries-{res}.json …')
        data = http_get(WORLD_URL.format(res=res))
        with open(path, 'wb') as f:
            f.write(data)
    return json.load(open(path))


def geocode_wiki(title, lang, cache):
    """用维基百科条目的坐标做地理编码，结果缓存。"""
    cpath = os.path.join(cache, 'geocode.json')
    db = json.load(open(cpath)) if os.path.exists(cpath) else {}
    key = f'{lang}:{title}'
    if key not in db:
        q = urllib.parse.urlencode({'action': 'query', 'prop': 'coordinates', 'titles': title, 'redirects': 1,
                                    'format': 'json', 'formatversion': 2})
        r = json.loads(http_get(f'https://{lang}.wikipedia.org/w/api.php?{q}'))
        pg = r['query']['pages'][0]
        if 'coordinates' not in pg:
            raise SystemExit(f'维基百科条目 "{title}" 没有坐标，请在 SPEC 里直接写 lonlat')
        c = pg['coordinates'][0]
        db[key] = [c['lon'], c['lat']]
        json.dump(db, open(cpath, 'w'), ensure_ascii=False, indent=1)
        time.sleep(0.3)
    return db[key]


# ---------------- 投影：球面横轴墨卡托，单位 km ----------------

class TM:
    R = 6371.0

    def __init__(self, lon0, lat0):
        self.l0, self.p0 = math.radians(lon0), math.radians(lat0)

    def __call__(self, lon, lat):
        l, p = math.radians(lon) - self.l0, math.radians(lat)
        b = max(-0.999999, min(0.999999, math.cos(p) * math.sin(l)))
        x = 0.5 * self.R * math.log((1 + b) / (1 - b))
        y = self.R * (math.atan2(math.tan(p), math.cos(l)) - self.p0)
        return (x, -y)


# ---------------- 几何工具 ----------------

def decode_arcs(topo):
    sx, sy = topo['transform']['scale']
    tx, ty = topo['transform']['translate']
    arcs = []
    for arc in topo['arcs']:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx; y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def rings_of(geom, arcs):
    def ring(idx):
        out = []
        for i in idx:
            pts = arcs[i] if i >= 0 else arcs[~i][::-1]
            out.extend(pts if not out else pts[1:])
        return out
    polys = geom['arcs'] if geom['type'] == 'MultiPolygon' else [geom['arcs']] if geom['type'] == 'Polygon' else []
    return [[ring(r) for r in poly] for poly in polys]


def clip_rect(ring, x0, x1, y0, y1):
    def edge(pts, inside, inter):
        out = []
        if not pts:
            return out
        prev = pts[-1]
        for cur in pts:
            if inside(cur):
                if not inside(prev):
                    out.append(inter(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(inter(prev, cur))
            prev = cur
        return out
    ix = lambda xc: (lambda a, b: (xc, a[1] + (b[1] - a[1]) * (xc - a[0]) / (b[0] - a[0])))
    iy = lambda yc: (lambda a, b: (a[0] + (b[0] - a[0]) * (yc - a[1]) / (b[1] - a[1]), yc))
    pts = edge(ring, lambda p: p[0] >= x0, ix(x0))
    pts = edge(pts, lambda p: p[0] <= x1, ix(x1))
    pts = edge(pts, lambda p: p[1] >= y0, iy(y0))
    return edge(pts, lambda p: p[1] <= y1, iy(y1))


def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]; bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / L if L else math.hypot(px - ax, py - ay)
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def area(pts):
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2


def point_in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def ring_path(pr):
    return 'M' + 'L'.join(f'{x:.1f} {y:.1f}' for x, y in pr) + 'Z'


# ---------------- 主流程 ----------------

def resolve_point(v, places, lang, cache):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return tuple(v)
    if isinstance(v, str):
        if v not in places:
            raise SystemExit(f'找不到地点 "{v}"：请在 places 里定义')
        return places[v]['_lonlat']
    raise SystemExit(f'无法识别的地点: {v!r}')


def text_w(s, fs):
    return sum(fs * (1.0 if ord(c) > 0x2E7F else 0.56) for c in str(s))


def main():
    ap = argparse.ArgumentParser(description='把行程路线画在真实海岸线底图上')
    ap.add_argument('spec')
    ap.add_argument('--out', required=True)
    ap.add_argument('--png', action='store_true')
    ap.add_argument('--pdf', action='store_true')
    ap.add_argument('--svg', action='store_true')
    ap.add_argument('--fragment', action='store_true')
    ap.add_argument('--png-scale', type=float, default=2.0, help='PNG 像素密度（默认 2 倍）')
    ap.add_argument('--cache', default=os.path.expanduser('~/.cache/trip-route-map'))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.cache, exist_ok=True)

    spec = json.load(open(args.spec, encoding='utf-8'))
    lang = spec.get('lang', 'zh')
    T = TEXT.get(lang, TEXT['zh'])
    wlang = spec.get('wiki_lang', 'en')
    aspect_opt = spec.get('aspect', 'auto')

    places = spec.get('places', {})
    for k, p in places.items():
        if 'lonlat' in p:
            p['_lonlat'] = tuple(p['lonlat'])
        elif 'wiki' in p:
            p['_lonlat'] = tuple(geocode_wiki(p['wiki'], p.get('wiki_lang', wlang), args.cache))
        else:
            raise SystemExit(f'地点 {k} 需要 lonlat 或 wiki')
        p.setdefault('name', k)

    routes = spec['routes']
    # 每条路线的经纬度范围
    def route_points(r):
        pts = [resolve_point(s['place'], places, wlang, args.cache) for s in r.get('stops', [])]
        if not pts:
            for leg in r['legs']:
                pts += [resolve_point(v, places, wlang, args.cache) for v in leg['via']]
        return pts

    def lonlat_box(pts, pad=0.16):
        lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
        w, h = max(lons) - min(lons), max(lats) - min(lats)
        w, h = max(w, 0.3), max(h, 0.2)
        return [min(lons) - w * pad, min(lats) - h * pad, max(lons) + w * pad, max(lats) + h * pad]

    all_pts = [p for r in routes for p in route_points(r)]
    union = lonlat_box(all_pts, 0.0)
    for r in routes:
        b = r.get('bbox')
        if b == 'all':
            r['_box'] = lonlat_box(all_pts)
        elif isinstance(b, list):
            r['_box'] = b
        else:
            r['_box'] = lonlat_box(route_points(r))
        bb = r['_box']
        union = [min(union[0], bb[0]), min(union[1], bb[1]), max(union[2], bb[2]), max(union[3], bb[3])]

    proj = TM((union[0] + union[2]) / 2, (union[1] + union[3]) / 2)

    def natural(box):
        a, b = proj(box[0], (box[1] + box[3]) / 2), proj(box[2], (box[1] + box[3]) / 2)
        c, d = proj((box[0] + box[2]) / 2, box[1]), proj((box[0] + box[2]) / 2, box[3])
        return abs(b[0] - a[0]) / max(1e-6, abs(c[1] - d[1]))
    if aspect_opt == 'auto':
        nat = sorted(natural(r['_box']) for r in routes)
        med = nat[len(nat) // 2] if len(nat) % 2 else (nat[len(nat) // 2 - 1] + nat[len(nat) // 2]) / 2
        aspect = min([0.8, 1.0, 1.25, 1.5], key=lambda a: abs(math.log(a / med)))
    else:
        aspect = float(aspect_opt)

    def viewbox(box):
        xs, ys = [], []
        for lon in (box[0], (box[0] + box[2]) / 2, box[2]):
            for lat in (box[1], (box[1] + box[3]) / 2, box[3]):
                x, y = proj(lon, lat); xs.append(x); ys.append(y)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = x1 - x0, y1 - y0
        if w / h < aspect:
            nw = h * aspect; x0 -= (nw - w) / 2; w = nw
        else:
            nh = w / aspect; y0 -= (nh - h) / 2; h = nh
        return x0, y0, w, h

    for r in routes:
        r['_vb'] = viewbox(r['_box'])

    # 底图
    min_w = min(r['_vb'][2] for r in routes)
    max_w = max(r['_vb'][2] for r in routes)
    res = '50m' if min_w > 2500 else '10m'
    topo = load_world(args.cache, res)
    arcs = decode_arcs(topo)
    tol = max(0.08, min_w / 1100)
    uw, uh = union[2] - union[0], union[3] - union[1]
    cx0, cx1 = union[0] - uw * 0.6 - 1, union[2] + uw * 0.6 + 1
    cy0, cy1 = max(-85, union[1] - uh * 0.6 - 1), min(85, union[3] + uh * 0.6 + 1)
    stop_ll = [resolve_point(s['place'], places, wlang, args.cache) for r in routes for s in r.get('stops', [])]
    focus_p, other_p = [], []
    for g in topo['objects']['countries']['geometries']:
        polys = rings_of(g, arcs)
        if not polys:
            continue
        lons = [p[0] for poly in polys for p in poly[0]]
        lats = [p[1] for poly in polys for p in poly[0]]
        if max(lons) < cx0 or min(lons) > cx1 or max(lats) < cy0 or min(lats) > cy1:
            continue
        is_focus = any(point_in_ring(lo, la, poly[0]) for poly in polys for lo, la in stop_ll)
        for poly in polys:
            for ring in poly:
                cr = clip_rect(ring, cx0, cx1, cy0, cy1)
                if len(cr) < 4:
                    continue
                pr = [proj(*p) for p in cr]
                if area(pr) < tol * tol * 12:
                    continue
                far = max(range(len(pr)), key=lambda i: (pr[i][0] - pr[0][0]) ** 2 + (pr[i][1] - pr[0][1]) ** 2)
                s = simplify(pr[:far + 1], tol) + simplify(pr[far:], tol)[1:]
                if len(s) >= 4:
                    (focus_p if is_focus else other_p).append(ring_path(s))
    focus_d, other_d = ''.join(focus_p), ''.join(other_p)

    # ---------- 每条路线画一张图 ----------
    used_modes, used_kinds = set(), set()
    label_report = {}
    svgs = {}

    for ri, r in enumerate(routes):
        rid = str(r.get('id', ri + 1))
        light, dark = (r['color'], r.get('color_dark', r['color'])) if r.get('color') else PALETTE[ri % len(PALETTE)]
        r['_colors'] = (light, dark)
        x0, y0, w, h = r['_vb']
        k = w / RENDER_W
        P = lambda v: proj(*resolve_point(v, places, wlang, args.cache))
        body, obstacles_pts, marker_boxes, labels = [], [], [], []

        # 路段
        for leg in r['legs']:
            mode = leg.get('mode', 'train')
            if mode not in MODES:
                raise SystemExit(f'未知交通方式 {mode}，可选 {MODES}')
            used_modes.add(mode)
            pts = [P(v) for v in leg['via']]
            opt = ' optional' if leg.get('optional') else ''
            if mode == 'flight':
                (ax, ay), (bx, by) = pts[0], pts[-1]
                L = math.hypot(bx - ax, by - ay) or 1
                bend = leg.get('bend', 0.18)
                cx, cy = (ax + bx) / 2 - (by - ay) / L * L * bend, (ay + by) / 2 + (bx - ax) / L * L * bend
                q = lambda t, ax=ax, ay=ay, cx=cx, cy=cy, bx=bx, by=by: (
                    (1 - t) ** 2 * ax + 2 * (1 - t) * t * cx + t * t * bx, (1 - t) ** 2 * ay + 2 * (1 - t) * t * cy + t * t * by)
                d = f'M{ax:.1f} {ay:.1f}Q{cx:.1f} {cy:.1f} {bx:.1f} {by:.1f}'
                body.append(f'<path class="leg flight{opt}" d="{d}"/>')
                samples = [q(i / 60) for i in range(61)]
                along = lambda t, q=q: q(t)
            else:
                d = 'M' + 'L'.join(f'{x:.1f} {y:.1f}' for x, y in pts)
                if mode == 'car':
                    body.append(f'<path class="leg car-o{opt}" d="{d}"/><path class="leg car-i{opt}" d="{d}"/>')
                else:
                    body.append(f'<path class="leg {mode}{opt}" d="{d}"/>')
                samples = []
                seglen = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
                total = sum(seglen) or 1
                for i, sl in enumerate(seglen):
                    n = max(2, int(sl / (3 * k)))
                    for j in range(n):
                        t = j / n
                        samples.append((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t))
                samples.append(pts[-1])

                def along(t, pts=pts, seglen=seglen, total=total):
                    target, acc = t * total, 0
                    for i, sl in enumerate(seglen):
                        if acc + sl >= target and sl > 0:
                            u = (target - acc) / sl
                            return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u)
                        acc += sl
                    return pts[-1]
            obstacles_pts += samples
            if leg.get('label'):
                at = leg.get('label_at')
                if at is None:
                    inview = [p for p in samples if x0 + w * .04 < p[0] < x0 + w * .96 and y0 + h * .04 < p[1] < y0 + h * .96]
                    anchor = along(0.5)
                    if inview and not (x0 < anchor[0] < x0 + w and y0 < anchor[1] < y0 + h):
                        anchor = inview[-1] if inview[-1] != samples[-1] else inview[0]
                else:
                    anchor = P(at) if isinstance(at, (str, list)) else along(float(at))
                labels.append(dict(x=anchor[0], y=anchor[1], gap_px=6, name=leg['label'], sub='', cls='tag',
                                   size=10.5, pos=leg.get('label_pos'), prio=2, key=f'leg:{leg["label"]}'))

        stop_specs = []
        for s in r.get('stops', []):
            x, y = P(s['place'])
            pl = places[s['place']] if isinstance(s['place'], str) else {}
            nights = int(s.get('nights', 0) or 0)
            kind = s.get('kind') or ('night' if nights else 'pass')
            used_kinds.add(kind)
            stop_specs.append(dict(x=x, y=y, nights=nights, kind=kind, s=s, name=s.get('name', pl.get('name', s['place']))))

        def render_points(ts):
            """按文字缩放 ts 画地点和全部标注，返回 (markup, 方位记录, 冲突数)。"""
            kt = k * ts
            out, marker_boxes, lbls = [], [], []
            for st in stop_specs:
                x, y, kind, nights = st['x'], st['y'], st['kind'], st['nights']
                if kind == 'night':
                    rr = (8.5 if nights < 5 else 10) * kt
                    out.append(f'<circle class="night" cx="{x:.1f}" cy="{y:.1f}" r="{rr:.2f}"/>'
                               f'<text class="nights" x="{x:.1f}" y="{y:.1f}" font-size="{10.5 * kt:.2f}" text-anchor="middle" '
                               f'dominant-baseline="central">{nights}</text>')
                elif kind == 'air':
                    rr = 4.2 * kt
                    out.append(f'<rect class="air" x="{x - rr:.1f}" y="{y - rr:.1f}" width="{2 * rr:.1f}" height="{2 * rr:.1f}" '
                               f'transform="rotate(45 {x:.1f} {y:.1f})"/>')
                    rr *= 1.3
                else:
                    rr = 3.6 * kt
                    out.append(f'<circle class="pass" cx="{x:.1f}" cy="{y:.1f}" r="{rr:.2f}"/>')
                marker_boxes.append((x - rr, y - rr, x + rr, y + rr))
                if not st['s'].get('hide_label'):
                    lbls.append(dict(x=x, y=y, gap=rr + 4 * kt, name=st['name'], sub=st['s'].get('sub', ''), cls='lbl',
                                     size=11.5, pos=st['s'].get('pos'), prio=0 if kind == 'night' else 1,
                                     key=f'stop:{st["s"]["place"]}'))
            for lb in labels:
                lbls.append({**lb, 'gap': lb['gap_px'] * kt})
            for n in r.get('notes', []):   # 地名注记（如"北海"、"图外还有…"）
                nx, ny = proj(*n['lonlat'])
                lbls.append(dict(x=nx, y=ny, gap=0, name='', sub=n['text'], cls='lbl note', size=10.5, pos='c', prio=3, key='note'))

            # 标注避让：每个标注试 8 个方位（不行再试远一圈加引线），选重叠最少的
            DIRS = {'r': (1, 0), 'l': (-1, 0), 'tr': (.75, -.75), 'br': (.75, .75), 'tl': (-.75, -.75), 'bl': (-.75, .75),
                    't': (0, -1), 'b': (0, 1), 'c': (0, 0)}
            ORDER = ['r', 'l', 'tr', 'br', 'tl', 'bl', 't', 'b']
            placed, report, collisions, n_far = [], {}, 0, 0

            def box_for(lb, pos, far=1.0):
                dx, dy = DIRS[pos]
                fs = lb['size'] * kt
                wtxt = text_w(lb['name'], fs) + (text_w(lb['sub'], fs * 0.86) + 3 * kt if lb['sub'] else 0)
                hh = fs * 1.25
                lx, ly = lb['x'] + dx * lb['gap'] * far, lb['y'] + dy * lb['gap'] * far
                anchor = 'start' if dx > 0.1 else ('end' if dx < -0.1 else 'middle')
                bx0 = lx if anchor == 'start' else (lx - wtxt if anchor == 'end' else lx - wtxt / 2)
                if abs(dy) < 0.1:
                    by0 = ly - hh / 2
                elif dy < 0:
                    ly -= 1 * kt; by0 = ly - hh
                else:
                    by0 = ly
                return (bx0, by0, bx0 + wtxt, by0 + hh), lx, ly, anchor, ('middle' if abs(dy) < 0.1 else ('auto' if dy < 0 else 'hanging'))

            def overlap(a, b):
                return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))

            ar = lambda b: max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
            # 圆点彼此压住也算重叠（比如首都和旁边的机场），缩小文字时圆点一起缩小
            for i in range(len(marker_boxes)):
                for j in range(i + 1, len(marker_boxes)):
                    if overlap(marker_boxes[i], marker_boxes[j]) > 0.15 * min(ar(marker_boxes[i]), ar(marker_boxes[j])):
                        collisions += 1
            for lb in sorted(lbls, key=lambda l: l['prio']):
                cands = [(lb['pos'].split('+')[0], 3.2 if lb['pos'].endswith('+far') else 1.0)] if lb['pos'] else [(o, 1.0) for o in ORDER]
                if not lb['pos'] and lb['cls'] == 'lbl':
                    cands += [(o, 3.2) for o in ORDER]   # 远一点放，再画一条引线
                best = None
                for ci, (pos, far) in enumerate(cands):
                    bx, lx, ly, anc, base = box_for(lb, pos, far)
                    barea = ar(bx)
                    others = [m for m in marker_boxes if not (m[0] <= lb['x'] <= m[2] and m[1] <= lb['y'] <= m[3])]
                    out_frac = 1 - overlap(bx, (x0, y0, x0 + w, y0 + h)) / barea
                    lab_hit = sum(overlap(bx, p) / min(barea, ar(p)) for p in placed)
                    mk_hit = sum(overlap(bx, m) / ar(m) for m in others)
                    score = out_frac * 2000 + lab_hit * 900 + mk_hit * 700
                    score += sum(1 for px, py in obstacles_pts if bx[0] <= px <= bx[2] and bx[1] <= py <= bx[3]) * 6
                    score += ci * 0.5 + (60 if far > 1 else 0)
                    bad = out_frac > 0.03 or lab_hit > 0.12 or mk_hit > 0.25
                    if best is None or score < best[0]:
                        best = (score, pos, bx, lx, ly, anc, base, far, bad)
                _, pos, bx, lx, ly, anc, base, far, bad = best
                collisions += bad
                n_far += far > 1
                placed.append(bx)
                report[lb['key']] = pos + ('+far' if far > 1 else '')
                if far > 1:
                    ex, ey = lb['x'] + (lx - lb['x']) * 0.2, lb['y'] + (ly - lb['y']) * 0.2
                    out.append(f'<path class="leader" d="M{ex:.1f} {ey:.1f}L{lx:.1f} {ly:.1f}"/>')
                fs = lb['size'] * kt
                t = (f'<text class="{lb["cls"]}" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anc}" dominant-baseline="{base}" '
                     f'font-size="{fs:.2f}" stroke-width="{3.2 * kt:.2f}">')
                if lb['name']:
                    t += f'<tspan class="nm">{esc(lb["name"])}</tspan>'
                if lb['sub']:
                    dx_attr = f' dx="{3 * kt:.2f}"' if lb['name'] else ''
                    t += f'<tspan class="sub" font-size="{fs * (0.86 if lb["name"] else 1):.2f}"{dx_attr}>{esc(lb["sub"])}</tspan>'
                out.append(t + '</text>')
            return out, report, collisions, n_far

        # 文字缩放：auto 时先用原大小，标注放不下就逐级缩小（PNG 会相应提高分辨率，文字的像素大小不变）
        ts_opt = r.get('text_scale', spec.get('text_scale', 'auto'))
        tries = TEXT_SCALES if ts_opt == 'auto' else [float(ts_opt)]
        # 质量 = 重叠数×10 + 挪远加引线的个数；先缩小文字，缩到最小仍放不下才接受引线
        best = None
        for ts in tries:
            res_pts = render_points(ts)
            q = res_pts[2] * 10 + res_pts[3]
            if best is None or q < best[0]:
                best = (q, ts, res_pts)
            if q == 0:
                break
        _, ts, (pts_markup, report, collisions, n_far) = best
        r['_ts'] = ts
        body += pts_markup
        label_report[rid] = {'_text_scale': ts, '_collisions': collisions, **report}
        if ts < 1 or collisions:
            log(f'路线 {rid}: 文字缩放 {ts}' + (f'，仍有 {collisions} 个标注重叠，见 labels.json，可手动设 pos/hide_label' if collisions else ''))

        svgs[rid] = (f'<svg class="rmap" viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" role="img" '
                     f'aria-label="{esc(r.get("title", rid))}">'
                     f'<rect class="water" x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}"/>'
                     f'<use href="#trm-other" class="land-o"/><use href="#trm-focus" class="land"/>' + ''.join(body) + '</svg>')

    # ---------- 组装 ----------
    css = CSS.replace('__ASPECT__', f'{aspect:.4f}')
    defs = (f'<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
            f'<path id="trm-focus" vector-effect="non-scaling-stroke" d="{focus_d}"/>'
            f'<path id="trm-other" vector-effect="non-scaling-stroke" d="{other_d}"/></defs></svg>')
    cards = []
    for ri, r in enumerate(routes):
        rid = str(r.get('id', ri + 1))
        light, dark = r['_colors']
        rec = (' rec' if r.get('highlight') else '') + (' wide' if r['_ts'] < 0.8 else '')
        cards.append(f'<figure class="trm-card{rec}" style="--rc-l:{light};--rc-d:{dark}">'
                     f'<figcaption><span class="trm-badge">{esc(rid)}</span><span>{esc(r.get("title", ""))}</span></figcaption>'
                     f'{svgs[rid]}' + (f'<p class="trm-note">{esc(r["note"])}</p>' if r.get('note') else '') + '</figure>')
    li = []
    for m in MODES:
        if m in used_modes:
            if m == 'car':
                ic = '<path class="lg car-o" d="M2 6H42"/><path class="lg car-i" d="M2 6H42"/>'
            else:
                ic = f'<path class="lg {m}" d="M2 6H42"/>'
            li.append(f'<li><svg viewBox="0 0 44 12" aria-hidden="true">{ic}</svg>{T[m]}</li>')
    if 'night' in used_kinds:
        li.append(f'<li><svg viewBox="0 0 44 16" aria-hidden="true"><circle class="lg-night" cx="22" cy="8" r="7"/>'
                  f'<text x="22" y="8" class="lg-n" text-anchor="middle" dominant-baseline="central">3</text></svg>{T["night"]}</li>')
    if 'air' in used_kinds:
        li.append(f'<li><svg viewBox="0 0 44 16" aria-hidden="true"><rect class="lg-pass" x="18" y="4" width="8" height="8" '
                  f'transform="rotate(45 22 8)"/></svg>{T["air"]}</li>')
    if 'pass' in used_kinds:
        li.append(f'<li><svg viewBox="0 0 44 12" aria-hidden="true"><circle class="lg-pass" cx="22" cy="6" r="3.5"/></svg>{T["pass"]}</li>')
    legend = (f'<div class="trm-card trm-legend"><div class="trm-lgt">{T["legend"]}</div><ul class="trm-lg">{"".join(li)}</ul>'
              f'<p class="trm-note">{T["foot"]}</p></div>')
    grid = defs + '<div class="trm-grid">' + ''.join(cards) + legend + '</div>'

    title = spec.get('title', '')
    page = PAGE.format(print_cols='1fr 1fr' if aspect < 1.1 else '1fr', lang='zh-CN' if lang == 'zh' else 'en', theme='{theme}', title=esc(title), css=css,
                       h1=f'<h1>{esc(title)}</h1>' if title else '',
                       sub=f'<p class="trm-sub">{esc(spec["subtitle"])}</p>' if spec.get('subtitle') else '', grid=grid)
    out_html = os.path.join(args.out, 'maps.html')
    open(out_html, 'w', encoding='utf-8').write(page.replace('{theme}', ''))
    json.dump(label_report, open(os.path.join(args.out, 'labels.json'), 'w'), ensure_ascii=False, indent=1)
    made = [out_html]

    if args.fragment:
        open(os.path.join(args.out, 'maps.fragment.html'), 'w', encoding='utf-8').write(grid)
        open(os.path.join(args.out, 'maps.css'), 'w', encoding='utf-8').write(css)
        made += ['maps.fragment.html', 'maps.css']

    standalone = {}
    if args.svg or args.png:
        for ri, r in enumerate(routes):
            rid = str(r.get('id', ri + 1))
            light, _ = r['_colors']
            x0, y0, w, h = r['_vb']
            k = w / RENDER_W * r['_ts']
            inner = svgs[rid].split('>', 1)[1].rsplit('</svg>', 1)[0]
            ttl = (f'<g class="ttl"><rect x="{x0 + 8 * k:.1f}" y="{y0 + 8 * k:.1f}" width="{20 * k:.1f}" height="{20 * k:.1f}" '
                   f'rx="{3 * k:.1f}" fill="{light}"/><text x="{x0 + 18 * k:.1f}" y="{y0 + 18.5 * k:.1f}" text-anchor="middle" '
                   f'dominant-baseline="central" font-size="{12 * k:.2f}" class="ttl-id">{esc(rid)}</text>'
                   f'<text x="{x0 + 34 * k:.1f}" y="{y0 + 18.5 * k:.1f}" dominant-baseline="central" font-size="{13 * k:.2f}" '
                   f'class="ttl-t" stroke-width="{3.5 * k:.2f}">{esc(r.get("title", ""))}</text></g>')
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" '
                   f'width="{RENDER_W / r["_ts"]:.0f}" height="{RENDER_W / r["_ts"] / aspect:.0f}" style="--rc:{light}">'
                   f'<style>{SVG_CSS}</style><defs><path id="trm-focus" vector-effect="non-scaling-stroke" d="{focus_d}"/>'
                   f'<path id="trm-other" vector-effect="non-scaling-stroke" d="{other_d}"/></defs>{inner}{ttl}</svg>')
            p = os.path.join(args.out, f'map-{rid}.svg')
            open(p, 'w', encoding='utf-8').write(svg)
            standalone[rid] = (p, RENDER_W / r['_ts'], RENDER_W / r['_ts'] / aspect)
            if args.svg:
                made.append(os.path.basename(p))

    if args.png or args.pdf:
        chrome = find_chrome()
        if not chrome:
            log('没找到 Chrome/Chromium，跳过 PNG/PDF。可用环境变量 CHROME 指定路径。')
        else:
            if args.pdf:
                pdf = os.path.join(args.out, 'maps.pdf')
                light_html = os.path.join(args.out, '.print.html')
                open(light_html, 'w', encoding='utf-8').write(page.replace('{theme}', ' data-theme="light"'))
                run_chrome(chrome, ['--no-pdf-header-footer', '--print-to-pdf-no-header', f'--print-to-pdf={pdf}'], light_html)
                os.unlink(light_html)
                made.append('maps.pdf')
            if args.png:
                for rid, (p, wcss, hcss) in standalone.items():
                    png = os.path.join(args.out, f'map-{rid}.png')
                    wpx, hpx = int(round(wcss)), int(round(hcss))
                    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8') as f:
                        f.write(f'<!doctype html><meta charset="utf-8"><body style="margin:0">'
                                f'<img src="file://{p}" width="{wpx}" height="{hpx}" style="display:block"></body>')
                    run_chrome(chrome, [f'--force-device-scale-factor={args.png_scale}', f'--window-size={wpx},{hpx}',
                                        f'--screenshot={png}', '--allow-file-access-from-files'], f.name)
                    os.unlink(f.name)
                    if not args.svg:
                        os.unlink(p)
                    made.append(os.path.basename(png))
    print('\n'.join(['生成：'] + [os.path.join(args.out, os.path.basename(m)) for m in made]))


def find_chrome():
    for c in [os.environ.get('CHROME'), '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
              '/Applications/Chromium.app/Contents/MacOS/Chromium', shutil.which('google-chrome'),
              shutil.which('google-chrome-stable'), shutil.which('chromium'), shutil.which('chromium-browser')]:
        if c and os.path.exists(c):
            return c
    return None


def run_chrome(chrome, extra, page):
    with tempfile.TemporaryDirectory() as prof:
        cmd = [chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars', f'--user-data-dir={prof}',
               '--virtual-time-budget=5000', *extra, 'file://' + os.path.abspath(page)]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)


CSS = """
.trm-grid{--land:#E8E9E2;--land-o:#F1F1EC;--water:#D9E6EC;--coast:#B4BAB0;--ink:#1A2230;--muted:#5A6472;--card:#FFFFFF;--rule:#D9DCD4;
  display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .trm-grid{--land:#2A313B;--land-o:#1D2229;--water:#141A21;--coast:#3E4753;--ink:#E6E9EE;--muted:#9CA5B1;--card:#181D25;--rule:#2B323D}
  :root:not([data-theme="light"]) .trm-card{--rc:var(--rc-d)}}
:root[data-theme="dark"] .trm-grid{--land:#2A313B;--land-o:#1D2229;--water:#141A21;--coast:#3E4753;--ink:#E6E9EE;--muted:#9CA5B1;--card:#181D25;--rule:#2B323D}
:root[data-theme="dark"] .trm-card{--rc:var(--rc-d)}
.trm-card{--rc:var(--rc-l,#1A2230);margin:0;background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:8px;min-width:0;break-inside:avoid}
.trm-card.rec{border:2px solid var(--rc)}
.trm-card.wide{grid-column:1/-1}  /* 文字缩小过的图占满一行，屏幕上字不会太小 */
.trm-card figcaption{display:flex;align-items:center;gap:10px;font-weight:600;font-size:15.5px;color:var(--ink)}
.trm-badge{flex:none;font-weight:700;font-size:15px;min-width:28px;height:28px;padding:0 6px;border-radius:5px;display:grid;place-items:center;background:var(--rc);color:var(--card)}
.trm-note{margin:0;font-size:12.5px;color:var(--muted);line-height:1.55}
.rmap{display:block;width:100%;max-width:100%;height:auto;aspect-ratio:__ASPECT__;border-radius:5px}
.rmap .water{fill:var(--water)}
.rmap .land{fill:var(--land);stroke:var(--coast);stroke-width:.7px}
.rmap .land-o{fill:var(--land-o);stroke:var(--coast);stroke-width:.5px}
.rmap .leg{fill:none;stroke:var(--rc);vector-effect:non-scaling-stroke;stroke-linecap:round;stroke-linejoin:round}
.rmap .leg.train{stroke-width:2.6px}
.rmap .leg.car-o{stroke-width:5.5px}
.rmap .leg.car-i{stroke:var(--land);stroke-width:1.8px}
.rmap .leg.flight{stroke-width:2px;stroke-dasharray:6 4}
.rmap .leg.ferry{stroke-width:2px;stroke-dasharray:9 3 2 3}
.rmap .leg.bus{stroke-width:2px;stroke-dasharray:2 2}
.rmap .leg.day{stroke-width:2.2px;stroke-dasharray:.1 4.5}
.rmap .leg.walk{stroke-width:1.6px;stroke-dasharray:.1 3}
.rmap .leg.transfer{stroke-width:1.4px}
.rmap .leg.optional{opacity:.5}
.rmap .night{fill:var(--rc);stroke:var(--card);stroke-width:1.5px;vector-effect:non-scaling-stroke}
.rmap .nights{fill:var(--card);font-weight:700}
.rmap .pass,.rmap .air{fill:var(--card);stroke:var(--rc);stroke-width:1.8px;vector-effect:non-scaling-stroke}
.rmap .leader{fill:none;stroke:var(--muted);stroke-width:.8px;vector-effect:non-scaling-stroke}
.rmap .lbl,.rmap .tag{paint-order:stroke;stroke:var(--land);stroke-linejoin:round}
.rmap .lbl .nm{fill:var(--ink);font-weight:600}
.rmap .lbl .sub,.rmap .tag .sub{fill:var(--muted);font-weight:400}
.rmap .tag .nm{fill:var(--rc);font-weight:600}
.trm-legend{justify-content:flex-start;gap:12px}
.trm-lgt{font-weight:600;font-size:15.5px;color:var(--ink)}
.trm-lg{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px;font-size:14px;color:var(--ink)}
.trm-lg li{display:flex;align-items:center;gap:10px}
.trm-lg svg{width:44px;height:16px;flex:none;overflow:visible}
.trm-lg .lg{fill:none;stroke:var(--ink);stroke-linecap:round}
.trm-lg .train{stroke-width:2.6}.trm-lg .car-o{stroke-width:5.5}.trm-lg .car-i{stroke:var(--card);stroke-width:1.8}
.trm-lg .flight{stroke-width:2;stroke-dasharray:6 4}.trm-lg .ferry{stroke-width:2;stroke-dasharray:9 3 2 3}
.trm-lg .bus{stroke-width:2;stroke-dasharray:2 2}.trm-lg .day{stroke-width:2.2;stroke-dasharray:.1 4.5}
.trm-lg .walk{stroke-width:1.6;stroke-dasharray:.1 3}.trm-lg .transfer{stroke-width:1.4}
.trm-lg .lg-night{fill:var(--ink)}.trm-lg .lg-n{fill:var(--card);font-weight:700;font-size:10.5px}
.trm-lg .lg-pass{fill:var(--card);stroke:var(--ink);stroke-width:1.8}
"""

SVG_CSS = """
svg{--land:#E8E9E2;--land-o:#F1F1EC;--water:#D9E6EC;--coast:#B4BAB0;--ink:#1A2230;--muted:#5A6472;--card:#FFFFFF;
 font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",sans-serif}
.water{fill:var(--water)}.land{fill:var(--land);stroke:var(--coast);stroke-width:.7px}.land-o{fill:var(--land-o);stroke:var(--coast);stroke-width:.5px}
.leg{fill:none;stroke:var(--rc);vector-effect:non-scaling-stroke;stroke-linecap:round;stroke-linejoin:round}
.leg.train{stroke-width:2.6px}.leg.car-o{stroke-width:5.5px}.leg.car-i{stroke:var(--land);stroke-width:1.8px}
.leg.flight{stroke-width:2px;stroke-dasharray:6 4}.leg.ferry{stroke-width:2px;stroke-dasharray:9 3 2 3}
.leg.bus{stroke-width:2px;stroke-dasharray:2 2}.leg.day{stroke-width:2.2px;stroke-dasharray:.1 4.5}
.leg.walk{stroke-width:1.6px;stroke-dasharray:.1 3}.leg.transfer{stroke-width:1.4px}.leg.optional{opacity:.5}
.night{fill:var(--rc);stroke:var(--card);stroke-width:1.5px;vector-effect:non-scaling-stroke}.nights{fill:var(--card);font-weight:700}
.pass,.air{fill:var(--card);stroke:var(--rc);stroke-width:1.8px;vector-effect:non-scaling-stroke}
.leader{fill:none;stroke:var(--muted);stroke-width:.8px;vector-effect:non-scaling-stroke}
.lbl,.tag,.ttl-t{paint-order:stroke;stroke:var(--land);stroke-linejoin:round}
.lbl .nm{fill:var(--ink);font-weight:600}.lbl .sub,.tag .sub{fill:var(--muted)}.tag .nm{fill:var(--rc);font-weight:600}
.ttl-id{fill:#fff;font-weight:700}.ttl-t{fill:var(--ink);font-weight:700}
"""

PAGE = """<!doctype html>
<html lang="{lang}"{theme}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{color-scheme:light dark}}
body{{margin:0;background:#F4F5F1;color:#1A2230;font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",sans-serif}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]) body{{background:#11151B;color:#E6E9EE}}}}
.trm-wrap{{max-width:940px;margin:0 auto;padding:24px 20px 48px;display:flex;flex-direction:column;gap:14px}}
h1{{margin:0;font-size:24px}} .trm-sub{{margin:0;color:#5A6472;font-size:14px}}
@media print{{body{{background:#fff}} .trm-grid{{grid-template-columns:{print_cols} !important}} @page{{size:A4;margin:10mm}}}}
{css}
</style></head><body><div class="trm-wrap">{h1}{sub}{grid}</div></body></html>
"""

if __name__ == '__main__':
    main()
