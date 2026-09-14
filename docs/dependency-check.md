# 依赖与模型检测

| 项目 | 内容 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：本文说明小焦如何检测「大脑模型」是否真的可用（按 OpenAI 兼容协议真发一次请求，通了才算通过），以及依赖清单、一键安装器与配套自查工具的用法。

## 目录

- [1. 为什么要按协议检测](#1-为什么要按协议检测)
- [2. 检测函数](#2-检测函数)
- [3. 安装向导怎么用](#3-安装向导怎么用)
- [4. 环境体检接口](#4-环境体检接口)
- [5. 检测结果对照](#5-检测结果对照)
- [6. 依赖清单与安装器](#6-依赖清单与安装器)
- [7. 配套自查工具](#7-配套自查工具)
- [8. 相关文件](#8-相关文件)

## 1. 为什么要按协议检测

只检查「配置里有没有 `api_key` / `base_url`」或「本地有没有模型文件」，会漏掉最常见的一种状态：
**填了但地址写错、Key 失效、服务没启动** —— 检测显示「有模型」，用户实际用不了却不知道。

所以小焦把模型检测升级为**协议连通测试**：

- **本地大脑**：不只看模型文件在不在，还探测大脑服务端口（socket 连通），确认服务真的在跑。
- **云端 API**：真发一个 OpenAI 兼容请求，**返回 200 才算通过**。

## 2. 检测函数

两个核心函数都在 `install_all.py`。

### 2.1 `test_cloud_api(base_url, api_key, model="")`

按 OpenAI 兼容协议探测一个端点，返回 `(ok, message)`：

1. `base_url` 为空 → `(False, "base_url 为空")`。
2. 先发 `GET {base_url}/models`（超时 15 秒），`200` → `(True, "GET /models 200 OK")`。
3. `/models` 返回**任何非 200**（不只是 404 / 405）→ 退回发一个最小 `POST {base_url}/chat/completions`：

   ```json
   {"model": "模型名或 test", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
   ```

   超时 20 秒，`200` → `(True, "POST /chat/completions 200 OK")`。
4. 其它情况 → `(False, "HTTP <状态码> (models=<状态码>, chat=<状态码>)")`；连接异常 → `(False, "连接失败: …")`。

> 为什么保留 fallback：有部分端点不开放 `/models` 列表，但 `/chat/completions` 可用。
> 保留 fallback 才能准确回答「到底能不能聊」这个问题。

### 2.2 `is_port_up(port, timeout=1.0)`

用 socket 连接 `127.0.0.1:<port>`，1 秒超时，返回布尔值。用于判断本地大脑服务是否已经上线。

## 3. 安装向导怎么用

一键安装器共 11 步，第 3 步（`[3/11]`）负责大脑模型。判定链如下：

1. **解析本地端口**：从 `brain.api.base_url` 里取端口，取不到用默认值 `9292`（llama-swap）。
2. **找本地模型文件**：先看配置里的 `brain.llama.gguf`；不存在则全盘自动探测（按目录关键词启发式 + `where /r` 兜底）。
3. **探测服务端口**：端口在线 → 对 `http://127.0.0.1:<端口>/v1` 调用 `test_cloud_api` 做协议连通测试。
4. **文件就绪也算通过**：若协议不通，但 `llama-server` 与 GGUF 文件都在，判为「文件就绪」，提示启动 `start_xiaojiao.py` 后会自动拉起大脑。
5. **再看云端**：只有 `api_key` 与 `base_url` 都非空时才真发一次 `test_cloud_api`。
6. **结论**：本地可用（协议通或文件就绪）**或** 云端通，任一成立即判通过。

都不通时进入**交互式引导**：询问是否现在配置云端 API，让使用者现场输入 `base_url` / `api_key` / `model`，
**当场实测**；通了才写入 `xiaojiao_control.json` 的 `brain.api`（并把 `brain.engine` 设为 `api`）并判通过；
不通则明确报出「连接失败 / 鉴权失败 / HTTP xxx」，并计入缺失项，绝不误判。

实际输出形如（下面是安装器原样打印的内容）：

```text
[3/11] 大脑模型 (本地 GGUF 或 云端 OpenAI 兼容 key) ...
   ✅ 本地大脑可用: http://127.0.0.1:9292/v1 (GET /models 200 OK)
   ❌ 云端 API 不通: HTTP 401 (models=401, chat=401)
   ⚠️ 当前没有协议连通的大脑。
   想现在配置一个云端 OpenAI 兼容 API(base_url + key + model)? [Y/n]:
```

## 4. 环境体检接口

`xiaojiao_app.py` 的 `GET /api/env` 返回环境体检清单，其中「**对话/工具模型**」一项同样按协议检测：

| 步骤 | 实现 |
| --- | --- |
| 解析本地端口 | 从 `brain.api.base_url` 取端口，默认 9292 |
| 本地判定 | `port_up(端口)` 做 socket 连通，超时 0.8 秒 |
| 云端判定 | `requests.get(base_url + "/models", Authorization: Bearer <key>, timeout=3)`，`200` 记为「已连(200)」，否则记「不通(HTTP xxx)」或「连接失败: …」 |
| 结论 | `本地在线 或 云端通` 为真才算通过，否则该项标记为不通过并给出「怎么做」 |

同一次体检还会检查 `llama-server` 是否可执行（环境变量 `XIAOJIAO_LLAMA_SERVER` 优先）、
GGUF 文件是否存在（`XIAOJIAO_LLAMA_GGUF` 优先）、llama-swap（9292）与 ComfyUI（8188）端口是否在线。

因此「装小焦体检」反映的是**模型是否真的能用**，而不是「填了个 key 就显示通过」。

## 5. 检测结果对照

| 场景 | 检测结果 |
| --- | --- |
| 本地大脑端口 9292 未启动，且没有模型文件 | 未连通，提示先启动 `start_xiaojiao.py` |
| 本地大脑端口在线且 `GET /models` 返回 200 | 通过 |
| 本地协议不通，但 `llama-server` 与 GGUF 文件齐全 | 通过（文件就绪），提示启动后自动拉起 |
| 云端 API 与正确 Key | 通过（`GET /models 200 OK`） |
| 云端 API 与错误 Key | 不通过（`HTTP 401`） |
| 云端地址不存在 | 不通过（`连接失败`） |
| 云端只开放 chat、不开放 models | 通过（fallback 到 `/chat/completions` 并返回 200） |
| `base_url` 为空 | 不通过（`base_url 为空`） |

## 6. 依赖清单与安装器

| 文件 | 说明 |
| --- | --- |
| `requirements.txt` | 宽松范围清单，便于人工阅读与升级；要求 Python 3.10+（推荐 3.13） |
| `requirements.lock` | 锁定版本清单，用于装出与验证环境完全一致的依赖；生成环境为 Python 3.13.13 / Windows |
| `一键安装.bat` | Windows 双击入口，内部执行 `python install_all.py` |
| `install_all.py` | 11 步全功能安装器：依赖、llama.cpp、大脑模型、小脑模型、llama-swap、ComfyUI、视频模型、Node.js、GPU、可选功能依赖、写配置、启动 |

```powershell
# 装出与验证环境一致的依赖
python -m pip install -r requirements.lock

# 升级到最新兼容版本
python -m pip install -r requirements.txt

# 完整安装（检测 11 项 → 自动下载缺失项 → 写配置 → 报告）
python install_all.py
```

`install_all.py` 的第 1 步会直接执行 `pip install -r requirements.txt`；另有更精简的三步版 `install_auto.py`
（装依赖 → 检查大模型 → 启动）。

关于自动下载的现状（据当前代码）：

| 能力 | 状态 |
| --- | --- |
| 下载 llama.cpp / llama-swap / Wan2.1 三件套 | 已落地（`urllib.request.urlretrieve`，可选功能会给选项） |
| 国内镜像 | 只有 hf-mirror（环境变量 `HF_ENDPOINT` 可改）；ModelScope 未接入 |
| 断点续传、下载后校验和、下载后试生成一次 | **设计，未落地** |
| 按显存分档自动推荐模型 | **设计，未落地**（当前是「全盘探测已有模型 + 让使用者手填任意 OpenAI 兼容端点」） |
| 硬件自动检测 | 仅检测 NVIDIA 显卡名称（`nvidia-smi`）；显存、内存、硬盘、网络未纳入 |

## 7. 配套自查工具

| 工具 | 用途 | 用法 |
| --- | --- | --- |
| `tools/check_cloud_brain.py` | 云端大脑体检：判定「是 Key 填错了」还是「服务商侧问题」 | `python tools/check_cloud_brain.py [--key sk-xxx] [--n 10]` |
| `tools/check_frontend_js.py` | 把 `xiaojiao_app.py` 里的前端 HTML/JS 抽出来交给 `node --check` 做语法检查，并做结构名字核对 | `python tools/check_frontend_js.py` |
| `tools/check_secrets.py` | 找出手写在配置文件里的明文密钥 | `python tools/check_secrets.py [--include-logs] [--fix-hint]` |

`tools/check_cloud_brain.py` 的判据只有一条：`POST /chat/completions` 能不能通。
`GET /models` 在那里**不作为证据** —— 实测连空 Key 或乱写的 Key 都可能拿到 200（网关或缓存不时不校验令牌），
「models 能通」并不等于「Key 是对的」。该工具默认每组打 6 次，并区分「被拒」与「太慢」两种失败。

```powershell
python tools/check_cloud_brain.py
python tools/check_cloud_brain.py --key sk-你在别的客户端里能用的那把
```

## 8. 相关文件

| 文件 | 作用 |
| --- | --- |
| `install_all.py` | 一键安装向导；`test_cloud_api` / `is_port_up` 就在这里 |
| `install_auto.py` | 精简三步安装与启动 |
| `xiaojiao_app.py` | `GET /api/env` 体检接口，「对话/工具模型」按协议检测 |
| `xiaojiao_control.json` | `brain.api`（云端 `base_url` / `api_key` / `model`）、`brain.llama`（本地 llama-server 与 GGUF） |
| `tools/check_cloud_brain.py` | 云端大脑体检（判据只用 chat） |

模型**可插拔、不写死型号**：任何 OpenAI 兼容端点，或任意本地 GGUF 文件，只要协议连通就可以使用。

## 参考

- 安装说明：[install.md](install.md)
- 快速上手：[quickstart.md](quickstart.md)
- 安全审计（含密钥自查与命令端点加固）：[security-audit.md](security-audit.md)

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
