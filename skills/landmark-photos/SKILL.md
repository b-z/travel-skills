---
name: landmark-photos
description: Find a classic, freely licensed photo for each sight on a trip (Wikipedia lead images and Wikimedia Commons), keep author/licence attribution, and lay them out as a grouped thumbnail wall — per route, per day or per city — as an HTML page, an embeddable fragment, a single PNG or a PDF. Use this whenever an itinerary or list of sights already exists in the conversation and the user wants to see what the places look like — "把景点照片列出来", "每条路线的代表景点配图", "景点小图", "show me photos of these places", "make a picture sheet of the stops" — even if they don't mention Wikimedia or skills. Choosing which sights to visit is out of scope; this skill illustrates a list that is already there.
license: MIT
compatibility: python3 (standard library only); network access to wikipedia.org and wikimedia.org; macOS sips or Pillow for resizing (optional); Google Chrome or Chromium for PNG/PDF.
---

# 景点代表照片

给会话里已有的景点清单配上"一眼认得出"的代表照片，按组（路线、天数、城市）排成小图墙，每张图下面一行名字和一行实用备注。照片全部来自 Wikimedia Commons 的自由授权图片，作者和许可会完整保留。

挑选去哪些景点不在这个技能里。

## 工作流程

1. **把清单整理成 SPEC（JSON）。** 格式见 `references/spec.md`，示例见 `examples/uk-sights.json`。要点：
   - 分组按读者做决定的方式来：比较路线方案时按方案分；几条方案共用的城市（比如首都）单独成一组放在最前，后面每组只列它独有的，避免同一张图出现五次。
   - `name` 用读者的语言；`note` 写一句对行程有用的话（几点开门、冬天看不到什么、要不要预约），不要写百科简介。
   - 照片来源三选一，优先级从高到低：`wiki`（英文维基条目名，条目首图通常就是最经典的角度）→ `search`（Commons 搜索词，条目首图不合适时用）→ `file`（指定 Commons 文件名）。

2. **下载。**

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/landmark_photos.py" fetch SPEC.json --out OUTDIR
   ```

   已下载的会跳过，可以反复运行。维基的条目首图如果是地图、徽标或示意图（svg/png），脚本会自动改用 Commons 搜索。Wikimedia 会限流（HTTP 429），脚本会等待重试，所以几十张图要几分钟。不要并行跑多个下载。

3. **检查选图。** 用 Read 打开 `OUTDIR/contact.png`（检查页，带文件名和许可）。常见要换的：
   - 拍错了对象（一个人的特写、局部细节、艺术化处理过的照片、地图）；
   - 季节和行程差太多且会误导（例如冬天去的地方只有盛夏照片时，换不了就在页面上写一句"照片多是夏天拍的"）；
   - 许可后面有 ⚠ 的，确认是自由授权再用。

   换图：给那一项改成 `search`（换个更具体的搜索词）或 `file`，然后 `fetch ... --refresh KEY` 重新下载。

4. **生成。**

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/landmark_photos.py" build SPEC.json --out OUTDIR --png --pdf
   ```

   - `gallery.html`：独立网页，图片用相对路径 `img/…`，要和 `img/` 文件夹一起发；加 `--embed` 则把图片内嵌成单个 HTML 文件。
   - `gallery.png`：一张长图，固定 5 列，底部列出每张照片的文件名、作者和许可。
   - `gallery.pdf`：A4，署名列表展开。
   - `--fragment`：`gallery.fragment.html` + `gallery.css`，嵌进已有网页用。

5. **交付。**
   - 放进 Artifact 网页：Artifact 的 CSP 不允许加载外部图片，所以不能直接引用 upload.wikimedia.org。把 `OUTDIR/img/*.jpg` 作为页面的附带文件一起发布（路径保持 `img/<key>.jpg`），或者用 `--embed` 内嵌。
   - 图片、PDF：直接给文件。

## 署名

这些照片大多是 CC BY / CC BY-SA，使用条件就是署名。生成的网页和 PDF 末尾有完整的署名列表（文件名链接、作者、许可），PNG 底部也有，交付时不要删掉。署名列表是脚本从 Commons 的元数据里取的，作者字段偶尔会很长，脚本会截断到 90 个字符。
