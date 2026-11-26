# 独立运行与迁移

整个 `clawpartner-suite-maker/` 目录就是可迁移单元。保持内部相对层级，复制到新环境的 Skill 目录即可；不依赖原仓库、原机器用户名、数据库、`.env`、服务端或示例输入。也可让支持 Skill 的代理直接读取目录中的 `SKILL.md`。

```text
clawpartner-suite-maker/
  SKILL.md
  agents/openai.yaml
  references/                 # 契约、本地图片、独立运行
  assets/reference-suite/     # 中性五页型示例，非默认设计风格
  scripts/
    prepare_source.py         # HTML/OOXML 素材与结构提取
    pptx_fidelity.py          # 继承字体、图层、坐标、裁剪、线型
    font_units.py             # 实际PPT物理尺寸换算、导出逆公式诊断
    build_pptx_suite.py       # 已有页型直接绑定槽位
    pptx_lock.py              # 防止后续改写源元素几何和样式
    verify_pptx_fidelity.py   # 源几何、平台字体、原生像素对照
    render_ppt_reference.ps1  # 可选 Windows PowerPoint 只读参考导出
    assets.py                 # 本地资源提取与路径处理
    package_suite.py          # 契约检查、JSON/ZIP
    render_preview.py         # 可选预览与结构检查
    smoke_test.py             # 自带样本，不读取仓库
    requirements.txt
    requirements-preview.txt
```

不要迁移 `.venv/`、`__pycache__/`、生成的套件或来源输入到 Skill。输入文件及其配套素材由使用者提供，解析产物、模板和截图写到工作目录。Python、浏览器和转换器是宿主依赖，不能靠复制源码文件替代安装。

## 基础环境

Python 3.11+；以下 `python` 指新环境中已选定的虚拟环境解释器。`<skill>` 必须换成复制后目录的绝对路径，命令不要求在 Skill 或仓库内执行：

```text
python -m venv .venv
# 激活 .venv，或用它的 Python 绝对路径替代下文 python
python -m pip install -r "<skill>/scripts/requirements.txt"
python "<skill>/scripts/smoke_test.py"
```

冒烟脚本在临时目录自行创建 HTML、图片和 PPTX，验证来源解析、参考套件槽位、图片相对路径与打包，工作结束自动清理；可用 `--work-dir <空目录>` 保留证据。无需 pytest 或任何仓库文件。不调用 LLM。

## 实际使用

```text
python "<skill>/scripts/prepare_source.py" --input "/path/to/input.html" --output "output/my-style-source"
# 代理读取 source.json/source.html/assets，按 SKILL.md 设计五类模板
python "<skill>/scripts/package_suite.py" --suite-dir "output/my-style" --name "我的套件"
```

准备完素材不等于已经生成模板；风格理解、页型补齐和 HTML 设计由调用 Skill 的模型执行。参考套件不是风格转换器。

PPTX 已有页面使用 [原稿保真路径](pptx-precision.md) 的直接槽位绑定，不重新设计。核心解析/绑定/锁定检查不依赖 Windows；原生 PowerPoint 参考导出是可选验证。源字体是宿主依赖，缺失时报告字体回退，不宣称像素级一致。

## 可选视觉预览

```text
python -m pip install -r "<skill>/scripts/requirements-preview.txt"
python -m playwright install chromium
python "<skill>/scripts/render_preview.py" --suite-dir "output/my-style"
```

已有 Edge/Chrome 时可用 `--channel msedge` / `--channel chrome`，或 `--executable-path <浏览器绝对路径>`，无需固定 Windows 安装路径。Playwright 与浏览器只在视觉预览阶段需要；不影响提取和打包。无可用浏览器时报告未做视觉验收。

`--samples samples.json` 接收 `{ "slot_name": "示例文案" }` 对象，用于长文案、品牌文案或正文 HTML 检查；缺省槽位使用通用示例。预览写入套件的 `preview/`：`index.html`、逐页 HTML/PNG 和 `verification.json`。预览 HTML 以相对 base 寻址素材，不写入本机绝对路径。脚本不修改正式模板，当前打包脚本的 ZIP 不包含 preview，需单独携带预览或将整个输出目录分享。

## 可选 PPT 转换

OOXML 的 PPTX（即使后缀 .ppt）直接读取；二进制 .ppt 需要宿主安装 LibreOffice 或 PowerPoint 再转换。不将 Office 安装文件或宿主工具路径打包进 Skill。
