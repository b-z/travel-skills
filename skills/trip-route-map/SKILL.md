---
name: trip-route-map
description: Draw schematic travel route maps on a real base map — country/region scale on Natural Earth coastlines, city scale (walking days, metro, river boats) on OpenStreetMap streets, rivers and parks — one small map per itinerary option or per day, with overnight stops (number of nights), dates, pass-through sights and transport modes (train, metro, drive, flight, ferry, coach, walk, day trip). Outputs a themed HTML page, an embeddable HTML fragment, per-route PNG/SVG, or a PDF. Use this whenever a trip plan or several route options already exist in the conversation and the user wants to see them on a map — "画一下路线图", "把这几个方案画在地图上", "行程示意图", "伦敦每天怎么走画个图", "show the routes on a map", "trip map PDF" — even if they don't say "skill". Planning the itinerary itself is out of scope; this skill only visualises a plan that is already there.
license: MIT
compatibility: python3 (standard library only); network on first run (Natural Earth base map; OpenStreetMap Overpass API for city maps); Google Chrome or Chromium for PNG/PDF.
---

# 行程路线示意图

把会话里已经有的行程方案画成"路线示意图"：国家、地区尺度的底图是 Natural Earth 1:10m 的海岸线和国界；城市尺度（一天的步行、地铁、游船路线）自动换成 OpenStreetMap 的街道、河流、公园和铁路。每个方案（或每一天）一张小图，圆点里写住几晚、旁边写日期，线型区分火车、自驾、航班等。线路是途经点之间的直线，表达"去哪、怎么走、住几晚"，不是导航路线。

制定计划不在这个技能里。如果会话里还没有方案，先和用户把方案定下来，再回到这里。

## 工作流程

1. **把方案整理成 SPEC（JSON）。** 格式见 `references/spec.md`，完整示例见 `examples/uk-three-routes.json`。要点：
   - 每个方案一个 `route`；同一套地点放在 `places` 里共用。
   - 熟悉的地点直接写 `lonlat`（经度在前，4 位小数足够）。拿不准的写 `wiki`（英文维基条目名），脚本会去查条目坐标并缓存。坐标写错比不写更糟，宁可用 `wiki`。
   - 路段的 `via` 里可以夹匿名途经点 `[lon, lat]`，让线大致沿着真实走向（铁路沿海岸、公路绕山口），这些点不画圆点。
   - 住宿点写 `nights`，机场写 `"kind": "air"`，景点不写（默认途经点）。日期放在 `sub` 里，例如 `"12/25–29"`。
   - 国际航班的另一端（比如飞往别的国家）只写在 leg 的 `via` 里，不要放进 `stops`，否则地图范围会被拉到另一个国家。

2. **运行脚本。** 脚本在本技能目录的 `scripts/` 下：

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/route_map.py" SPEC.json --out OUTDIR --png
   ```

   `--png` 每个方案一张 PNG，`--pdf` 整页 PDF，`--svg` 每个方案一个 SVG，`--fragment` 输出可以嵌进已有网页的片段（`maps.fragment.html` + `maps.css`）。`maps.html` 总会生成。`--png-scale 3` 可以把 PNG 再放大。

3. **看一眼再交付。** 用 Read 打开生成的 PNG（这就是用户会看到的样子），检查：
   - 标注有没有压住别的标注或圆点、有没有被图边切掉。脚本会自动避让：先换方位，放不下就**缩小文字**（同时提高 PNG 分辨率，字在图上的像素大小不变，HTML 里这张图会占满一行），缩到 0.6 倍仍放不下才把标签挪远并画引线。终端里会提示哪条路线缩放了、还剩几处重叠。
   - 每个标注最后放在哪个方位记在 `OUTDIR/labels.json`（`r`、`tl`、`b+far` 等），`_text_scale` 是这张图的文字缩放。手动修正时在 stop 或 leg 上写 `pos`、`hide_label`，或者在 route / 顶层写 `text_scale`。
   - 两个过夜点离得太近（全国比例尺下的首都和机场）时，圆点会互相压住，缩小文字也救不了：把其中一个改成 `"kind": "air"` 的小菱形，或者给这条路线一张放大的 `bbox`。
   - 一个方案跨度很大、细节都挤在一角时，给它单独的 `bbox` 放大到主要区域，图外的部分用 `notes` 写一句"↓ 伦敦 3 晚在图外"。
   - 航班曲线和别的线重叠时，把 `bend` 改成负数让它往另一侧弯，或者设成 0 画直线。

4. **交付。**
   - 用户要图片或 PDF：给 PNG / PDF 文件路径，或者用文件发送工具发过去。
   - 放进 Artifact 网页：用 `--fragment`，把 `maps.css` 放进页面的 `<style>`，把 `maps.fragment.html` 原样插进页面。片段里所有样式和底图都是内联的，不依赖外部资源，符合 Artifact 的 CSP。片段里的 SVG `id` 是 `trm-focus` / `trm-other`，同一页面只插一次片段。
   - 独立网页：`maps.html` 自带浅色/深色主题，可以直接打开或分享。

## 城市级路线

所有地图都窄于 80 km 时（例如伦敦市内每天一张），脚本自动改用 OpenStreetMap 底图，也可以在顶层写 `"base": "city"` / `"base": "world"` 强制指定。示例：`examples/london-days.json`。

- 地点坐标要准到几十米：城市里两个景点常常只隔两三百米，凭印象写的坐标会把圆点放到河对岸。拿不准就用 `wiki`。
- 步行用 `walk`，地铁用 `metro`，城市游船用 `ferry`，打车用 `transfer`。游船、步行沿河走时，在 `via` 里加几个河道上的匿名点，线才会沿着河弯。
- 住处只有一个、每天都从那里出发时，每张图都把它放进 stops（写同样的 `nights`），读者一眼知道起点。
- 底图数据通过 Overpass API 下载，按范围缓存在 `~/.cache/trip-route-map/osm_*.json`；伦敦市中心约 10 km 见方要下载几十 MB、半分钟左右。范围超过 150 km 会拒绝，改成国家尺度的图。
- OpenStreetMap 的数据要求署名，脚本已经把"© OpenStreetMap contributors"写进图例和每张 PNG 的右下角，交付时不要去掉。

## 设计取舍（为什么这样做）

- **每个方案单独一张图**，比几条线叠在同一张图上更容易比较；需要对照时，在 route 上写 `"bbox": "all"` 让几张图用相同的范围。
- **图的宽高比默认自动**（`aspect: "auto"`），按多数方案的形状在 4:5、1:1、5:4、3:2 里挑一个，所有卡片保持一致。东西向的长路线用竖版会留出大片空白、标注挤在一起。
- **底图只区分"行程所在国家"和"其它国家"**两种灰度，水是浅蓝。地图上的颜色留给路线本身。
- 只用 Python 标准库，不需要安装任何包；底图首次运行时下载到 `~/.cache/trip-route-map/`，之后离线可用。
