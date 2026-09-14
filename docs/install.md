# 安装

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：从零把「小焦 XiaoJiao」装起来并跑通。本文覆盖环境要求、手动安装、一键安装（`install_all.py`）的检测分级、安装校验、迁移换机与常见安装故障；只想尽快看到界面请直接看 [快速开始](quickstart.md)。

## 目录

1. [环境要求](#1-环境要求)
2. [手动安装](#2-手动安装)
3. [一键安装](#3-一键安装install_allpy)
4. [安装校验](#4-安装校验)
5. [常见安装问题](#5-常见安装问题)
6. [换电脑迁移](#6-换电脑与迁移)
7. [相关文档](#7-相关文档)

---

## 1. 环境要求

| 项 | 要求 |
| --- | --- |
| 操作系统 | Windows 或 Linux（`一键安装.bat` 只适用于 Windows） |
| Python | 3.10 及以上，推荐 3.13（见 `requirements.txt` 顶部说明） |
| 大脑模型 | 二选一：任意 GGUF 本地模型，或任意 OpenAI 兼容接口（`base_url` + `api_key` + `model`） |
| 显卡 | 非必需。CPU 也能对话；有 NVIDIA 显卡时本地推理与视频生成明显更快，显存需求随所选模型规模变化 |
| 其它 | 抓取插件的浏览器渲染、`.js` 插件需要额外组件，均属可选（见 [工具清单](tools.md)） |

小焦本身不绑定具体模型：换模型只改配置，人设、工具、记忆这些"壳"不变。

## 2. 手动安装

### 2.1 获取代码

```powershell
git clone https://github.com/jiangchuangege/xiaojiao-harness
cd xiaojiao-harness
```

### 2.2 安装 Python 依赖

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` 是宽松版本范围，主要包含：

| 包 | 用途 |
| --- | --- |
| `torch` | 自研小模型（MiniGPT，项目里称"小脑"）的训练与推理 |
| `flask` | Web 服务（默认端口 5000）与 `/v1` 接口 |
| `requests` | HTTP 调用：本地大脑、云端大脑、联网搜索 |
| `numpy` | 通用数组运算 |
| `jieba` | 中文分词（记忆、检索、自学习） |
| `scrapling` / `markdownify` / `mcp` | 网页抓取插件（`plugins/scrapling_bridge.py`） |
| `chatterbox-tts` / `soundfile` | 播客配音（可选） |
| `diffusers` / `transformers` / `accelerate` | 播客与视频封面图（可选） |

需要完全一致的环境时改用锁定文件：

```powershell
python -m pip install -r requirements.lock
```

### 2.3 生成控制文件

控制文件是配置的统一入口，仓库只提供模板：

```powershell
copy xiaojiao_control.json.example xiaojiao_control.json
```

该文件含本地密钥，已被 `.gitignore` 忽略，不要提交。关键字段：

| 字段 | 说明 |
| --- | --- |
| `brain.engine` | `auto`（默认，自动判断）/ `llama`（本地大模型）/ `api`（外接 OpenAI 兼容接口）/ `xiaojiao`（自研小脑，能力弱，不推荐日常使用） |
| `brain.llama.server` | `llama-server.exe` 路径；留空则自动探测 |
| `brain.llama.gguf` | 本地大脑 GGUF 路径；留空则自动探测 |
| `brain.llama.ctx` | 上下文窗口，默认 20224 |
| `brain.api.base_url` / `model` / `api_key` | 外接 OpenAI 兼容接口；`api_key` 支持写 `env:变量名` 表示从环境变量读取 |
| `brain.xiaojiao.model_path` / `vocab_path` / `config_path` | 小脑三件套路径；留空则自动探测 |
| `capabilities.plugins` | **对象**，形如 `{"插件名": true}`；不要写成布尔值 `true`，否则启动加载插件时会直接报错 |
| `capabilities.full_access` | `false`（默认）= 危险命令先询问；`true` = 直接执行，不建议 |
| 人设（`role`） | 人设文本，决定角色设定与回答方式 |

### 2.4 启动

```powershell
python start_xiaojiao.py
```

启动器按顺序做五件事：拉起 llama-swap（默认 9292）、拉起本地大脑、启动 Web（默认 5000）、打开浏览器、询问是否同时启动 N.E.K.O. 桌面端（48911/48912）。详细分工见 [快速开始](quickstart.md)。

### 2.5 打开界面

浏览器访问 `http://127.0.0.1:5000`。默认只监听本机回环地址。

## 3. 一键安装（`install_all.py`）

```powershell
python install_all.py
```

Windows 上也可以双击 `一键安装.bat`（它只做一件事：调用 `install_all.py`）。

另有一个精简版安装器 `install_auto.py`，只做三步：装依赖 → 检查大模型路径 → 启动小焦。需要完整检测与自动下载时用 `install_all.py`。

### 3.1 检测项

`install_all.py` 按 11 个编号步骤执行，顺序为：

| 步骤 | 检测/动作 | 分级 |
| --- | --- | --- |
| 1 | Python 依赖（`pip install -r requirements.txt`） | 必需 |
| 2 | llama.cpp（`llama-server.exe`），找不到则自动下载最新版便携包 | 必需 |
| 3 | 大脑模型：本地 GGUF 或云端 OpenAI 兼容接口，按协议真探测一次 | 必需 |
| 3b | 小脑（自研 MiniGPT，项目核心）：`*.pth` + `vocab*.pkl`（+ `model_config*.json`） | 必需 |
| 4 | llama-swap（多大脑热切换管理器），找不到则自动下载 | 必需 |
| 5 | ComfyUI（视频大脑） | 可选 |
| 5b | 视频节点：`ComfyUI-AnyDeviceOffload`、`ComfyUI-WanVideoWrapper` | 可选 |
| 6 | Wan2.1 视频模型三件套（`dit_fp8` / `umt5_fp8` / `vae_fp8`，约 2.5 GB，下载前先询问） | 可选 |
| 7 | Node.js（`.js` 插件用） | 可选 |
| 8 | NVIDIA GPU（`nvidia-smi`，只打印结果，不计入通过与否） | 仅报告 |
| 8b | 可选功能依赖：N.E.K.O. 桌面端、Chatterbox（配音）、diffusers（封面）、`music_service`（音乐） | 可选 |

### 3.2 分级结果

脚本最后按两组分别打印结论：

| 分组 | 包含 | 缺失的后果 |
| --- | --- | --- |
| 必需 | Python 依赖、llama.cpp（`llama-server.exe`）、大脑模型（本地或云端，需协议连通）、小脑模型（`*.pth` + `vocab*.pkl`，缺 `xiaojiao_harness.py` 也会报）、llama-swap | 无法进入小焦，脚本会点名缺什么、怎么补 |
| 可选 | ComfyUI、视频节点、Wan 视频模型、Node.js、N.E.K.O.、Chatterbox、diffusers、`music_service` | 只少对应功能，不拦启动 |

必需项齐全时，脚本提示可以启动，并询问是否立刻运行 `start_xiaojiao.py`。

### 3.3 路径不改代码

所有路径都靠探测或配置，不写死在代码里：

| 组件 | 解析顺序 |
| --- | --- |
| llama-server / llama-swap / ComfyUI | 控制文件（存在才用）→ 环境变量 → PATH / 各盘符关键词扫描 |
| 大脑 GGUF | 控制文件 `brain.llama.gguf` → 环境变量 → 常见目录与全盘按关键词、体积探测 |
| 小脑三件套 | `XIAOJIAO_BRAIN_MODEL` / `XIAOJIAO_BRAIN_VOCAB` / `XIAOJIAO_BRAIN_CONFIG` → 控制文件 `brain.xiaojiao` → 项目目录 glob → 全盘探测（`*.pth` 按体积优先，并与 `vocab*.pkl` 配对） |
| 视频模型根目录 | `XIAOJIAO_VIDEO_ROOT` → 自动探测（找含 `dit_fp8.safetensors` 的目录）→ 项目中新建 `video_models/` |

各组件的路径探测中，小脑以 `*.pth` 为主：换任意自训模型后只需改 `brain.xiaojiao`，代码不动。

### 3.4 模型检测判据：协议连通

安装向导与「装小焦体检」都不只看"配置里填没填"，而是真发一次请求：

- 本地大脑：先看端口是否在线；在线则按 OpenAI 兼容协议真探测一次。
- 本地文件齐但服务没起：判定为"文件就绪，启动 `start_xiaojiao` 后会自动拉起大脑"。
- 云端接口：`install_all.py` 的 `test_cloud_api()` 先试 `GET /models`，若返回 405/404 再回退发一次最小 `POST /chat/completions`；两者都通才算通过。
- 未配置任何可用大脑时会交互式询问是否现在填一个云端接口，填完立即实测，通过才写入控制文件。

检测函数的完整说明见 [依赖与模型检测](dependency-check.md)。

## 4. 安装校验

三种方式任选：

| 方式 | 做法 |
| --- | --- |
| 环境体检页 | 启动后访问 `GET /api/env`，返回逐项 `ok` 与缺失清单（含"怎么补"） |
| 对话询问 | 对 N.E.K.O. 桌面端说「装小焦体检」，它读取 `/api/env` 转述结果 |
| 云端大脑专项体检 | `python tools/check_cloud_brain.py`（判据只看 `POST /chat/completions`，见 [常见问题](faq.md)） |

## 5. 常见安装问题

| 现象 | 处理 |
| --- | --- |
| 端口被占用 | 默认需要 5000（Web）与 9292（llama-swap）空闲，先用 `netstat` 或 `tools/check_cloud_brain.py` 之外的端口检查手段确认 |
| 显存不足（CUDA OOM） | 调小 `xiaojiao_control.json` 的 `brain.llama.ctx`，例如从 32768 降到 16384；或改用云端 `brain.api` |
| 只想用云端接口 | `brain.engine` 设为 `api`，填好 `brain.api.base_url` / `api_key` / `model` |
| 找不到 `llama-swap.exe` | 设 `XIAOJIAO_LLAMA_SWAP` 指向该文件，或把 `llama-swap.exe` 放到项目目录 / `llama-swap/` 子目录 |
| 找不到大脑模型 | 把 GGUF 放到项目目录、`C:/llama`、用户目录或 `Downloads`，或直接填 `brain.llama.gguf` |
| 插件加载后启动报错 | 检查 `capabilities.plugins` 是否为对象（见 [2.3](#23-生成控制文件)） |

## 6. 换电脑与迁移

代码里没有必须修改的绝对路径，三种方式任选：

| 方式 | 做法 |
| --- | --- |
| 自动查找 | 把 `llama-server.exe` 与模型 GGUF 放到 `C:/llama`、项目目录、用户目录或 `Downloads`，启动器会自动找到 |
| 环境变量 | 见下表 |
| 控制文件 | 直接改 `xiaojiao_control.json` 的 `brain.llama.server` / `gguf` / `port`、`brain.xiaojiao.*`、`scrapling.*` |

常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `XIAOJIAO_LLAMA_SERVER` | `llama-server.exe` 路径 |
| `XIAOJIAO_GGUF` | 聊天大脑 GGUF 路径（`start_xiaojiao.py`、`brain_manager.py` 读这个；体检接口 `/api/env` 另读 `XIAOJIAO_LLAMA_GGUF`） |
| `XIAOJIAO_LLAMA_SWAP` | `llama-swap.exe` 路径 |
| `XIAOJIAO_BRAIN_MODEL` / `XIAOJIAO_BRAIN_VOCAB` / `XIAOJIAO_BRAIN_CONFIG` | 小脑三件套路径 |
| `XIAOJIAO_COMFY_DIR` / `XIAOJIAO_VIDEO_ROOT` | ComfyUI 目录 / 视频模型总目录 |
| `XIAOJIAO_NEKO_DIR` / `XIAOJIAO_NEKO_AUTO` | N.E.K.O. 目录 / 设为 `1` 时启动不再询问、直接拉起 |
| `LLAMA_API` | 蒸馏脚本调用的 llama-swap 接口 |
| `LLM_BASE_URL` | 未提供控制文件时使用的 OpenAI 兼容接口地址 |

优先级：控制文件（存在才用）→ 环境变量 → 自动查找。记忆、会话、知识库、插件等数据都存放在项目目录内，复制整个文件夹即可迁移。

## 7. 相关文档

- [快速开始](quickstart.md)：三步跑起来
- [常见问题](faq.md)：模型自述、工具不执行、云端 Key 报错等
- [工具清单](tools.md)：运行时组件、环境变量总表
- [插件开发指南](PLUGINS.md)：插件机制与写法
- [HTTP API](api.md)：接口清单

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
