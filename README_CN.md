# Seedance 2.0 AI 视频生成工作台 (Lite 开源版)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.135.3-teal.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat&logo=python)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**中文版** | [English Version](./README.md)

一个基于 **Seedance 2.0** 构建的可私有化部署、轻量级 AI 视频生成控制台。本项目为开源 Lite 版，使用本地 **SQLite3** 存储数据，支持多模态参考输入和精细化的任务管理。OSS 为可选配置，不配置也可直接使用参考图片功能。
---

## Lite 版 vs Pro 版

| 功能 | Lite 开源版 | Pro 版 |
|------|:-----------:|:------:|
| Seedance 2.0 视频生成 | ✅ | ✅ |
| 对话式工作流 | ✅ | ✅ |
| 媒体库管理 | ✅ | ✅ |
| 本地 SQLite 存储 | ✅ | ✅ |
| 无 OSS 本地模式（参考图片） | ✅ | ✅ |
| 参考视频 / 参考音频 | 需配置 OSS | ✅ |
| 多用户 / 工作区 | ❌ | ✅ |
| 用户配额管理 | ❌ | ✅ |
| Supabase 云数据库 | ❌ | ✅ |
| 字节真人资产库集成 | ❌ | ✅ |
| API Key 接入 | ❌ | ✅ |

> 如需 Pro 版（多用户、配额管理、Supabase 支持），请联系：giordanoshai@gmail.com

---

## 📸 项目预览

### Lite 版界面

#### 核心界面
![主界面预览](screenshot/main.png)

#### 对话与历史
![历史记录](screenshot/history.png)

#### 媒体库管理
![媒体库](screenshot/media.png)

### Pro 版界面预览

#### 主页
![Pro 主页](screenshot/pro_home.png)

#### 媒体库
![Pro 媒体库](screenshot/pro_medialib.png)

#### 用户管理
![Pro 用户管理](screenshot/pro_user.png)

#### 管理后台
![Pro 管理后台](screenshot/pro_admin.png)

---

## ✨ 核心特性

- 🚀 **模型支持**：完整支持 Seedance 2.0 及其多参考输入协议（图片、视频、音频）。
- 💾 **本地存储**：无需复杂数据库，使用 SQLite3 存储对话历史、任务信息及媒体元数据。
- ☁️ **OSS 可选**：OSS 未配置时自动切换本地模式，参考图片以 base64 直传 API，零门槛启动。
- 🖼️ **自动化预览**：自动生成生成的视频关键帧缩略图，提升浏览效率。
- 🔄 **后台异步**：内置任务状态轮询器，自动将火山引擎生成结果转存至本地。
- ⚡ **轻量化设计**：单用户模式，无需登录，开箱即用，适合个人创作。

---

## 🛠️ 安装与部署

### 1. 环境准备
- Python 3.12+
- 系统需安装 **FFmpeg** 并加入系统 PATH（用于视频信息及缩略图提取）。

### 2. 克隆项目
```bash
git clone https://github.com/your-username/seedance2.0_api_web_Lite.git
cd seedance2.0_api_web_Lite
```

### 3. 创建虚拟环境并安装依赖
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install aiosqlite fastapi httpx jinja2 oss2 pillow pydantic python-dotenv python-multipart uvicorn[standard]
```

### 4. 配置 .env

复制 `.env.example` 为 `.env`，按需填写：

```bash
# 必填：火山引擎 API Key
SEEDANCE20_KEY=你的Seedance2.0专属KEY

# 可选：阿里云 OSS（不填则使用本地模式）
OSS_KEY_ID=
OSS_ACCESSKEY=
OSS_BUCKET_NAME=
```

#### 两种运行模式说明

| 模式 | 触发条件 | 参考图片 | 参考视频 | 参考音频 |
|------|---------|:--------:|:--------:|:--------:|
| **本地模式**（默认） | OSS 三项配置留空 | ✅ base64 直传 | ❌ | ❌ |
| **OSS 模式** | 填写 OSS_KEY_ID / OSS_ACCESSKEY / OSS_BUCKET_NAME | ✅ | ✅ | ✅ |

> 两种模式自动检测，无需手动切换。

---

## 🚀 启动应用

```bash
python main.py
# 或
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

默认访问地址：`http://127.0.0.1:8001`

---

## 📁 项目结构

```text
├── app/
│   ├── routers/          # API 路由（任务创建、状态查询、媒体库）
│   ├── static/           # 前端 UI（HTML/JS/CSS）
│   ├── template/         # Jinja2 模版
│   ├── config.py         # 配置文件（含 OSS_ENABLED 自动检测）
│   ├── database.py       # SQLite3 交互
│   ├── oss_client.py     # 双模式存储路由（OSS / 本地 + base64）
│   ├── task_worker.py    # 后台轮询器
│   └── volcano_api.py    # 火山引擎 API 封装
├── data/                 # 数据库文件
├── outputs/              # 本地生成的视频、缩略图与上传素材
├── screenshot/           # 项目截图
├── main.py               # 程序入口
└── .env.example          # 配置模版
```

---

## 🤝 贡献与反馈

如果这个项目对你有帮助，欢迎 Star 或提交 Pull Request。

---

## ⚠️ 免责声明

本项目基于火山引擎与 Seedance API 开发，生成内容版权归原作者所有。请在使用过程中遵守相关法律法规及平台规定。
