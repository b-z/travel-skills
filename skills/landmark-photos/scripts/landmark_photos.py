#!/usr/bin/env python3
"""景点代表照片：从 Wikimedia Commons 取免费授权照片，排成按组分类的小图墙，并保留署名。

用法:
  python3 landmark_photos.py candidates SPEC.json --out DIR [--keys KEY ...] [--n 8]
  python3 landmark_photos.py fetch SPEC.json --out DIR [--refresh KEY ...] [--max 420] [--format jpg|webp]
  python3 landmark_photos.py build SPEC.json --out DIR [--embed] [--fragment] [--png] [--pdf]
  python3 landmark_photos.py assets SPEC.json --out DIR

candidates  每个景点在 Commons 搜前 N 张照片，列出文件名、尺寸、许可，生成 DIR/candidates.html（+ .png）
            供挑图；挑中的写进 SPEC 的 file 字段。
fetch  下载照片到 DIR/img/<key>.jpg（或 .webp），元数据（作者、许可、来源）写进 DIR/meta.json，
       并生成 DIR/contact.html（+ contact.png，有 Chrome 时）供人工检查选图。已下载的会跳过。
       --max 是最长边像素（默认 420，网页大图用 960），--format webp 体积约为 JPEG 的一半。
build  生成 DIR/gallery.html（图片用相对路径 img/…；--embed 改成内嵌 data URI 的单文件），
       --fragment 额外输出 gallery.fragment.html + gallery.css，--png 输出 gallery.png，--pdf 输出 gallery.pdf。
assets 不排版，只输出素材：DIR/assets.json（每张图的 data URI、名字、署名）和 DIR/credits.fragment.html，
       给自己排版的网页把照片放进各自的卡片里。

只用 Python 标准库；缩图优先用 macOS 的 sips，其次 Pillow，都没有就保留 Commons 的缩略图原样。
SPEC 格式见 references/spec.md。
"""
import argparse, base64, html, json, math, os, re, shutil, subprocess, sys, tempfile, time
import urllib.error, urllib.parse, urllib.request

# Wikimedia 要求 User-Agent 带联系方式，否则更容易被限流
UA = {'User-Agent': 'landmark-photos/1.1 (travel planning gallery; https://github.com/b-z/travel-skills)'}
STD_W = (330, 500, 960, 1280, 1920)   # Wikimedia 的标准缩略图宽度；非标准宽度更容易被限流（HTTP 429）
MIME = {'.jpg': 'image/jpeg', '.webp': 'image/webp'}


def thumb_w(maxpx):
    return next((w for w in STD_W if w >= maxpx), STD_W[-1])
FREE = re.compile(r'(cc[ -]?by|cc0|public domain|pd|gfdl|attribution|no restrictions)', re.I)
TEXT = {
    'zh': {'credits': '照片来源（Wikimedia Commons）', 'anon': '佚名', 'png_foot': '照片均来自 Wikimedia Commons，按各自许可使用。',
           'what': '是什么', 'why': '为什么去', 'who': '适合谁', 'photo': '照片：'},
    'en': {'credits': 'Photo credits (Wikimedia Commons)', 'anon': 'Unknown', 'png_foot': 'All photos from Wikimedia Commons under their respective licences.',
           'what': 'What it is', 'why': 'Why go', 'who': 'Who it suits', 'photo': 'Photo: '},
}
NOTES = ('what', 'why', 'who')   # 解说卡片的三栏


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def get(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            wait = int(e.headers.get('Retry-After') or 0) or 10 * (attempt + 1)
            log(f'  被限流（429），等 {min(wait, 60)} 秒')
            time.sleep(min(wait, 60))


def api(host, params):
    q = urllib.parse.urlencode({**params, 'format': 'json', 'formatversion': 2})
    return json.loads(get(f'https://{host}/w/api.php?{q}'))


def strip(h, n=90):
    t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', h or '')).strip()
    return t if len(t) <= n else t[:n - 1] + '…'


def commons_search(query):
    r = api('commons.wikimedia.org', {'action': 'query', 'list': 'search', 'srnamespace': 6, 'srsearch': query, 'srlimit': 15})
    return [h['title'][5:] for h in r['query']['search'] if h['title'].lower().endswith(('.jpg', '.jpeg'))]


def commons_candidates(query, n, width=330):
    """一次请求拿到搜索结果和每张图的尺寸、许可、缩略图地址；顺序和 commons_search 一致（只留 jpg）"""
    r = api('commons.wikimedia.org', {'action': 'query', 'generator': 'search', 'gsrnamespace': 6, 'gsrsearch': query,
                                      'gsrlimit': 15, 'prop': 'imageinfo', 'iiprop': 'url|size|extmetadata',
                                      'iiextmetadatafilter': 'Artist|LicenseShortName', 'iiurlwidth': width})
    pages = sorted(r.get('query', {}).get('pages', []), key=lambda p: p.get('index', 0))
    out = []
    for p in pages:
        if not p['title'].lower().endswith(('.jpg', '.jpeg')) or not p.get('imageinfo'):
            continue
        ii = p['imageinfo'][0]
        em = ii.get('extmetadata', {})
        out.append({'file': p['title'][5:], 'w': ii.get('width'), 'h': ii.get('height'), 'thumb': ii.get('thumburl'),
                    'license': strip(em.get('LicenseShortName', {}).get('value'), 40),
                    'artist': strip(em.get('Artist', {}).get('value'), 40)})
    return out[:n]


def lead_image(title, lang):
    r = api(f'{lang}.wikipedia.org', {'action': 'query', 'titles': title, 'prop': 'pageimages', 'piprop': 'name', 'redirects': 1})
    pg = r['query']['pages'][0]
    return pg.get('pageimage'), pg.get('title')


def imageinfo(fname, width=500):
    r = api('commons.wikimedia.org', {'action': 'query', 'titles': 'File:' + fname, 'prop': 'imageinfo',
                                      'iiprop': 'url|extmetadata|size', 'iiurlwidth': width})
    pg = r['query']['pages'][0]
    if pg.get('missing') or 'imageinfo' not in pg:
        return None
    return pg['imageinfo'][0]


def resize(src, dst, maxpx=420):
    """缩到最长边 maxpx；dst 的扩展名决定格式（.jpg / .webp）。返回实际写出的路径（webp 做不了时退回 jpg）"""
    if dst.endswith('.webp'):
        try:
            from PIL import Image  # noqa
            im = Image.open(src).convert('RGB')
            im.thumbnail((maxpx, maxpx))
            im.save(dst, 'WEBP', quality=78)
            return dst
        except Exception:
            pass
        if shutil.which('cwebp'):
            r = subprocess.run(['cwebp', '-quiet', '-q', '78', '-resize', str(maxpx), '0', src, '-o', dst],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode == 0:
                return dst   # 横图正好；竖图按宽度缩，会比 maxpx 高一些
        log('  没有 Pillow（带 WebP）或 cwebp，改存 JPEG')
        dst = dst[:-5] + '.jpg'
    if shutil.which('sips'):
        r = subprocess.run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '72', '-Z', str(maxpx), src, '--out', dst],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            return dst
    try:
        from PIL import Image  # noqa
        im = Image.open(src).convert('RGB')
        im.thumbnail((maxpx, maxpx))
        im.save(dst, 'JPEG', quality=72)
        return dst
    except Exception:
        shutil.copyfile(src, dst)
        return dst


def data_uri(path):
    mime = MIME.get(os.path.splitext(path)[1].lower(), 'image/jpeg')
    return f'data:{mime};base64,' + base64.b64encode(open(path, 'rb').read()).decode()


def img_name(meta_item, key):
    return meta_item.get('img', key + '.jpg')


def items_of(spec):
    for g in spec['groups']:
        for it in g['items']:
            yield g, it


# ---------------- candidates ----------------

def cmd_candidates(spec, out, keys, n):
    cdir = os.path.join(out, 'candidates')
    os.makedirs(cdir, exist_ok=True)
    rows, report = [], {}
    seen = set()
    for _, it in items_of(spec):
        key = it['key']
        if key in seen or (keys and key not in keys):
            continue
        seen.add(key)
        q = it.get('search') or it.get('wiki') or it.get('name') or key
        try:
            cands = commons_candidates(q, n)
        except Exception as e:
            log(f'✗ {key}: {e}'); continue
        report[key] = {'query': q, 'candidates': [{k: v for k, v in c.items() if k != 'thumb'} for c in cands]}
        log(f'## {key}（搜 "{q}"）')
        cells = []
        for i, c in enumerate(cands):
            flag = '' if FREE.search(c['license'] or '') else ' ⚠'
            log(f'  [{i}] {c["file"]}  {c["w"]}×{c["h"]}  {c["license"]}{flag}')
            tp = os.path.join(cdir, f'{key}-{i}.jpg')
            if c['thumb'] and not os.path.exists(tp):
                try:
                    open(tp, 'wb').write(get(c['thumb']))
                except Exception as e:
                    log(f'    缩略图下载失败: {e}')
                time.sleep(0.5)
            small = ' small' if (c['w'] or 0) < 960 else ''
            cells.append(f'<figure><img src="candidates/{esc(key)}-{i}.jpg"><figcaption><b>[{i}]</b> {esc(c["file"])}<br>'
                         f'<span class="{small}">{c["w"]}×{c["h"]}</span> · <i>{esc(c["license"])}</i>{flag}</figcaption></figure>')
        rows.append(f'<h2>{esc(key)} <small>{esc(it.get("name", ""))} · 搜 “{esc(q)}”</small></h2><div class="g">{"".join(cells)}</div>')
        time.sleep(1.5)
    json.dump(report, open(os.path.join(out, 'candidates.json'), 'w'), ensure_ascii=False, indent=1)
    sheet = os.path.join(out, 'candidates.html')
    open(sheet, 'w', encoding='utf-8').write(
        '<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:8px 12px;font:11px/1.35 -apple-system,sans-serif;width:1100px;box-sizing:border-box}'
        'h2{font-size:15px;margin:10px 0 6px}h2 small{font-weight:400;color:#666}.g{display:grid;grid-template-columns:repeat(6,1fr);gap:6px}'
        'figure{margin:0}img{width:100%;height:120px;object-fit:cover;display:block;background:#eee}'
        'figcaption{height:44px;overflow:hidden;word-break:break-all}.small{color:#c00}</style>' + ''.join(rows))
    chrome = find_chrome()
    if chrome:
        h = sum(40 + math.ceil(len(r['candidates']) / 6) * 176 for r in report.values()) + 20
        run_chrome(chrome, ['--force-device-scale-factor=1', f'--window-size=1100,{max(h, 200)}',
                            f'--screenshot={os.path.join(out, "candidates.png")}', '--allow-file-access-from-files'], sheet)
    print(f'候选页 {sheet}；挑中的照片把文件名写进 SPEC 的 "file"，再运行 fetch --refresh KEY。红字尺寸 = 原图不到 960px 宽')


# ---------------- fetch ----------------

def cmd_fetch(spec, out, refresh, maxpx=420, fmt='jpg'):
    lang = spec.get('wiki_lang', 'en')
    raw, img = os.path.join(out, 'raw'), os.path.join(out, 'img')
    os.makedirs(raw, exist_ok=True); os.makedirs(img, exist_ok=True)
    mp = os.path.join(out, 'meta.json')
    meta = json.load(open(mp)) if os.path.exists(mp) else {}
    seen = set()
    for _, it in items_of(spec):
        key = it['key']
        if key in seen:
            continue
        seen.add(key)
        want = key + '.' + fmt
        m0 = meta.get(key, {})
        if (key in meta and key not in refresh and os.path.exists(os.path.join(img, img_name(m0, key)))
                and m0.get('max', 420) == maxpx and img_name(m0, key).endswith('.' + fmt)):
            continue
        try:
            fname = page = None
            how = ''
            if it.get('file'):
                fname, how = it['file'].removeprefix('File:'), 'file'
            elif it.get('search'):
                hits = commons_search(it['search'])
                if hits:
                    fname, how = hits[it.get('pick', 0)], f'search "{it["search"]}"'
            elif it.get('wiki'):
                fname, page = lead_image(it['wiki'], it.get('wiki_lang', lang))
                how = f'wiki "{it["wiki"]}"'
                # 条目首图是地图、徽标、示意图（svg/png/gif）或缺失时，改用 Commons 搜索
                if not fname or not fname.lower().endswith(('.jpg', '.jpeg')):
                    hits = commons_search(page or it['wiki'])
                    fname, how = (hits[0] if hits else None), f'search "{page or it["wiki"]}"（条目首图不是照片）'
            if not fname:
                log(f'✗ {key}: 没找到照片，在 SPEC 里给它加 search 或 file'); continue
            info = imageinfo(fname, thumb_w(maxpx))
            if info is None and it.get('wiki'):   # 首图是非自由图片（只在维基百科本地），改搜 Commons
                hits = commons_search(page or it['wiki'])
                fname = hits[0] if hits else None
                info = imageinfo(fname, thumb_w(maxpx)) if fname else None
                how += '（首图不在 Commons）'
            if info is None:
                log(f'✗ {key}: Commons 上找不到 {fname}'); continue
            em = info.get('extmetadata', {})
            lic = strip(em.get('LicenseShortName', {}).get('value'), 40)
            thumb = info.get('thumburl') or info['url']
            ext = os.path.splitext(urllib.parse.urlparse(thumb).path)[1].lower() or '.jpg'
            rp = os.path.join(raw, key + ext)
            open(rp, 'wb').write(get(thumb))
            done = resize(rp, os.path.join(img, want), maxpx)
            meta[key] = {'file': fname, 'page': page, 'source_url': info.get('descriptionurl'),
                         'artist': strip(em.get('Artist', {}).get('value')), 'license': lic,
                         'license_url': em.get('LicenseUrl', {}).get('value'), 'via': how,
                         'img': os.path.basename(done), 'max': maxpx}
            if (info.get('width') or 0) < maxpx:
                log(f'  {key}: 原图只有 {info.get("width")}px 宽，比 --max {maxpx} 小，网页上会发虚')
            flag = '' if FREE.search(lic or '') else '  ⚠ 许可不常见，检查后再用'
            log(f'✓ {key}: {fname} [{lic}]{flag}')
            json.dump(meta, open(mp, 'w'), ensure_ascii=False, indent=1)
        except Exception as e:  # 单个失败不影响其它
            log(f'✗ {key}: {e}')
        time.sleep(1.5)
    json.dump(meta, open(mp, 'w'), ensure_ascii=False, indent=1)

    # 选图检查页
    cells = ''.join(f'<figure><img src="img/{esc(img_name(m, k))}"><figcaption><b>{esc(k)}</b><br>{esc(m["file"])}<br>'
                    f'<i>{esc(m["license"])}</i></figcaption></figure>' for k, m in meta.items() if k in seen)
    sheet = os.path.join(out, 'contact.html')
    n = len([k for k in meta if k in seen])
    open(sheet, 'w', encoding='utf-8').write(
        '<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:8px;font:11px/1.35 -apple-system,sans-serif;'
        'display:grid;grid-template-columns:repeat(6,1fr);gap:6px;width:1100px;box-sizing:border-box}figure{margin:0}'
        'img{width:100%;height:110px;object-fit:cover;display:block}figcaption{height:44px;overflow:hidden;word-break:break-all}'
        '</style>' + cells)
    chrome = find_chrome()
    if chrome:
        rows = math.ceil(n / 6)
        run_chrome(chrome, ['--force-device-scale-factor=1', f'--window-size=1100,{rows * 166 + 20}',
                            f'--screenshot={os.path.join(out, "contact.png")}', '--allow-file-access-from-files'], sheet)
    missing = [it['key'] for _, it in items_of(spec) if it['key'] not in meta]
    print(f'已有 {n} 张；检查页 {sheet}' + (f'；缺 {len(set(missing))} 张: {", ".join(sorted(set(missing)))}' if missing else ''))


# ---------------- build ----------------

def credit_items(spec, meta, keys, T):
    """署名列表的 <li>…</li>；照片拍的不是景点本身（photo_note）时，在署名里也注明"""
    first = {}
    for _, it in items_of(spec):
        first.setdefault(it['key'], it)
    return ''.join(f'<li>{esc(first[k].get("name", k))}：'
                   f'<a href="{esc(meta[k]["source_url"])}" target="_blank" rel="noopener">{esc(meta[k]["file"])}</a>，'
                   f'{esc(meta[k]["artist"] or T["anon"])}，{esc(meta[k]["license"])}'
                   + (f'（{esc(T["photo"] + first[k]["photo_note"])}）' if first[k].get('photo_note') else '') + '</li>'
                   for k in keys)


def cmd_assets(spec, out):
    """不排版，只给素材：自己排版的网页把 data URI 填进各自的 <img>，署名列表放页脚"""
    lang = spec.get('lang', 'zh')
    T = {**TEXT.get(lang, TEXT['zh']), **spec.get('labels', {})}
    meta = json.load(open(os.path.join(out, 'meta.json')))
    assets, used = {}, []
    for _, it in items_of(spec):
        k = it['key']
        if k not in meta or k in assets:
            continue
        m = meta[k]
        used.append(k)
        assets[k] = {'src': data_uri(os.path.join(out, 'img', img_name(m, k))), 'name': it.get('name', k),
                     'photo_note': it.get('photo_note'),
                     'title': f'{m["artist"] or T["anon"]} · {m["license"]}',
                     'credit': {f: m.get(f) for f in ('file', 'source_url', 'artist', 'license', 'license_url')}}
    ap = os.path.join(out, 'assets.json')
    json.dump(assets, open(ap, 'w'), ensure_ascii=False, indent=1)
    cp = os.path.join(out, 'credits.fragment.html')
    open(cp, 'w', encoding='utf-8').write(
        f'<details class="lp-credits"><summary>{T["credits"]}</summary><ul>{credit_items(spec, meta, used, T)}</ul></details>')
    kb = os.path.getsize(ap) // 1024
    print(f'生成：\n{ap}（{len(assets)} 张，{kb} KB）\n{cp}')
    if kb > 12000:
        log('⚠ 素材超过 12 MB，Artifact 上限 16 MB：用 --max 小一点或 --format webp 重新 fetch')


def cmd_build(spec, out, embed, fragment, png, pdf):
    lang = spec.get('lang', 'zh')
    T = {**TEXT.get(lang, TEXT['zh']), **spec.get('labels', {})}
    meta = json.load(open(os.path.join(out, 'meta.json')))
    # 任何一项有 what / why / who 就整页改成解说卡片；都没有时保持原来的小图墙，输出和以前逐字节一样
    rich = any(it.get(f) for _, it in items_of(spec) for f in NOTES)
    css = CSS + RICH_CSS if rich else CSS

    def src(key, inline):
        name = img_name(meta[key], key)
        if inline:
            return data_uri(os.path.join(out, 'img', name))
        return f'img/{name}'

    def rich_card(it, img, credit):
        name = esc(it.get('name', it['key']))
        tags = ''.join(f'<li>{esc(t)}</li>' for t in it.get('tags', []))
        dl = ''.join(f'<dt>{esc(T[f])}</dt><dd>{esc(it[f])}</dd>' for f in NOTES if it.get(f))
        return (f'<figure class="lp-card"><img src="{img}" alt="{name}" title="{esc(credit)}" width="420" height="315">'
                f'<figcaption><b>{name}</b>'
                + (f'<span>{esc(it["note"])}</span>' if it.get('note') else '')
                + (f'<span>{esc(T["photo"] + it["photo_note"])}</span>' if it.get('photo_note') else '')
                + (f'<ul class="lp-tags">{tags}</ul>' if tags else '')
                + (f'<dl>{dl}</dl>' if dl else '') + '</figcaption></figure>')

    def grid_html(inline):
        parts, used = [], []
        for g in spec['groups']:
            col = g.get('color', '#1A2230')
            parts.append(f'<section class="lp-group" style="--gc:{esc(col)}"><div class="lp-head">'
                         + (f'<span class="lp-badge">{esc(g["id"])}</span>' if g.get('id') else '')
                         + f'<span class="lp-title">{esc(g.get("title", ""))}</span>'
                         + (f'<span class="lp-sub">{esc(g["sub"])}</span>' if g.get('sub') else '')
                         + ('</div><div class="lp-grid lp-rich">' if rich else '</div><div class="lp-grid">'))
            for it in g['items']:
                k = it['key']
                if k not in meta:
                    continue
                if k not in used:
                    used.append(k)
                m = meta[k]
                credit = f'{m["artist"] or T["anon"]} · {m["license"]}'
                if rich:
                    parts.append(rich_card(it, src(k, inline), credit))
                    continue
                parts.append(f'<figure class="lp-card"><img src="{src(k, inline)}" alt="{esc(it.get("name", k))}" title="{esc(credit)}">'
                             f'<figcaption><b>{esc(it.get("name", k))}</b>'
                             + (f'<span>{esc(it["note"])}</span>' if it.get('note') else '')
                             + (f'<span>{esc(T["photo"] + it["photo_note"])}</span>' if it.get('photo_note') else '')
                             + '</figcaption></figure>')
            parts.append('</div></section>')
        parts.append(f'<details class="lp-credits"><summary>{T["credits"]}</summary><ul>{credit_items(spec, meta, used, T)}</ul></details>')
        return '\n'.join(parts), used

    grid, used = grid_html(embed)
    title = spec.get('title', '')
    head = (f'<h1>{esc(title)}</h1>' if title else '') + (f'<p class="lp-lead">{esc(spec["subtitle"])}</p>' if spec.get('subtitle') else '')
    page = PAGE.format(lang='zh-CN' if lang == 'zh' else 'en', theme='', title=esc(title or 'Gallery'), css=css, body=head + grid)
    gp = os.path.join(out, 'gallery.html')
    open(gp, 'w', encoding='utf-8').write(page)
    made = [gp]
    if fragment:
        open(os.path.join(out, 'gallery.fragment.html'), 'w', encoding='utf-8').write(grid)
        open(os.path.join(out, 'gallery.css'), 'w', encoding='utf-8').write(css)
        made += [os.path.join(out, 'gallery.fragment.html'), os.path.join(out, 'gallery.css')]

    chrome = find_chrome() if (png or pdf) else None
    if (png or pdf) and not chrome:
        log('没找到 Chrome/Chromium，跳过 PNG/PDF。可用环境变量 CHROME 指定路径。')
    if chrome and pdf:
        pp = os.path.join(out, 'gallery.pdf')
        printable = page.replace('<details class="lp-credits">', '<details class="lp-credits" open>').replace('<html lang="zh-CN"', '<html data-theme="light" lang="zh-CN"').replace('<html lang="en"', '<html data-theme="light" lang="en"')
        tmp = os.path.join(out, '.print.html')
        open(tmp, 'w', encoding='utf-8').write(printable)
        run_chrome(chrome, ['--no-pdf-header-footer', '--print-to-pdf-no-header', f'--print-to-pdf={pp}',
                            '--allow-file-access-from-files'], tmp)
        os.unlink(tmp)
        made.append(pp)
    if chrome and png and rich:
        # 解说卡片的文字长短不一，高度算不准：先在同样宽度下渲染一遍读出页面高度，再按这个高度截图
        COLS, CW, GAP = 3, 270, 14
        cr = ''.join(f'<li>{esc(meta[k]["file"])} — {esc(meta[k]["artist"] or T["anon"])}（{esc(meta[k]["license"])}）</li>' for k in used)
        body = (head + grid_html(True)[0].rsplit('<details', 1)[0]
                + f'<div class="lp-pngfoot">{T["png_foot"]}</div><ul class="lp-pngcred">{cr}</ul>'
                + '<script>addEventListener("load",()=>document.body.setAttribute("data-h",'
                  'Math.ceil(document.documentElement.getBoundingClientRect().height)))</script>')
        fixed = PAGE.format(lang='zh-CN' if lang == 'zh' else 'en', theme=' data-theme="light"', title='',
                            css=css + PNG_CSS + RICH_PNG_CSS, body=body)
        tmp = os.path.join(out, '.png.html')
        open(tmp, 'w', encoding='utf-8').write(fixed)
        w = COLS * CW + (COLS - 1) * GAP + 48
        dom = run_chrome(chrome, ['--force-device-scale-factor=1', f'--window-size={w},800', '--dump-dom'], tmp)
        m = re.search(r'data-h="(\d+)"', dom or '')
        h = int(m.group(1)) if m else 4000
        pp = os.path.join(out, 'gallery.png')
        run_chrome(chrome, ['--force-device-scale-factor=2', f'--window-size={w},{h}', f'--screenshot={pp}'], tmp)
        os.unlink(tmp)
        made.append(pp)
    elif chrome and png:
        # 固定版式，高度可以算准：5 列，卡片 180×(135+66)
        COLS, CW, IH, CH, GAP, HEAD, GGAP = 5, 180, 135, 66, 12, 30, 22
        h = 24 + (44 if title else 0) + (26 if spec.get('subtitle') else 0)
        for g in spec['groups']:
            n = len([it for it in g['items'] if it['key'] in meta])
            rows = math.ceil(n / COLS)
            h += HEAD + 8 + rows * (IH + CH + 2) + max(0, rows - 1) * GAP + GGAP
        credit_lines = math.ceil(len(used) / 2)
        h += 22 + credit_lines * 15 + 24
        cr = ''.join(f'<li>{esc(meta[k]["file"])} — {esc(meta[k]["artist"] or T["anon"])}（{esc(meta[k]["license"])}）</li>' for k in used)
        body = (head + grid_html(True)[0].rsplit('<details', 1)[0]
                + f'<div class="lp-pngfoot">{T["png_foot"]}</div><ul class="lp-pngcred">{cr}</ul>')
        fixed = PAGE.format(lang='zh-CN', theme=' data-theme="light"', title='', css=CSS + PNG_CSS, body=body)
        tmp = os.path.join(out, '.png.html')
        open(tmp, 'w', encoding='utf-8').write(fixed)
        pp = os.path.join(out, 'gallery.png')
        run_chrome(chrome, ['--force-device-scale-factor=2', f'--window-size={COLS * CW + (COLS - 1) * GAP + 48},{h}',
                            f'--screenshot={pp}'], tmp)
        os.unlink(tmp)
        made.append(pp)
    print('\n'.join(['生成：'] + made))


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
               '--virtual-time-budget=6000', *extra, 'file://' + os.path.abspath(page)]
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            cmd.insert(1, '--no-sandbox')  # 容器里以 root 运行时 Chrome 不加这个会直接退出
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180)
        return r.stdout.decode('utf-8', 'replace')


CSS = """
.lp-group{--ink:#1A2230;--muted:#5A6472;--card:#FFFFFF;--rule:#D9DCD4;--ph:#E8E9E2;display:flex;flex-direction:column;gap:8px;break-inside:avoid-page}
.lp-credits{--muted:#5A6472}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .lp-group{--ink:#E6E9EE;--muted:#9CA5B1;--card:#181D25;--rule:#2B323D;--ph:#2A313B}
 :root:not([data-theme="light"]) .lp-credits{--muted:#9CA5B1}}
:root[data-theme="dark"] .lp-group{--ink:#E6E9EE;--muted:#9CA5B1;--card:#181D25;--rule:#2B323D;--ph:#2A313B}
:root[data-theme="dark"] .lp-credits{--muted:#9CA5B1}
.lp-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.lp-badge{align-self:center;flex:none;font-weight:700;font-size:15px;min-width:26px;height:26px;padding:0 6px;border-radius:5px;display:grid;place-items:center;background:var(--gc);color:var(--card)}
.lp-title{font-weight:600;font-size:16px;color:var(--ink)}
.lp-sub{font-size:12.5px;color:var(--muted)}
.lp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.lp-card{margin:0;background:var(--card);border:1px solid var(--rule);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;min-width:0;break-inside:avoid}
.lp-card img{display:block;width:100%;aspect-ratio:4/3;object-fit:cover;background:var(--ph)}
.lp-card figcaption{padding:7px 9px 9px;display:flex;flex-direction:column;gap:1px;font-size:13px;line-height:1.45;color:var(--ink)}
.lp-card figcaption b{font-weight:600}
.lp-card figcaption span{font-size:12px;color:var(--muted)}
.lp-credits{font-size:12px;color:var(--muted)}
.lp-credits summary{cursor:pointer}
.lp-credits ul{margin:6px 0 0;padding-left:1.2em;display:flex;flex-direction:column;gap:2px;word-break:break-word}
@media (max-width:640px){.lp-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""

# 解说卡片（任何一项有 what / why / who 时追加）。分组颜色用在标签底色和三栏小标题上；深色主题把小标题颜色调亮
RICH_CSS = """
.lp-group{--gt:var(--gc)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .lp-group{--gt:color-mix(in srgb,var(--gc) 45%,#fff)}}
:root[data-theme="dark"] .lp-group{--gt:color-mix(in srgb,var(--gc) 45%,#fff)}
.lp-grid.lp-rich{grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.lp-rich .lp-card{border-radius:10px}
.lp-rich .lp-card figcaption{padding:12px 14px 14px;gap:8px;font-size:13.5px;line-height:1.6}
.lp-rich .lp-card figcaption b{font-size:16px;font-weight:700;line-height:1.4}
.lp-rich .lp-card figcaption span{margin-top:-6px}
.lp-tags{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:5px}
.lp-tags li{font-size:12px;line-height:1.4;padding:2px 7px;border-radius:4px;background:color-mix(in srgb,var(--gc) 14%,var(--card));color:var(--ink)}
.lp-rich dl{margin:0;display:grid;gap:6px}
.lp-rich dt{font-size:11.5px;letter-spacing:.08em;font-weight:700;color:var(--gt)}
.lp-rich dd{margin:-4px 0 0;overflow-wrap:anywhere}
@media (max-width:640px){.lp-grid.lp-rich{grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}}
@media print{.lp-grid.lp-rich{grid-template-columns:repeat(3,1fr) !important}}
"""

RICH_PNG_CSS = """
.lp-grid.lp-rich{grid-template-columns:repeat(3,270px);gap:14px}
.lp-rich .lp-card img{width:270px;height:202px}
.lp-rich .lp-card figcaption{height:auto;overflow:visible}
.lp-rich .lp-card figcaption span{display:block}
.lp-pngcred{margin-bottom:24px}
"""

PNG_CSS = """
body{background:#fff !important} .lp-wrap{padding:24px !important;gap:0 !important;max-width:none !important;margin:0 !important}
.lp-wrap h1{height:44px;margin:0;font-size:22px;line-height:44px} .lp-lead{height:26px;margin:0}
.lp-group{gap:8px;margin-bottom:22px} .lp-head{height:30px;align-items:center;flex-wrap:nowrap}
.lp-grid{grid-template-columns:repeat(5,180px);gap:12px}
.lp-card img{width:180px;height:135px;aspect-ratio:auto}
.lp-card figcaption{height:66px;box-sizing:border-box;overflow:hidden}
.lp-card figcaption span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.lp-pngfoot{height:22px;font-size:12px;color:#5A6472}
.lp-pngcred{margin:0;padding:0;list-style:none;columns:2;column-gap:24px;font-size:10px;line-height:15px;color:#5A6472}
.lp-pngcred li{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
"""

PAGE = """<!doctype html>
<html lang="{lang}"{theme}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{color-scheme:light dark}}
body{{margin:0;background:#F4F5F1;color:#1A2230;font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",sans-serif}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]) body{{background:#11151B;color:#E6E9EE}}}}
.lp-wrap{{max-width:940px;margin:0 auto;padding:24px 20px 48px;display:flex;flex-direction:column;gap:22px}}
h1{{margin:0;font-size:24px}} .lp-lead{{margin:0;color:#5A6472;font-size:14px}}
@media print{{body{{background:#fff}} @page{{size:A4;margin:10mm}} .lp-grid{{grid-template-columns:repeat(4,1fr) !important}}}}
{css}
</style></head><body><div class="lp-wrap">{body}</div></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description='从 Wikimedia Commons 取景点照片并排成小图墙')
    ap.add_argument('cmd', choices=['candidates', 'fetch', 'build', 'assets'])
    ap.add_argument('spec')
    ap.add_argument('--out', required=True)
    ap.add_argument('--refresh', nargs='*', default=[], help='fetch：重新下载这些 key')
    ap.add_argument('--max', type=int, default=420, help='fetch：最长边像素，默认 420；网页大图用 960')
    ap.add_argument('--format', choices=['jpg', 'webp'], default='jpg', help='fetch：图片格式，webp 约小一半')
    ap.add_argument('--keys', nargs='*', default=[], help='candidates：只看这些 key')
    ap.add_argument('--n', type=int, default=8, help='candidates：每个景点列几张')
    ap.add_argument('--embed', action='store_true', help='build：图片内嵌为 data URI，得到单个 HTML 文件')
    ap.add_argument('--fragment', action='store_true')
    ap.add_argument('--png', action='store_true')
    ap.add_argument('--pdf', action='store_true')
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding='utf-8'))
    os.makedirs(a.out, exist_ok=True)
    if a.cmd == 'candidates':
        cmd_candidates(spec, a.out, set(a.keys), a.n)
    elif a.cmd == 'fetch':
        cmd_fetch(spec, a.out, set(a.refresh), a.max, a.format)
    elif a.cmd == 'assets':
        cmd_assets(spec, a.out)
    else:
        cmd_build(spec, a.out, a.embed, a.fragment, a.png, a.pdf)


if __name__ == '__main__':
    main()
