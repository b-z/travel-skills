# 手账 prompt 模板

`<…>` 是要替换的部分。说明部分用英文（图像模型对英文指令最稳），要画在图上的文字用原文写在 `「」` 或引号里。完整填好的例子：`examples/hawaii-oahu.md`。

用户指定了别的语言时，把第一段的 "All main text is in Japanese" 和各处的日语文字一起换掉；指定了别的风格时，替换 LOCAL DESIGN STYLE 一节和第一段的画风描述。

```
Create a single portrait travel-journal page (A4 vertical, 2:3 ratio, high resolution) in a hand-drawn watercolor scrapbook style: soft watercolor illustrations, ink line details, handwritten-style Japanese text, washi tape, stamps, ticket stubs and small doodles, dense but well-organized layout like a real travel notebook (旅の手帳). All main text is in Japanese. Every place name is written in Japanese with its <当地语言> name underneath, spelled exactly <拼写要求，如 with ʻokina (ʻ) and kahakō (macrons) / in Georgian script / in Kazakh Cyrillic> as given below.

LOCAL DESIGN STYLE (<目的地>):
- <元素 1：画什么 + 用在哪里 + 颜色，如 Corner ornaments in … style: …>
- <元素 2：边框或面板底纹>
- <元素 3：纸胶带图案>
- <元素 4：标题字体的灵感来源>
- <元素 5：页边小涂鸦>
- A postage stamp reading "<邮票文字>" and a round postmark "<地名 · 月份 年份>".
- Color palette: <4–6 个颜色>, cream paper.

TOP AREA:
- Big title: 「<日语标题>」 with subtitle "<罗马字或当地文字 · 日期>"
- Intro line: 「<一句引言>」
- Top right: a hand-drawn map of <区域> with a dotted <交通方式> route, a small <交通工具> icon, and pins labeled:
  <日语名> <当地名> / <日语名> <当地名> / …

MAIN PANELS (each = watercolor illustration + Japanese name + <当地语言> name + 2–3 line handwritten caption):
1. <日语名> / <当地名> — <插画内容：时间、天气、角度、主体>.
   「<第一人称过去式感想，2–3 行>」
2. …
<最有代表性的一个写 (largest panel)；合并面板用子项列出：>
N. <日语名> / <当地名> (largest panel):
   - <子景点日语名> / <当地名>: <插画内容>
   - …
   「<感想>」
<战争、宗教场所的面板加：quiet muted colors, respectful tone.>

FOOD SECTION — title 「<美食区标题>」, <3 或 4> illustrated dishes with short captions:
- <日语菜名> (<当地名或店名>): 「<一句感想>」
- …

SMALL EXTRAS:
- A ticket stub: "<出发地代码 ⇄ 目的地代码  日期>"
- <一两个和这次旅行有关的小物件，如胶片相机、彩虹的拍立得>
- A note card 「旅メモ」 with checkboxes:
  □ <小发现 1>
  □ <小发现 2>
  □ <小发现 3>
  □ <小发现 4>
- Closing card 「旅のまとめ」:
  「<两三句总结，结尾可以用当地语言说谢谢>」

Make sure all Japanese text is legible and correctly written, <当地语言> names keep their <变音符或字母>, and nothing overlaps or gets cut off at the edges.
```

## 分两页时

两段 prompt 第一段和 LOCAL DESIGN STYLE 完全相同；标题写成「<标题> 1/2」「<标题> 2/2」；地图只放在第一页；美食区、旅メモ、旅のまとめ 放在第二页。
