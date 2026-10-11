# landmark_photos.py 的 SPEC 格式

一个 JSON 文件。完整示例：`examples/uk-sights.json`。

## 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | | 页面标题 |
| `subtitle` | | 标题下的一行说明（适合写"照片多是夏天拍的"这类提醒） |
| `lang` | | 署名等固定文字的语言，`zh`（默认）或 `en` |
| `wiki_lang` | | `wiki` 字段用哪个语言的维基，默认 `en`（英文维基的首图最稳定） |
| `groups` | 是 | 分组列表 |

## groups[]

| 字段 | 说明 |
|---|---|
| `id` | 组标号，显示在彩色小方块里，如 `"A"`、`"伦"` |
| `title` | 组名 |
| `sub` | 组名后面的小字 |
| `color` | 小方块颜色，如 `"#A3195B"` |
| `items` | 景点列表 |

## items[]

```json
{"key": "stonehenge", "name": "巨石阵", "note": "约 5000 年前的石圈", "wiki": "Stonehenge"}
{"key": "glencoe", "name": "格伦科", "search": "Three Sisters Glen Coe"}
{"key": "tartan", "name": "第一张彩色照片", "file": "Tartan Ribbon.jpg"}
```

| 字段 | 说明 |
|---|---|
| `key` | 文件名用的短名（小写、连字符）。同一个 key 在多个组里出现时只下载一次 |
| `name` | 显示名 |
| `note` | 名字下面的一行备注，可省略 |
| `wiki` | 维基条目名，取条目首图 |
| `search` | Commons 搜索词，取第一个 jpg 结果；`pick` 可以指定取第几个（从 0 开始） |
| `file` | 直接指定 Commons 文件名（带不带 `File:` 都行） |
| `wiki_lang` | 只对这一项改用别的语言维基 |

`wiki`、`search`、`file` 三选一；同时写时 `file` 优先，其次 `search`。

## 输出目录

| 路径 | 说明 |
|---|---|
| `img/<key>.jpg` | 缩到最长边 420 像素的 JPEG |
| `raw/` | Commons 的 500px 原始缩略图 |
| `meta.json` | 每张图的文件名、来源页、作者、许可、选图方式 |
| `contact.html` / `contact.png` | 检查页（fetch 生成） |
| `gallery.html` / `.png` / `.pdf` / `.fragment.html` + `gallery.css` | build 生成 |
