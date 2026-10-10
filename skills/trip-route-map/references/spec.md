# route_map.py 的 SPEC 格式

一个 JSON 文件。完整示例：`examples/uk-three-routes.json`。

## 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | | 页面标题 |
| `subtitle` | | 标题下的一行说明 |
| `lang` | | 图例语言，`zh`（默认）或 `en` |
| `wiki_lang` | | 用 `wiki` 查坐标时的维基语言，默认 `en` |
| `aspect` | | 每张图的宽高比，默认 `"auto"`；也可以写数字，如 `0.8`（4:5 竖版）、`1.5`（3:2 横版） |
| `text_scale` | | 文字和圆点的缩放，默认 `"auto"`（放不下时依次试 1、0.85、0.72、0.6）；写数字则固定 |
| `places` | 是 | 地点表，键是你自己起的短名 |
| `routes` | 是 | 方案列表，每个方案画一张图 |

## places

```json
"LON": {"name": "伦敦", "lonlat": [-0.128, 51.507]},
"EDI": {"name": "爱丁堡", "wiki": "Edinburgh"}
```

- `lonlat`：`[经度, 纬度]`，经度在前。
- `wiki`：维基条目名，脚本查条目坐标（缓存在 `~/.cache/trip-route-map/geocode.json`）。条目没有坐标时会报错，改写 `lonlat`。
- `name`：图上显示的名字；不写就用键名。

## routes[]

| 字段 | 说明 |
|---|---|
| `id` | 卡片左上角的标号，如 `"A"` |
| `title` | 卡片标题 |
| `note` | 卡片下方的一行说明 |
| `highlight` | `true` 时卡片加粗边框（推荐方案） |
| `color` / `color_dark` | 路线颜色（浅色 / 深色主题）；不写就用内置色板 |
| `bbox` | 地图范围 `[西经度, 南纬度, 东经度, 北纬度]`；`"all"` 表示所有方案共用的范围；不写则按本方案的 stops 自动计算 |
| `text_scale` | 只对这张图生效的文字缩放 |
| `legs` | 路段列表 |
| `stops` | 要画圆点的地点 |
| `notes` | 地图上的纯文字注记：`[{"lonlat": [1.2, 56.2], "text": "北海"}]` |

### legs[]

```json
{"mode": "train", "via": ["LON", [-1.14, 53.52], "YORK", "EDI"], "label": "12/30 火车"}
```

| 字段 | 说明 |
|---|---|
| `mode` | `train` 实线、`car` 空心双线、`flight` 虚线弧、`ferry` 点划线、`bus` 短虚线（大巴、跟团）、`day` 圆点线（一日游）、`walk` 细点线、`transfer` 细实线（接送车、机场线） |
| `via` | 途经点：`places` 的键，或匿名坐标 `[lon, lat]`（不画圆点） |
| `label` | 路段上的小字，通常写日期 |
| `label_at` | 标签位置：0–1 的比例（沿路段的长度），或某个地点键；不写时在中点，路段中点在图外时自动挪到图内 |
| `label_pos` | 标签方位，见下文 `pos` |
| `bend` | 只对 `flight`：弧度，默认 0.18；负数往另一侧弯，0 是直线 |
| `optional` | `true` 时半透明（可选的一日游等） |

### stops[]

```json
{"place": "LON", "nights": 5, "sub": "12/25–29"}
{"place": "LGW", "kind": "air", "sub": "12/25 落地"}
{"place": "STONE"}
```

| 字段 | 说明 |
|---|---|
| `place` | `places` 的键 |
| `nights` | 住几晚；有值时画实心圆点并写数字 |
| `kind` | `night`、`air`（菱形，机场）、`pass`（空心小圆点）；不写时有 `nights` 就是 `night`，否则 `pass` |
| `name` | 覆盖 `places` 里的名字 |
| `sub` | 名字后面的小字，通常写日期 |
| `pos` | 标注方位：`r` `l` `t` `b` `tr` `tl` `br` `bl`；加 `+far` 表示挪远并画引线，如 `"bl+far"`。不写则自动选择 |
| `hide_label` | `true` 时只画圆点不写字 |

## 输出

| 文件 | 何时生成 |
|---|---|
| `maps.html` | 总是。浅色/深色主题自适应，卡片网格 + 图例 |
| `labels.json` | 总是。每张图的文字缩放 `_text_scale`、剩余重叠数 `_collisions`、每个标注最后的方位 |
| `map-<id>.png` | `--png`。宽度 = 420 / text_scale CSS 像素 × `--png-scale`（默认 2） |
| `map-<id>.svg` | `--svg`。独立 SVG，样式内联 |
| `maps.pdf` | `--pdf`。A4，浅色 |
| `maps.fragment.html` + `maps.css` | `--fragment`。嵌入已有网页用 |
