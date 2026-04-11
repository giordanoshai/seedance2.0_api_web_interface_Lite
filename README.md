# Seedance 2.0 AI 视频生成工作台 (Lite Open Source)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.135.3-teal.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat&logo=python)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**中文版** | [English Version](./README_EN.md)

一个基于 **Seedance 2.0** 构建的可私有化部署、轻量级 AI 视频生成控制台。本项目为开源简化版（Lite），使用本地 **SQLite3** 存储数据，配合 **阿里云 OSS** 管理上传素材，支持多模态参考输入和精细化的任务管理。

如果你需要supabase多用户管理,支持用户生成管理,请联系:giordanoshai@gmail.com
---



## 📸 项目预览

### 核心界面
![主界面预览](screenshot/main.png)
*简洁直观的控制台，支持多种模型参数调整与即时预览。*

### 对话与历史
![历史记录](screenshot/history.png)
*左侧对话列表式管理，任务状态实时轮询更新。*

### 媒体库管理
![媒体库](screenshot/media.png)
*统一管理上传素材与生成结果，支持视频缩略图自动提取与预览。*

---

## ✨ 核心特性

- 🚀 **模型支持**：完整支持 Seedance 2.0 及其多参考输入协议（图片、视频、音频）。
- 💾 **本地存储**：无需复杂数据库，使用 SQLite3 存储对话历史、任务信息及媒体元数据。
- ☁️ **云端联动**：利用阿里云 OSS 存储海量参考素材，确保 API 调用时的稳定性。
- 🖼️ **自动化预览**：自动生成生成的视频关键帧缩略图，提升浏览效率。
- 🔄 **后台异步**：内置任务状态轮询器，自动将火山引擎生成结果转存至本地。
- ⚡ **轻量化设计**：单用户模式，无需登录，开箱即用，适合个人创作。

---

## 🛠️ 安装与部署

### 1. 环境准备
- Python 3.12+ 
- 系统需安装 **FFmpeg** 并加入系统变量（用于视频信息及缩略图提取）。

### 2. 克隆项目
```bash
git clone https://github.com/your-username/seedance2.0_api_web_Lite.git
cd seedance2.0_api_web_Lite
```

### 3. 创建虚拟环境并安装依赖
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# 安装库
pip install -r pyproject.toml # 或者使用 uv/pip 直接安装
# 推荐使用 pip
pip install aiosqlite fastapi httpx jinja2 oss2 pillow pydantic python-dotenv python-multipart uvicorn[standard]
```

### 4. 配置项目
根据 `.env.example` 创建项目根目录下的 `.env` 文件，或者直接编辑 `app/config.py`：

```bash
# 核心配置项,我这里默认用的是上海的OSS，根据你的实际情况来修改。
OSS_KEY_ID=你的阿里云AccessKeyId
OSS_ACCESSKEY=你的阿里云AccessKeySecret
OSS_BUCKET_NAME=你的Bucket名
OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com
OSS_URI=your-bucket.oss-cn-shanghai.aliyuncs.com

SEEDANCE20_KEY=你的Seedance2.0专属KEY 
SEEDANCE20_URL=默认已填官方地址
```

---

## 🚀 启动应用

运行主程序：
```bash
python main.py
```
默认访问地址：`http://127.0.0.1:8001/static/generator/index.html` (或根据 main.py 中的路由查看)。

---

## 📁 项目结构

```text
├── app/
│   ├── routers/          # API 路由 (任务创建、状态查询、媒体库)
│   ├── static/           # 前端 UI (HTML/JS/CSS)
│   ├── template/         # Jinja2 模版
│   ├── config.py         # 配置文件
│   ├── database.py       # SQLite3 交互
│   ├── oss_client.py     # 阿里云 OSS 与本地存储路由
│   ├── task_worker.py    # 后台轮询器
│   └── volcano_api.py    # 封装的火山引擎 API
├── data/                 # 数据库文件所在目录
├── outputs/              # 本地生成的视频与缩略图
├── screenshot/           # 项目截图
├── main.py               # 程序入口
└── pyproject.toml        # 依赖管理
```

---

## 🤝 贡献与反馈
如果你觉得该项目对你有帮助，欢迎给出 Star 或提交 Pull Request。

---

## ⚠️ 免责声明
本项目基于火山引擎与 Seedance API 开发，生成的视频版权归原作者所有。请在使用过程中遵守相关法律法规及平台规定。
