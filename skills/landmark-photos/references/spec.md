# landmark_photos.py 的 SPEC 格式

一个 JSON 文件。完整示例：`examples/uk-sights.json`（紧凑小图墙）、`examples/oahu-annotated.json`（解说卡片）。

## 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | | 页面标题 |
| `subtitle` | | 标题下的一行说明（适合写"照片多是夏天拍的"这类提醒） |
| `lang` | | 署名等固定文字的语言，`zh`（默认）或 `en` |
| `wiki_lang` | | `wiki` 字段用哪个语言的维基，默认 `en`（英文维基的首图最稳定）；日本等地的小景点用 `ja`，条目更全 |
| `labels` | | 改解说卡片三栏的小标题，如 `{"why": "看点"}`；默认 `zh` 是「是什么」「为什么去」「适合谁」，`en` 是 What it is / Why go / Who it suits |
| `groups` | 是 | 分组列表 |

## groups[]

| 字段 | 说明 |
|---|---|
| `id` | 组标号，显示在彩色小方块里，如 `"A"`、`"伦"` |
| `title` | 组名 |
| `sub` | 组名后面的小字 |
| `color` | 小方块颜色，如 `"#A3195B"`；解说卡片里也用作标签底色（淡化）和三栏小标题的颜色，深色主题下小标题会自动调亮 |
| `items` | 景点列表 |

## items[]

```json
{"key": "stonehenge", "name": "巨石阵", "note": "约 5000 年前的石圈", "wiki": "Stonehenge"}
{"key": "glencoe", "name": "格伦科", "search": "Three Sisters Glen Coe"}
{"key": "tartan", "name": "第一张彩色照片", "file": "Tartan Ribbon.jpg"}
{"key": "hanauma", "name": "Hanauma Bay", "wiki": "Hanauma Bay",
 "tags": ["要预约", "$25/人", "周一二闭园"],
 "what": "火山口塌进海里形成的圆形海湾，湾里是珊瑚礁保护区。",
 "why": "Oahu 最容易上手的浮潜点：浪小、离岸近、鱼多。",
 "who": "会一点游泳的人；不会游泳的穿救生衣在浅水也能看到鱼。"}
```

| 字段 | 说明 |
|---|---|
| `key` | 文件名用的短名（小写、连字符）。同一个 key 在多个组里出现时只下载一次 |
| `name` | 显示名 |
| `note` | 名字下面的一行备注，可省略 |
| `wiki` | 维基条目名，取条目首图 |
| `search` | Commons 搜索词，取第一个 jpg 结果；`pick` 可以指定取第几个（从 0 开始，和 `candidates` 列出的编号一致）。也是 `candidates` 的搜索词 |
| `file` | 直接指定 Commons 文件名（带不带 `File:` 都行） |
| `wiki_lang` | 只对这一项改用别的语言维基 |
| `photo_note` | 照片拍的不是景点本身时写明，如 `"竜串海岸的砂岩，不是馆内"`。显示为"照片：…"，写在名字下面和署名列表里 |
| `tags` | 解说卡片：名字下面的几个小标签（字符串数组），写时长、费用、要不要预约、开放时间 |
| `what` | 解说卡片「是什么」：客观事实，一两句 |
| `why` | 解说卡片「为什么去」：值得去的理由，一两句 |
| `who` | 解说卡片「适合谁」：适合谁、什么情况可以跳过，一两句 |

`wiki`、`search`、`file` 三选一；同时写时 `file` 优先，其次 `search`。

## 两种版式

| 条件 | 版式 |
|---|---|
| 所有 item 都没有 `what` / `why` / `who` | 紧凑小图墙：名字 + 一行 `note`，`tags` 不显示。和加入解说卡片之前的输出逐字节相同 |
| 任何一项有 `what` / `why` / `who` | 整页改成解说卡片：4:3 照片，下面依次是名字、`note`（有的话）、`tags`、三栏解说；某一项缺哪栏就不显示哪栏 |

解说卡片在 HTML、`--fragment`、PNG、PDF 里都支持：网页每行放得下几张就放几张（每张至少 250px 宽，手机上一列）；PNG 固定 3 列、每张 270px 宽，高度按实际文字渲染后量出来；PDF 每行 3 张。

## 输出目录

| 路径 | 说明 |
|---|---|
| `img/<key>.jpg` | 缩到最长边 420 像素的 JPEG；`fetch --max 960 --format webp` 时是 `img/<key>.webp` |
| `raw/` | Commons 的标准宽度缩略图（≥ `--max` 的最小标准宽度：500、960、1280、1920） |
| `meta.json` | 每张图的文件名、来源页、作者、许可、选图方式、本地文件名 `img`、`max` |
| `candidates.json` / `candidates.html` / `candidates.png` / `candidates/` | `candidates` 生成：每个景点的候选照片 |
| `assets.json` / `credits.fragment.html` | `assets` 生成：data URI 素材和署名列表 |
| `contact.html` / `contact.png` | 检查页（fetch 生成） |
| `gallery.html` / `.png` / `.pdf` / `.fragment.html` + `gallery.css` | build 生成 |
