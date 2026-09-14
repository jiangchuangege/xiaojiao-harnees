# HTTP API

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：小焦的对外接口清单。分为两部分：给任意 OpenAI 兼容客户端使用的 `/v1`，以及网页与外部脚本使用的 `/api/*` 内部接口。表中所有端点都对应代码里真实注册的路由（`xiaojiao_app.py` 的 `@app.route`、子服务 Blueprint 与 `xiaojiao_tools.py`），未落地的接口不列入。

## 目录

1. [地址与鉴权](#1-地址与鉴权)
2. [OpenAI 兼容接口](#2-openai-兼容接口)
3. [对话与消息](#3-对话与消息)
4. [会话](#4-会话)
5. [工具与权限](#5-工具与权限)
6. [模型](#6-模型)
7. [设置、预设与人设](#7-设置预设与人设)
8. [环境、成本与运行状态](#8-环境成本与运行状态)
9. [语音与视觉](#9-语音与视觉)
10. [工作区](#10-工作区)
11. [世界层与协同网络](#11-世界层与协同网络)
12. [视频与播客](#12-视频与播客)
13. [监控面板](#13-监控面板)
14. [工具调用服务（独立端口）](#14-工具调用服务独立端口)
15. [注意事项](#15-注意事项)

---

## 1. 地址与鉴权

Base URL：

```text
http://127.0.0.1:5000
```

端口取值优先级：启动参数 `--port` > 控制文件 `web_port` > 环境变量 `PORT` > 默认 5000。

监听地址与令牌规则（`bind_host()` 与 `_require_token()`）：

| 配置 | 行为 |
| --- | --- |
| 默认（`capabilities.lan_access` 为假） | 只监听 `127.0.0.1`，不做令牌校验 |
| 开了 `lan_access` 且 `access_token` 非空 | 监听 `0.0.0.0`，非本机请求必须带令牌 |
| 只开 `lan_access` 没配令牌 | 仍只监听 `127.0.0.1`，并在启动时打印警告 |

带令牌的两种方式：请求头 `X-Auth-Token: <token>`，或网址参数 `?token=<token>`。本机请求免令牌；`/health`、`/favicon.ico`、`/api/central` 与 `/static/` 路径始终免鉴权。

## 2. OpenAI 兼容接口

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/v1/models` | GET | 返回当前模型名（`id` 为控制文件的 `model_name`，`owned_by` 为 `xiaojiao`） |
| `/v1/chat/completions` | POST | 对话。取最后一条 user 消息交给小焦的 Agent 处理，返回 OpenAI 格式响应；请求体带 `stream: true` 时返回 SSE 流 |

示例：

```bash
curl http://127.0.0.1:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "xiaojiao1.0-4B",
    "messages": [{"role": "user", "content": "你是谁"}]
  }'
```

接入方式：把客户端（dsh、open-webui、脚本等）的模型地址填成 `http://127.0.0.1:5000/v1` 即可，人设、工具与记忆随之上线。二者分工见 [dsh 集成](dsh-integration.md)。

## 3. 对话与消息

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/chat` | POST | 发起一轮对话（非流式） |
| `/api/chat/stream` | POST | 流式对话（SSE），前端边收边渲染 |
| `/api/chat/pending` | GET | 查询当前会话最后一条消息是否仍在生成 |
| `/api/chat/stop` | POST | 叫停长文续写 |
| `/api/chat/abandon` | POST | 放弃当前轮，强制清掉生成标记 |
| `/api/message` | POST | 把一条消息（如视频结果）写入当前会话历史 |
| `/api/history` | GET | 读取当前会话历史 |
| `/api/feedback` | POST | 记录点赞 / 点踩 / 更正反馈，其中被赞或被更正的内容会进入小脑知识库 |

## 4. 会话

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/sessions` | GET | 会话列表 |
| `/api/session/new` | POST | 新建会话 |
| `/api/session/<sid>` | GET | 打开指定会话 |
| `/api/session/delete` | POST | 删除会话 |

## 5. 工具与权限

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/tools_toggle` | GET / POST | 读 / 切换工具开关（开 = 允许执行工具，关 = 只聊天） |
| `/api/access` | GET / POST | 读 / 切换权限模式（Full access 与 Read-only） |
| `/api/confirm` | POST | 确认执行此前被挂起的危险动作 |
| `/metrics` | GET | 抓取插件的指标（Prometheus 文本格式） |
| `/api/scrapling/metrics` | GET | 同一份指标的 JSON 视图，含活跃会话与熔断状态 |

## 6. 模型

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/models` | GET | 当前引擎与已配置模型列表 |
| `/api/model/select` | POST | 切换到某个已配置模型 |
| `/api/model/add` | POST | 添加模型（本地或外接，同名覆盖） |
| `/api/model/addlocal` | POST | 一键登记本地 GGUF：写入 `llama-swap.yaml` 与大脑注册表并重启 llama-swap |
| `/api/model/delete` | POST | 删除模型条目 |

## 7. 设置、预设与人设

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/settings` | GET | 返回当前配置与插件清单（含开关状态） |
| `/api/settings` | POST | 保存设置并热更新运行中的配置 |
| `/api/presets` | GET | 预设列表 |
| `/api/presets` | POST | 新建预设 |
| `/api/presets/detail` | GET | 读取单个预设内容 |
| `/api/presets/save` | POST | 保存预设内容 |
| `/api/presets/load` | POST | 加载预设并热更新配置 |
| `/api/presets/delete` | POST | 删除预设 |
| `/api/presets/current` | GET | 当前预设状态 |
| `/api/persona` | POST | 切换人格（写入 `role` 并生效） |
| `/api/plugin/generate` | POST | 按自然语言需求生成插件代码并尝试注册 |

## 8. 环境、成本与运行状态

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/env` | GET | 环境体检：逐项返回是否具备及缺失时的补救说明 |
| `/api/cost` | GET | 当日调用数、本地/云端 token、花费与节省 |
| `/cost` | GET | 成本看板页面 |
| `/api/brain` | GET | 小脑数据：成长统计、学到的用法、反思 |
| `/api/growth` | GET | 小脑成长指标 |
| `/growth` | GET | 成长报告页面 |
| `/health` | GET | 探活（免鉴权，不含敏感信息） |
| `/` | GET | 主聊天页面 |
| `/pet` | GET | 跳转到 N.E.K.O. 桌面端（端口 48911） |
| `/favicon.ico` | GET | 内联图标 |

## 9. 语音与视觉

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/voice/warm` | POST | 预热语音链路（对话大脑、识别、发声） |
| `/api/asr` | POST | 离线语音识别，接收音频返回文字 |
| `/api/tts` | POST | 文字转语音，返回音频地址（缺依赖时提示安装） |
| `/api/screen` | GET | 截屏并返回截图地址 |
| `/api/vision` | GET | 截屏并让视觉模型理解画面；未配置视觉接口时退回 OCR |

## 10. 工作区

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/workspace` | GET | 列出项目文件夹内容 |
| `/api/ws/open` | POST | 读取项目内的文本文件（带目录穿越防护） |

## 11. 世界层与协同网络

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/world` | GET | 世界层概览：探索、吸收、隔离与黑名单情况 |
| `/api/world/firewall` | GET / POST | 污染防火墙操作：释放隔离、驳回记忆、黑白名单、开关探索 |
| `/api/central` | GET | 协同网络只读快照：中央状态、事件总线统计与最近事件 |

## 12. 视频与播客

以下端点来自子服务，随主程序启动一并挂载（挂载失败只会打印一条警告，不影响其它功能）。

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/video` | POST | 生成视频（本地 ComfyUI 或云端接口） |
| `/api/video/mode` | GET / POST | 读 / 切换视频大脑模式（`api` 云端 / `local` 本地） |
| `/api/video/status` | GET | 生成任务进度 |
| `/api/video/current` | GET | 当前视频产物 |
| `/api/video/state` | GET | 视频服务状态 |
| `/api/video/refine` | GET | 提示词精炼 |
| `/api/video/promptkb` | GET | 提示词知识库 |
| `/videos/<path:name>` | GET | 视频文件访问 |
| `/media/<path:name>` | GET | 媒体文件访问 |
| `/podcast` | GET | 播客页面 |
| `/api/podcast` | POST / GET | 生成播客（POST）/ 读取状态（GET） |
| `/api/podcast/status/<jid>` | GET | 按任务 id 查询播客生成进度 |

播客生成参数：`topic`（必填）、`host_a`（默认"小李"）、`host_b`（默认"小焦"）、`rounds`（默认 4）、`style`（默认"轻松有趣"）、`minutes`（可选）。

## 13. 监控面板

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/monitor` | GET | 大脑与显存监控页面 |
| `/api/monitor` | GET | 监控数据（大脑状态、显存、内存） |
| `/api/monitor/op` | POST | 对大脑执行操作（调优参数等） |

## 14. 工具调用服务（独立端口）

`xiaojiao_tools.py` 是一个独立进程，需单独启动（`python xiaojiao_tools.py`），默认监听 `127.0.0.1:5003`。

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/` | GET | 工具调用面板 |
| `/api/tools` | GET | 该服务可调用工具的说明清单 |
| `/api/run` | POST | 执行工具，请求体：`{"name": "...", ...参数}` |

`POST /api/run` 只在请求来自本机回环地址时才接受 `force`；非本机请求即使传 `force` 也会降级走危险命令确认流程。可用 `TOOLS_PORT` 改端口、`XIAOJIAO_TOOLS_HOST` 改监听地址（改为非本机地址会暴露命令执行能力，需自行加鉴权）。

## 15. 注意事项

- 人设由提示词层注入。走 `/v1` 或网页才会带上"小焦"人格；直连上游裸模型得到的是模型自身的回答。
- `/v1/chat/completions` 不会执行调用方传入的 `tools`：工具由小焦内部 Agent 自行决定调用，响应只包含最终文本，`usage` 中的 token 计数为 0。
- 危险命令默认需要确认（`capabilities.full_access` 为假时）：模型提出动作后会挂起，等待 `POST /api/confirm`。
- 删除文件属于硬约束，任何入口都会被 `core/security/no_delete.py` 拦截，与权限开关无关。
- 接口字段随版本演进，脚本侧建议对上表端点做一次实际探测，而不是依赖文档中的示例值。

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
