# LandPPT - AI驱动的PPT生成平台

[![GitHub stars](https://img.shields.io/github/stars/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/network)
[![GitHub issues](https://img.shields.io/github/issues/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/issues)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg?style=flat-square)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-supported-blue.svg?style=flat-square)](https://hub.docker.com/r/bradleylzh/landppt)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/sligter/LandPPT)

---

如果你对我的项目感兴趣，欢迎联系我！

[![Email](https://img.shields.io/badge/_Email-ai%40yydsapp.com-blue?style=for-the-badge)](mailto:ai@yydsapp.com)

---


[English](README_EN.md) | **中文**

---

##  目录

- [项目简介](#-项目简介)
- [功能特性](#功能特性)
- [快速开始](#-快速开始)
- [使用指南](#-使用指南)
- [配置说明](#-配置说明)
- [常见问题](#-常见问题)
- [许可证](#-许可证)

<div align="center">
  <img src="https://img.pub/p/e810c5680509b4f051a5.png" width="180" alt="LandPPT Logo" />
  <p>
    <b>基于大语言模型（LLM）的智能演示文稿生成平台</b>
  </p>
</div>

LandPPT 是一个基于大语言模型（LLM）的智能演示文稿生成平台，能够自动将文档内容转换为专业的PPT演示文稿。平台集成了多种AI模型、智能图像处理、深度研究功能和丰富的模板系统，提供一站式的AIPPT服务。

[文档指南](http://landppt-doc.52yyds.top/docs)

### 主界面

![image](https://img.pub/p/3accad83a8b624d7cb19.png)

![image](https://img.pub/p/7d5c3c1a4b625abeb4c1.png)

### 生成大纲

![image](https://img.pub/p/a31e4f94c5d2bd577d8d.png)

### 生成效果

![image](https://img.pub/p/e6cffa89a2b532a8514b.png)

![image](https://img.pub/p/9a38b57c6f5f470ad59b.png)

### 在线编辑
![image](https://img.pub/p/6d357a847626f1a55c13.png)

![image](https://img.pub/p/42f84b07850f5aa4aebb.png)

![image](https://img.pub/p/8dccee74d0b85893bd38.png)

![image](https://img.pub/p/aaf483b2507a57db8b35.png)

### 讲稿生成
![image](https://img.pub/p/c53b752e0a6833c0ee87.png)

### 导出效果
![image](https://img.pub/p/62694101810bfa472db9.png)

### 模板生成
![image](https://img.pub/p/892622b3f3cc0d6ad843.png)

## 功能特性

**核心亮点：**

- **一键生成**：主题到完整 PPT 全程自动化，支持并行生成
- **智能配图**：图库 / 网络 / AI 生成三源融合，自动匹配
- **深度研究**：Tavily + SearXNG 双引擎，实时抓取并提取网络信息
- **讲稿与讲解视频**：生成演讲稿，Edge-TTS 逐页讲解，可导出 1080p 视频
- **多格式导出**：PDF / HTML / PPTX / 图片 / DOCX / Markdown
- **自动化就绪**：OpenAI 兼容 API + REST API，支持 API Key 鉴权

**详细能力：**

### 多 AI 提供商支持
- OpenAI GPT 系列、Anthropic Claude、Google Gemini、Azure OpenAI
- 兼容 DeepSeek、Moonshot、Qwen 等 OpenAI 协议平台
- 支持 Ollama 本地模型；按功能角色自定义模型，精准控制成本

### 文件处理与深度研究
- 多格式支持：PDF / Word / Markdown / TXT / Excel / PowerPoint
- MinerU + MarkItDown 高质量解析；Tavily + SearXNG 多引擎检索
- 网页内容深度提取与摘要，多语言实时信息

### 智能图像处理
- 三源获取：本地图库 / 网络搜索（Pixabay、Unsplash）/ AI 生成（DALL-E、SiliconFlow、Pollinations、OpenAI、Gemini）
- AI 自动匹配最合适图像，自动尺寸调整、格式转换、质量优化

### 模板系统
- 全局主模板 + 多样化 AI 布局，通用 / 旅游 / 教育等场景模板
- 上传参考 PPTX 抽取版式；项目级 AI 自适应模板；支持自定义模板

### 项目管理
- 四阶段工作流：需求确认 → 大纲生成 → TODO 追踪 → PPT 生成
- 阶段重跑与恢复；可视化大纲编辑与实时预览；批量处理
- 一键公开分享，分享页支持全屏放映、讲解音频与字幕联动

### Web 界面
- 响应式界面，侧边栏 AI 对话编辑，支持图像上传与视觉分析
- 演讲稿生成（DOCX / Markdown / PPT 备注），全屏放映与 16:9 实时预览

### 平台与运维
- Docker / Compose 单容器与多服务编排；PostgreSQL + Valkey + MinIO 生产栈
- 后台任务系统（PDF / PPTX / 讲解视频）异步执行，多 Worker 容错
- 账号体系：本地账号、GitHub / Linux Do OAuth、邮件验证、注册限流
- 可选积分系统、SMTP / Resend、Cloudflare Turnstile；支持本地部署

##  快速开始

### 系统要求
- Python 3.11+
- SQLite 3
- ffmpeg（讲解视频导出需要）
- Docker (可选)

### 数据库迁移（自动）
- 默认启动时会自动检测并执行数据库迁移（与用户无关），可通过环境变量关闭：`LANDPPT_AUTO_MIGRATE_ON_STARTUP=false`
- 本地默认启动使用 SQLite；只有在显式设置 `DATABASE_URL` 时才切换到 PostgreSQL 等外部数据库
- 多容器/多节点共享同一个数据库时，建议关闭自动迁移，改为单独运行一次迁移作业

### 本地安装

#### 方法一：uv（推荐）

```bash
# 克隆项目
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

# 安装uv（如果尚未安装）
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装依赖
uv sync --extra dev

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置你的 AI API 密钥

# 启动服务（默认监听 8000，使用 SQLite + 内存缓存，无需 PostgreSQL / Valkey）
uv run python run.py
```

#### 方法二：传统pip安装

```bash
# 克隆项目
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

# 创建虚拟环境
python -m venv venv
# 激活虚拟环境
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 安装依赖
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置你的AI API密钥

# 启动服务（默认监听 8000，默认使用 SQLite + memory cache，无需 PostgreSQL / Valkey）
python run.py
```

### Docker部署

#### 使用预构建镜像（推荐）

```bash
# 拉取最新镜像
docker pull bradleylzh/landppt:latest

# 运行容器
docker run -d \
  --name landppt \
  -p 8000:8000 \
  -v $(pwd)/.env:/app/.env \
  -v landppt_data:/app/data \
  -v landppt_uploads:/app/uploads \
  -v landppt_reports:/app/research_reports \
  -v landppt_cache:/app/temp \
  -v landppt_lib:/app/lib \
  bradleylzh/landppt:latest

# 查看日志
docker logs -f landppt
```

> **注意**: 确保在运行前创建并配置好 `.env` 文件，包含必要的API密钥。

#### 使用 Docker Compose（推荐生产部署）

仓库内自带 `docker-compose.yml`，使用预构建镜像同时启动 `landppt`（Web 服务）、`worker`（后台任务队列）、PostgreSQL、Valkey 和 MinIO（S3 对象存储，`minio-init` 会自动创建存储桶），适合多用户、后台任务和长期运行场景。若只是本地单机体验，直接运行 `python run.py` / `uv run python run.py` 即可，默认会使用 SQLite + memory cache，无需额外依赖。

```bash
# 准备配置（compose 会将 .env 挂载进容器，必须先创建）
cp .env.example .env
# 至少补充 AI Key、SECRET_KEY、POSTGRES_PASSWORD

# 启动生产编排（默认使用 bradleylzh/landppt:latest，可用 LANDPPT_IMAGE 覆盖）
docker compose up -d

# 查看日志
docker compose logs -f landppt
```

默认访问地址：`http://localhost:8000`（可用 `LANDPPT_PORT` 修改）；MinIO 控制台：`http://localhost:9001`。

生产编排默认关闭管理员自动初始化，首次部署请设置 `LANDPPT_BOOTSTRAP_ADMIN_ENABLED=true` 及对应账号密码变量。

#### 开发模式（热重载）

开发编排使用 `docker-compose-dev.yaml`，基于本地 Dockerfile 构建镜像，挂载源码目录并启用热重载，适合本地调试。默认会自动初始化管理员账号（`admin` / `admin123`）。

```bash
cp .env.example .env
docker compose -f docker-compose-dev.yaml up -d --build
docker compose -f docker-compose-dev.yaml logs -f landppt
```

默认访问地址：`http://localhost:8000`

##  使用指南

### 1. 访问Web界面
启动服务后，访问以下地址：
- **Web界面**: http://localhost:8000
- **API文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

默认会自动初始化管理员账号（账号 `admin` / 密码 `admin123`），由 `LANDPPT_BOOTSTRAP_ADMIN_*` 环境变量控制；生产部署请务必通过这些变量修改默认账号或关闭自动初始化。

### 2. 配置AI提供商
在设置页面配置你的AI API密钥：
- OpenAI API Key(支持openai 兼容model api，例如deepseek、moonshot、qwen等等)
- Anthropic API Key
- Google API Key
- 或配置本地Ollama服务

### 3. 创建PPT项目
1. **需求确认**：输入主题、选择受众、设置页数范围、选择场景模板
2. **大纲生成**：AI智能生成结构化大纲，支持可视化编辑
3. **内容研究**：可选择启用深度研究功能，获取最新相关信息
4. **图像配置**：配置图像获取方式（本地/网络/AI生成）
5. **PPT生成**：基于大纲生成完整的HTML演示文稿

### 4. 编辑和导出
- 使用AI聊天功能实时编辑内容和样式，支持图像上传进行视觉参考
- 支持图像替换和优化，AI模板生成可参考上传的图片
- 生成配套演讲稿，支持单页/多页/全部幻灯片模式
- 生成逐页讲解音频，支持 Edge-TTS 或 ComfyUI Qwen3-TD，并可上传参考音频
- 导出讲解视频（MP4），支持 1080p、30/60fps 与字幕嵌入
- 导出为PDF、HTML、标准 PPTX、图片型 PPTX、演讲稿 DOCX/Markdown 格式
- 支持一键生成公开分享链接，并在分享页中播放讲解音频与字幕
- 保存项目版本和历史记录
- 支持批量处理和模板复用

### 5. 自动化与开放接口
- 支持通过 API Key 将项目流程接入 CI、脚本和自定义后端
- 提供 OpenAI 兼容接口：`/v1/chat/completions`、`/v1/completions`、`/v1/models`
- 提供项目级导出/分享/讲稿接口，适合非浏览器自动化工作流

##  配置说明

### 环境变量配置

主要配置项（常用项见 `.env.example`，高级项可参考 `src/landppt/core/config.py`）：

```bash
# AI提供商配置
DEFAULT_AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GOOGLE_API_KEY=your_google_api_key_here
GOOGLE_BASE_URL=https://generativelanguage.googleapis.com  # 自定义Gemini端点

# 角色级模型路由（可选）
OUTLINE_MODEL_PROVIDER=openai
OUTLINE_MODEL_NAME=gpt-4o-mini
SLIDE_GENERATION_MODEL_PROVIDER=openai
SLIDE_GENERATION_MODEL_NAME=gpt-4o
EDITOR_ASSISTANT_MODEL_PROVIDER=openai
TEMPLATE_GENERATION_MODEL_PROVIDER=openai
SPEECH_SCRIPT_MODEL_PROVIDER=openai
SPEECH_SCRIPT_MODEL_NAME=gpt-4o-mini

# 服务器配置
HOST=0.0.0.0
PORT=8000
SECRET_KEY=your-secure-secret-key
WORKERS=2
RELOAD=false

# 研究功能配置
TAVILY_API_KEY=your_tavily_api_key_here        # Tavily 搜索引擎
TAVILY_BASE_URL=https://gateway.example.com/tavily # 可选：自定义 Tavily 网关/代理地址
SEARXNG_HOST=http://localhost:8888             # SearXNG 实例地址
RESEARCH_PROVIDER=tavily                       # 研究提供商：tavily, searxng, both

# 图像服务配置
ENABLE_IMAGE_SERVICE=false                      # 启用图像服务（默认关闭，按需开启）
IMAGE_USER_STORAGE_QUOTA_MB=100                # 单用户图床存储上限(MB)，<=0 表示不限制
PIXABAY_API_KEY=your_pixabay_api_key_here     # Pixabay 图库
UNSPLASH_ACCESS_KEY=your_unsplash_key_here    # Unsplash 图库
SILICONFLOW_API_KEY=your_siliconflow_key_here # AI图像生成
POLLINATIONS_API_KEY=your_pollinations_api_key_here # Pollinations AI (gen.pollinations.ai)

# 自动化鉴权
LANDPPT_API_KEY=replace-with-strong-random-key
LANDPPT_API_KEYS=admin:prod-key,robot:n8n-key
LANDPPT_BOOTSTRAP_ADMIN_ENABLED=true            # 默认自动初始化 admin 账号，生产环境请修改默认密码或关闭
LANDPPT_ENABLE_API_DOCS=true
LANDPPT_ALLOW_HEADER_SESSION_AUTH=false

# 存储 / 缓存
DATABASE_URL=sqlite:///./landppt.db
CACHE_BACKEND=memory
VALKEY_URL=valkey://localhost:6379
# 生产部署示例：
# DATABASE_URL=postgresql://landppt:password@localhost:5432/landppt
# CACHE_BACKEND=valkey

# 导出功能配置
APRYSE_LICENSE_KEY=your_apryse_key_here       # PPTX导出
COMFYUI_BASE_URL=http://127.0.0.1:8188        # ComfyUI TTS
COMFYUI_TTS_WORKFLOW_PATH=tests/Qwen3-TD-TTS.json

# 注册 / OAuth / 邮件
EMAIL_PROVIDER=smtp
ENABLE_USER_REGISTRATION=true
INVITE_CODE_REQUIRED_FOR_REGISTRATION=false
GITHUB_OAUTH_ENABLED=false
LINUXDO_OAUTH_ENABLED=false
ENABLE_CREDITS_SYSTEM=false
TURNSTILE_ENABLED=false

# 生成参数
MAX_TOKENS=8192
TEMPERATURE=0.7
```

##  贡献指南

欢迎所有形式的贡献！

### 如何贡献
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

详情请见 [贡献指南](CONTRIBUTING.md)。

### 报告问题
如果你发现了bug或有功能建议，请在 [Issues](https://github.com/sligter/LandPPT/issues) 页面创建新的issue。

##  常见问题

### Q: 支持哪些AI模型？
A: 支持 OpenAI GPT(兼容)、Anthropic Claude、Google Gemini、等模型。可以在配置页面切换不同的AI提供商。

### Q: 如何配置图像功能？
A: 在 `.env` 文件中配置相应的API密钥：
- Pixabay: `PIXABAY_API_KEY`
- Unsplash: `UNSPLASH_ACCESS_KEY`
- AI生成: `SILICONFLOW_API_KEY` 或 `POLLINATIONS_API_KEY`

### Q: 使用反向代理（如 Nginx、Apache）时图片链接异常怎么办？
未正确配置 `base_url` 可能导致：图片链接仍显示为 `localhost:8000`、前端无法加载图片、图片预览/下载等功能异常。

**解决方法（通过 Web 界面配置）**：
1. 访问系统配置页面：`https://your-domain.com/ai-config`
2. 切换到"应用配置"标签页
3. 在"基础URL (BASE_URL)"字段中输入您的代理域名，例如 `https://your-domain.com` 或 `http://your-domain.com:8080`
4. 点击"保存应用配置"

### Q: 研究功能如何使用？
A: 配置 `TAVILY_API_KEY` 或部署 SearXNG 实例，然后在创建PPT时启用研究功能即可自动获取相关信息。

### Q: 支持本地部署吗？
A: 完全支持本地部署，可以使用 Docker 或直接安装。支持 Ollama 本地模型，无需依赖外部API。

### Q: 如何导出PPTX格式？
A: 需要配置 `APRYSE_LICENSE_KEY`，然后在导出选项中选择PPTX格式。

### Q: 如何选择标准 PPTX 和图片型 PPTX？
A: 标准 PPTX 依赖 `APRYSE_LICENSE_KEY`，导出后更适合继续编辑；图片型 PPTX 通过截图嵌入页面，复杂 CSS、图标和特殊排版保真更高，但页内元素通常不可再编辑。

### Q: 如何生成公开分享链接？
A: 可在项目编辑页点击分享，或调用 `POST /api/projects/{project_id}/share/generate`。分享地址格式为 `/share/{share_token}`，需要停用时调用 `share/disable` 即可。

### Q: 如何启用开发模式或生产编排？
A: 生产环境推荐 `docker compose up -d` 使用仓库内的 `docker-compose.yml`（预构建镜像，包含 Web、worker、PostgreSQL、Valkey、MinIO）；开发调试推荐 `docker compose -f docker-compose-dev.yaml up -d --build`，本地构建镜像并启用源码挂载和热重载。

### Q: 讲解音频支持哪些方式？
A: 默认支持 Edge-TTS；也可以配置 ComfyUI Qwen3-TD，并在项目编辑页上传参考音频做语音克隆。

### Q: 并行生成会影响PPT质量吗？
A: 不会。并行生成只是改变了生成顺序，每页的生成逻辑和质量保持不变。

### Q: 所有AI提供商都支持批量生成吗？
A: 大多数AI提供商支持并发请求，但可能有不同的限制。建议查看您使用的AI服务的API文档。

##  许可证

本项目采用 Apache License 2.0 许可证。详情请见 [LICENSE](LICENSE) 文件。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=sligter/LandPPT&type=Date)](https://www.star-history.com/#sligter/LandPPT&Date)

##  联系我们

- **项目主页**: https://github.com/sligter/LandPPT
- **问题反馈**: https://github.com/sligter/LandPPT/issues
- **讨论区**: https://github.com/sligter/LandPPT/discussions

---

<div align="center">

**如果这个项目对你有帮助，请给我们一个 :star:！**

Made with :heart: by the LandPPT Team

</div>
