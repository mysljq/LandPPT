# 从导出公式反推 HTML 字号

核对当前项目的 DOM 导出器后，普通文本路径为：

```text
PPI = 96
slide = 10 × 5.625 inches
export_scale = min(10 / (root_width_px / 96), 5.625 / (root_height_px / 96))
font_pt = Math.round(font_px * 0.75 * export_scale * 10) / 10
```

来源是导出器的 getTextStyle、processSlide、PPI/版面常量，以及 PptxGenJS 写入 a:rPr/@sz 的逻辑；sz 是百分之一 pt。字体大小在输出到 XML 前保留一位小数。此处只记录已核对的公式，Skill 不需要原仓库。上游导出器如果改变，应重新运行真实导出往返验证后更新这个记录，不盲目跟随固定比例。

对于项目常用1280×720根节点，export_scale=0.75，因而：

```text
font_pt = round_to_0.1(font_px * 0.5625)
font_px ≈ font_pt / 0.5625 = font_pt * 16/9
```

| 原 HTML px | 导出 PPT pt | 反算 px |
| --- | --- | --- |
| 24 | 13.5 | 24 |
| 48 | 27 | 48 |
| 64 | 36 | 64 |
| 14 | 7.9 | 14.044444… |

不能对所有 PPT 套用16/9，也不能固定乘4/3。原生 PPT 的页面可能是其他物理尺寸。通用保真公式始终读取 presentation.xml 的实际 sldSz：

```text
font_px = font_pt * 12700 * min(target_width_px / slide_width_emu,
                               target_height_px / slide_height_emu)
```

项目输出10×5.625英寸，sldSz=9144000×5143500 EMU；目标1280×720时，通用公式恰好得到16/9，是导出公式的反向。原生960×540pt页面则为12192000×6858000 EMU，同样目标得到4/3，因此原生48pt是64px，项目导出的48pt却是85.333333px。以实际文件尺寸为准，不能仅按文件来源名称猜比例。

scripts/font_units.py 提供这两种换算。PPTX 解析器默认使用实际物理尺寸；项目导出 profile 用于解释公式和量化范围，不会取代通用公式：

```text
# 项目普通文本正向换算与反向诊断
python "<skill>/scripts/font_units.py" --font-px 64
python "<skill>/scripts/font_units.py" --font-pt 36
# 任意 PPTX，传真实 EMU 尺寸；root-width/root-height 是目标 HTML 尺寸
python "<skill>/scripts/font_units.py" --font-pt 48 --slide-width-emu 12192000 --slide-height-emu 6858000
```

0.1pt舍入会丢失信息，无法唯一还原原始小数 px。普通1280×720路径的最大量化误差约0.088889px；反算结果是区间中点，不要再次取整。CLI 同时返回原 px 的可能区间。应使用 JS Math.round 的正数规则，不用 Python ties-to-even 的 round 来模拟导出。

字号公式不等于完整排版的逆变换。导出器还会：

- 根据浏览器可用字体映射拉丁/东亚字体和字重。PPT只能反映实际导出字体，不能恢复原先完整CSS候选列表。
- 校准 PPT 字体行距、基线、文本框内边距和单行框宽。不能把字号比率直接套到全部行距或坐标修正上。
- 对 SVG、变换文本或某些特定路径应用额外缩放/舍入。反算物理显示字号不一定等于原始CSS声明字号；原始transform和样式语法未必可恢复。
- Office 后续 AutoFit/手工编辑也可能改变显示。需要结合文本框/段落继承和真实参考图核验，不能只靠一个字号公式保证像素一致。
