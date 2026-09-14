# 小焦项目知识库

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：面向 AI 的项目背景资料，用于让模型在对话中准确介绍"小焦"这个项目本身：定位、模块、大脑切换、各子服务、部署方式与常用接口。内容随代码更新维护；文中涉及的能力都标注了对应的代码位置。

## 目录

1. [定位](#1-定位)
2. [核心模块](#2-核心模块)
3. [大脑](#3-大脑)
4. [视频生成](#4-视频生成)
5. [播客生成](#5-播客生成)
6. [音乐生成](#6-音乐生成)
7. [桌面端与互相学习](#7-桌面端与互相学习)
8. [部署与启动](#8-部署与启动)
9. [常用接口速查](#9-常用接口速查)
10. [人格](#10-人格)

---

## 1. 定位

小焦是一个本地优先的 AI 助手：底层使用使用者自己的大模型（本地 GGUF 推理，或任意 OpenAI 兼容接口），上层提供人设、记忆、工具与插件，并支持在多个大脑（聊天、编码、视频、播客等）之间切换。

它同时具备两类能力：

- 对话：联网检索、长期记忆、可配置人格；
- 执行：写文件、跑命令、抓网页、生成视频与音频。

## 2. 核心模块

以下模块位于项目根目录，除特殊说明外均为 Python。

| 文件或目录 | 作用 |
| --- | --- |
| `xiaojiao_app.py` | 主应用（Flask，默认端口 5000）：Web 界面、人设、工具、记忆、会话、`/v1` OpenAI 兼容接口 |
| `start_xiaojiao.py` | 启动器：拉起 llama-swap、本地大脑、Web、N.E.K.O. 桌面端 |
| `brain_manager.py` | 多大脑调度：大脑注册表与 RUN / WARM / OFF 状态迁移 |
| `xiaojiao_harness.py` | 自研小模型（MiniGPT）的加载与推理 |
| `xiaojiao_control.json.example` | 控制文件模板：人格、大脑、模型、行为参数 |
| `video_service/` | 文生视频：本地 ComfyUI + Wan2.1，或云端接口，按需切换 |
| `podcast_service/` | 播客生成：写稿 → 配音 → 拼接 → 封面 |
| `music_service/` | ACE-Step 音乐调用封装（模块形式提供，未接入主程序） |
| `plugins/` | 插件目录：Python / JavaScript / JSON / Markdown 四类插件 |
| `core/` | 载体与治理层：能力登记、火种注册、安全红线、健康、自主性、世界层 |
| `tools/` | 开发与校验脚本：文档检查、抓取测试、发布等 |
| `docs/` | 项目文档：架构、安装、快速开始、接口、各子服务说明 |

小焦不在代码里写死模型：换模型只改配置，人设、工具与记忆不受影响。

## 3. 大脑

`xiaojiao_control.json` → `brain.engine` 决定用哪个大脑：

| 取值 | 含义 |
| --- | --- |
| `auto` | 自动判断（本地大脑在线则用本地） |
| `llama` | 本地 GGUF 大模型 |
| `api` | 外接 OpenAI 兼容接口（如 DeepSeek、Qwen、Agnes 等） |
| `xiaojiao` | 自研小脑（MiniGPT），能力弱于大模型，默认不启用 |

本地大脑由 `llama-swap`（默认端口 9292）托管，`llama-swap.yaml` 里登记可用模型；仓库中的示例登记了聊天模型（4B，模型名 `xiaojiao`）与编码模型（8B，模型名 `qwen3-8b`）。云端模型走 `brain.api`，也可在 `models[]` 里登记多个模型并在界面下拉切换。

状态与资源：

| 状态 | 含义 |
| --- | --- |
| RUN | 权重驻留显存 |
| WARM | 权重保留在内存（内存只保留一个槽位，新温存会顶掉旧的） |
| OFF | 完全卸载，释放显存与内存 |

切换时旧大脑让出显存，目标大脑上显存；生成视频或音乐前会先卸载 llama 大脑以腾出显存。同一时刻只有一个大模型占用显存，因此显存需求取决于当前驻留的那个模型，而不是所有模型之和。

## 4. 视频生成

`video_service/` 提供两种模式，由 `XIAOJIAO_VIDEO_MODE` 或 `brain.video_mode` 决定：

| 模式 | 实现 | 特点 |
| --- | --- | --- |
| `api` | 云端接口（默认 Agnes） | 不占本地显存；免费额度带每分钟 1 次的节流 |
| `local` | 本地 ComfyUI + Wan2.1 | 无需外部账号，占用本地显存 |

云端调用方式：`POST {base}/v1/videos`（Bearer 鉴权，`mode` 取 `ti2vid` 表示文生视频），随后轮询 `/agnesapi` 取结果；Key 来自 `XIAOJIAO_AGNES_KEY` 或 `models[]` 中的 agnes 条目。相关接口见 [HTTP API](api.md) 第 12 节。

## 5. 播客生成

- 页面与接口：`/podcast` 页面、`POST /api/podcast` 生成、`GET /api/podcast/status/<jid>` 查询进度（另有 `GET /api/podcast`）。
- 流程：大模型写双人中文对话稿 → Chatterbox 逐句配音 → pydub 拼接音频 → SD1.5 生成封面。
- 参数：`topic`（主题，必填）、`host_a` / `host_b`（两位主持人，默认"小李"与"小焦"）、`rounds`（轮数，默认 4）、`style`（风格，默认"轻松有趣"）、`minutes`（目标时长，单位分钟）。界面里目标时长默认 15 分钟，也可选短播客、5 / 10 / 20 / 30 分钟。

## 6. 音乐生成

存在两条互不相干的路径：

| 路径 | 实现 | 状态 |
| --- | --- | --- |
| 工具 `generate_music` | `plugins/music_generation.py`，本地 MusicGen（`facebook/musicgen-small`），首次使用会自动下载模型 | 已接入，可被模型调用 |
| `music_service/ace_music.py` | 调用 ACE-Step 自带的 FastAPI 服务（默认 `http://127.0.0.1:8001`），地址与 Key 分别用 `XIAOJIAO_ACESTEP_URL`、`XIAOJIAO_ACESTEP_KEY` | 模块已提供，未接入主程序（设计，未落地） |

## 7. 桌面端与互相学习

N.E.K.O. 是一个独立的 Live2D 桌面应用，后端端口 48911 / 48912；启动器会先询问是否同时拉起（`XIAOJIAO_NEKO_AUTO=1` 可跳过询问）。两种形态都支持：

- Steam 版：入口是 `N.E.K.O.exe`，由它连带拉起后端；
- 源码版：`launcher.py` + `.venv`，分别启动 memory_server（48912）与 main_server（48911）。

目录可通过 `XIAOJIAO_NEKO_DIR` 指定，未指定时按常见 Steam 库路径与项目目录自动探测。

互相学习由 `learn_from_neko.py` 完成：读取 N.E.K.O. 的 `facts.json` 与 `persona.json`（默认目录为 `%LOCALAPPDATA%\N.E.K.O\memory\YUI\`），把其中的事实写入小焦记忆库（键形如 `学会:*`），把人格内容写入「说话风格」条目（键名见该脚本源码）。

注意：`start_xiaojiao.py` 会以 `--daemon --interval 300` 的方式启动该脚本，但脚本本身目前只执行一次学习，没有实现守护循环与参数解析（设计为后台每 5 分钟学习一次，未落地）。需要持续学习时手动重复执行即可。

N.E.K.O. 侧的插件 `xiaojiao_install` 提供两项能力：读取小焦 `/api/env` 的体检结果，以及给出分步安装指引。

## 8. 部署与启动

```powershell
cd <项目目录>
python -m pip install -r requirements.txt
python start_xiaojiao.py
```

启动后的入口：

| 入口 | 地址 |
| --- | --- |
| 网页 | `http://127.0.0.1:5000` |
| OpenAI 兼容接口 | `http://127.0.0.1:5000/v1` |
| 成本看板 | `http://127.0.0.1:5000/cost` |
| 播客页面 | `http://127.0.0.1:5000/podcast` |
| 监控面板 | `http://127.0.0.1:5000/monitor` |
| 工具调用服务 | `http://127.0.0.1:5003`（需单独运行 `python xiaojiao_tools.py`） |
| 桌面端 | Steam 客户端 N.E.K.O.exe（后端 48911 / 48912） |

完整安装、依赖分级与迁移方式见 [安装](install.md)；三步启动见 [快速开始](quickstart.md)。

## 9. 常用接口速查

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/chat` | POST | 主对话（带记忆与工具） |
| `/api/chat/stream` | POST | 流式对话 |
| `/api/tts` | POST | 文字转语音 |
| `/api/asr` | POST | 离线语音识别 |
| `/api/video` | POST | 生成视频 |
| `/api/video/mode` | GET / POST | 切换视频大脑模式 |
| `/api/podcast` | POST / GET | 生成播客 / 读取状态 |
| `/api/env` | GET | 环境体检 |
| `/api/models` | GET | 模型列表 |
| `/api/model/add` | POST | 添加模型 |
| `/api/model/select` | POST | 切换模型 |
| `/api/settings` | GET / POST | 读 / 写配置与插件开关 |
| `/v1/models`、`/v1/chat/completions` | GET / POST | OpenAI 兼容接口 |

端点、参数与注意事项的完整清单见 [HTTP API](api.md)。

## 10. 人格

人设写在 `xiaojiao_control.json` 的 `role` 字段，也可通过网页设置或 `POST /api/persona` 修改。

系统提示词由 `compose_system_prompt()` 统一合成，固定顺序为：人设 → 检索规则 → 工具规则 → 动态工具清单 → 技能插件内容 → 人格规则。每条规则只拼一份，因此修改人设不会丢掉工具清单与检索约束。

关于让回答风格更接近 N.E.K.O. 角色（独立人格、简短口语、不说教、不重复、有自身兴趣）的约定，见 [说话风格约定](xiaojiao-catgirl-style.md)。

## 相关文档

- [架构说明](architecture.md)：分层与数据流
- [快速开始](quickstart.md) / [安装](install.md)
- [插件开发指南](PLUGINS.md) / [工具清单](tools.md)
- [HTTP API](api.md)
- 子服务：[视频](video.md)、[播客](podcast.md)、[音乐](music.md)、[多大脑切换](brain-switch.md)、[N.E.K.O.](neko.md)

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
