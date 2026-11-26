# PPTX 原稿保真路径

本路径用于来源中已经存在的页型。缺失页型仍提炼同一来源风格设计，并标注 synthesized。不要为长标题或“阅读性”更改已有静态骨架；文案溢出应缩减或拆页，不移动标题、缩放图片、改虚线或重新设计原稿。

## 源证据与单位

当前 prepare_source.py 输出 evidence_version:2：包括母版、布局、页面图层、唯一元素 ID、原始 EMU 尺寸、有效框/变换矩阵、文本框内边距和锚点、段落/run 的继承字号/字体/字距、颜色、线宽/虚线、图片裁剪和透明度。读取 source.json、OOXML、warnings 和源截图，不要仅凭缩略图估算。

统一比例 `s=min(1280/slide_width_emu,720/slide_height_emu)`；坐标等比缩放并居中补边；字号 `font_px=font_pt*12700*s`。只有原始物理宽960pt、目标宽1280px时才等于 `pt*4/3`。不能 pt 直接当 px，也不能分别拉伸横纵轴。

此通用公式已与项目 HTML→PPT 导出逻辑逆向核对：项目10英寸宽PPT的1280px反算比例是16/9，非4/3。换算集中在 scripts/font_units.py，每个run同时记录font_size_pt和font_size_px。舍入范围、公式推导与限制见 [font-export-inverse.md](font-export-inverse.md)。

组形状必须递归应用 off/ext/chOff/chExt；内部坐标单位不一定是物理 EMU，不能以子框坐标代替全局位置或按内部单位比例放大字体。图片保留位置、宽高、旋转、翻转、srcRect 裁剪、alphaModFix透明度和层序，不能改成 height:auto 或随意使用 cover/contain。线条保留两个端点、宽度、颜色、cap、dash；贯穿虚线不能改成有边距的实线。

解析器仍不是完整 Office 渲染器。特殊几何、复杂效果、图表、主题变体、字体缺失等需要专项处理。检查 warnings 和原生参考，遇到未支持内容不能静默宣称像素级一致。输入图片上的文字不等于可编辑源文本。

## 直接绑定已有页型

按实际 source.json 选择页型和元素 ID，写 page-map.json：

```json
{
  "cover": {"slide":1,"slots":{"cover_title":"s1-slide-5","cover_subtitle":"s1-slide-21"}},
  "transition": {"slide":3,"slots":{"transition_title":"s3-slide-7","transition_subtitle":"s3-slide-2"}},
  "content": {"slide":4,"slots":{"page_title":"s4-slide-2","page_content":"s4-slide-7"}}
}
```

这些 ID 只是格式示例，必须读取本次输入确定。主副标题按语义而非上下位置绑定。来源没有 extra/subtitle/页码区域时保留 hidden 槽位，不能新加可见框。主标题必须绑定可编辑文本；仅有图片文字的页面需另行设计可编辑区并标为 synthesized，不能凭 OCR 猜字号后标为原稿还原。

```text
python "<skill>/scripts/build_pptx_suite.py" --source-dir "output/my-style-source" --page-map page-map.json --output "output/my-style"
```

目标必须为空目录；命令只建立 map 中的页面并返回 remaining_pages。继续制作缺失页型、design-analysis.json 和设计规范，最后仍需五页型。保留三份证据：geometry-lock.json（元素顺序、框、样式、字体、裁剪及 DOM/CSS 指纹）、source-samples.json（原文案）、source-provenance.json（页面来源）。源正文框换成同边界 suite-stage；动态正文不影响标题和固定装饰。

design-analysis.json 设置 `source_kind:"pptx"`。每个 adapted 页都必须有锁。打包器会拒绝源元素丢失、顺序改变、图片裁剪或样式改动；不要重建锁来认可 agent 的手工改动，锁只能由原始 source.json 和绑定生成。数据槽位采用首 run 样式；源混合字体文案如需重新分段，须专项验收。

## 两级验证

基础环境仅依赖 Python；视觉检查安装 requirements-preview.txt 和浏览器。回填原稿同文案，运行：

```text
python "<skill>/scripts/verify_pptx_fidelity.py" --suite-dir "output/my-style" --channel msedge
```

检查实际浏览器元素框（容差0.15px）、字号（0.05px）、本地素材和实际平台字体。不是只看 font-family 声明；源字体被回退替代时会失败。宿主需安装并合法使用源字体，不自动把系统字体打进包。其他系统缺微软雅黑时要明确报告，不以 sans-serif 回退后声称像素级一致。

Windows 安装 PowerPoint 时可只读导出真实参考及文字指标：

```text
powershell -File "<skill>/scripts/render_ppt_reference.ps1" -InputFile input.pptx -OutputDir native-reference
python "<skill>/scripts/prepare_source.py" --input input.pptx --output "output/my-style-source" --native-reference native-reference/native-metrics.json
# 从这份证据重新绑定后运行
python "<skill>/scripts/verify_pptx_fidelity.py" --suite-dir "output/my-style" --channel msedge --native-dir native-reference
```

脚本不修改或保存源 PPT。原生指标用于校准文字行框；没有 PowerPoint 的核心解析仍能读取源坐标和继承字体。其他环境可提供真实 Office/LibreOffice 渲染的1280×720参考图，但须说明渲染器差异；不能以解析器自己的 HTML 截图充当原稿。

像素检查输出差异PNG、平均通道误差和“任一通道差>16”的像素占比。默认3%是回归报警线，可用 --max-changed-fraction 收紧。阈值通过不等于逐像素相同，必须人工查看标题、图片裁剪、虚线等局部，不能靠大面积相同背景掩盖错误。无原生图只报告几何/字体检查；有原生图仍有字体抗锯齿、插值、倒影等差异时，报告真实指标和剩余限制。

保真检查与 render_preview.py 长文案检查分别进行。前者判断同文案原稿一致性，后者判断使用时溢出；不能为了后者通过而更改锁定几何。
