# 套件契约

## 产物与字段

```text
<suite>/
  cover.html
  catalog.html
  transition.html
  content.html
  ending.html
  design_token.txt
  design-analysis.json
  assets/                  # 本地素材，随套件包携带
  assets-manifest.json     # package_suite.py 生成
  suite.json               # API payload
  suite.zip                # 六个主文件、分析、素材和清单
```

`cover/transition/catalog/ending.html` 分别对应同名 API 字段，`content.html` 对应 `header_footer`，`design_token.txt` 对应 `design_tokens`。JSON 还有 `suite_name`、`description`、`tags`。此为随 Skill 固化的 clawpartner 导入契约：`POST /api/template-suites` 接收这些字段（`suite_name/cover/transition/header_footer` 必需，其余页面和元数据可选）。本 Skill 输出始终补齐五种页型，不自动调用 API，也不导入项目代码。只有对接其他版本服务器时才核对其契约。

随包 `assets/reference-suite/` 提供全部五类槽位、正文安全区和来源分析的中性结构示例，不包含项目图片、远程图床或业务数据。它用于理解文件结构及独立冒烟验证；制作实际套件时必须换成输入来源的设计语言。

每个模板为独立 UTF-8 HTML，固定画布 1280×720，`box-sizing:border-box`，画布隐藏越界；不含 JS、事件处理器或外链 CSS，CSS 随文件内联。PPTX 不同画幅统一等比缩放、居中补边；已有页型不重新排版。HTML 长页面按设计语言重排。不变形缩放品牌 Logo。用真实 DOM 文本、形状和图片，不得整页截图代替可编辑模板。

## 槽位

| 文件 | 必备槽位 |
| --- | --- |
| cover.html | `{{ cover_title }}`、`{{ cover_subtitle }}`、`{{ cover_extra }}` |
| catalog.html | `{{ catalog_title }}`、`{{ catalog_subtitle }}`、`{{ catalog_extra }}` |
| transition.html | `{{ transition_title }}`、`{{ transition_subtitle }}`、`{{ transition_extra }}` |
| ending.html | `{{ ending_title }}`、`{{ ending_subtitle }}`、`{{ ending_extra }}` |
| content.html | `{{ page_title }}`、`{{ page_content }}`、`{{ current_page_number }}` |

`{{ total_page_count }}` 可选。品牌文案可用 `{{ brand_org }}`、`{{ brand_tagline }}`、`{{ brand_attribution }}`、`{{ brand_year }}`；章节编号可用 `{{ chapter_number }}`。按实际来源使用，不凭空发明动态槽位。

目录必须有带编号的示例条目和布局，不能留下 `catalog_items` 槽位。内容页只有固定视觉骨架，正文仅一个 `page_content` 插槽，置于唯一 `.suite-stage`；它必须明确 `position:absolute;left:...px;top:...px;width:...px;height:...px;overflow:hidden`，不得侵入页眉页脚。正文 CSS 作用域限制在 `.suite-stage`，不让全局规则破坏后续动态内容。`page_content` 不能转义为普通文本或塞入属性。

## PPTX 几何锁定

PPTX 需声明 source_kind 为 pptx，adapted 页面通过 build_pptx_suite.py 从源证据直接绑定，保留 geometry-lock.json、source-samples.json、source-provenance.json；三者均随 ZIP 交付。源标题/图片/线条的 DOM、CSS 和层序由打包器检查。源文件没有 extra/subtitle 区域时允许 hidden 槽位，不添加可见框。源图片中只有内嵌文字而无文本框时，新增可编辑文案属于 synthesized；不能把图片文字伪报为原稿可编辑文本。详见 [pptx-precision.md](pptx-precision.md)。

## 来源分析

`design-analysis.json` 至少包含 `palette`、`typography`、`layout`、`pages`。`pages` 下五个键是 `cover/catalog/transition/content/ending`；每项含 `method`（`adapted` 或 `synthesized`）、`source_pages`（来源序号或 HTML 模块标识）和 `reason`。HTML 没有天然页型时，诚实标为 synthesized，不把第一个模块机械认定为封面。

## 相对资源与项目导入

便携 HTML 使用 `assets/<hash>.<ext>`。把 HTML 字符串存进 clawpartner 后，这些路径会相对网页 URL 解析，不能直接假定 ZIP 导入器会搬运图片。现有创建 API 接受 JSON，不接受本 Skill 的 ZIP。

交付套件始终使用相对图片地址，HTML 和 assets 一起携带；消费端若只保存 HTML 字符串，需要自行解析素材路径或提供文件服务。打包脚本不改写为绝对 URL。
