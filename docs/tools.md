# 工具清单

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：列出小焦当前实际可用的工具（内置工具与插件工具），以及这些工具运行所依赖的外部组件与环境变量。工具的注册机制、如何自己写一个，见 [插件开发指南](PLUGINS.md)。

## 目录

1. [工具是怎么来的](#1-工具是怎么来的)
2. [内置工具](#2-内置工具14-个)
3. [插件工具](#3-插件工具)
4. [运行依赖与外部组件](#4-运行依赖与外部组件)
5. [环境变量总表](#5-环境变量总表)
6. [相关文档](#6-相关文档)

---

## 1. 工具是怎么来的

工具由两部分合并而成：

| 来源 | 位置 | 数量（实测） |
| --- | --- | --- |
| 内置工具 | `xiaojiao_app.py` 里的 `TOOLS` 列表 | 14 |
| 插件工具 | `plugins/` 目录（`.py` / `.js` / `.json` 插件声明） | 63 |
| 合计 | `all_tool_names()` 的返回 | 77 |

插件目录里另外还有 2 个"已注册但不下发"的工具：`plugins/openai-demo.json` 声明的 `get_time` 与 `calc`。该清单只有工具名、没有 `url`，执行不了，因此不会出现在模型看到的工具表里（判据见 [插件开发指南](PLUGINS.md) 第 1.3 节）。

### 1.1 自己数一遍

工具数量随插件变化，不要抄文档里的数字，直接问运行中的小焦：

```powershell
python -c "import xiaojiao_app as x; print(len(x.all_tool_names())); print(sorted(x.all_tool_names()))"
```

列出插件（而不是工具）：

```powershell
python -c "import xiaojiao_app as x; print(list(x.PLUGINS.keys()))"
```

### 1.2 模型每轮看到多少工具

完整工具目录会随系统提示词下发，但每轮真正可调用的工具会按意图收窄（`_detect_intent()` 把输入分为闲聊、抓取、画图、查询、命令等类），避免一轮把所有工具的 schema 都发出去。因此"工具总数"与"某一轮可用工具数"并不相等。

## 2. 内置工具（14 个）

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `check_env` | `items` | 只读检测本机是否安装 python / git / node / ffmpeg 等，给建议不执行 |
| `suggest_organize` | `path` | 只读扫描目录，给出按类型/日期整理的建议清单 |
| `run_command` | `command`、`timeout` | 执行系统命令（PowerShell 语法；多条命令用分号） |
| `open_app` | `path` | 用系统默认方式打开应用、文件或网址 |
| `list_files` | `path` | 列出目录条目 |
| `read_file` | `path`、`max_chars` | 读取文本文件内容 |
| `write_file` | `path`、`content` | 新建或整篇覆盖写入文件（自动建父目录） |
| `edit_file` | `path`、`old_string`、`new_string` | 精准替换文件中第一次出现的片段 |
| `search_files` | `path`、`pattern` | 按文件名（glob）查找 |
| `grep_files` | `path`、`pattern` | 在文件内容里搜关键词或正则 |
| `fetch_url` | `url` | 直接读取网址或接口返回的文本/JSON |
| `ask_user` | `question`、`options` | 向用户提问并给出选项 |
| `background` | `command`、`timeout` | 后台运行命令，立即返回任务 id |
| `background_result` | `job_id` | 查询后台任务结果 |

内置工具执行失败时会返回 `工具执行失败：<异常类型>: <说明>`；删除类操作由 `core/security/no_delete.py` 统一拦截，与权限开关无关。

## 3. 插件工具

### 3.1 网页抓取与漏洞：`plugins/scrapling_bridge.py`（18 个）

| 工具 | 用途 |
| --- | --- |
| `get` | 抓普通网页（纯 HTTP，最快），静态页与接口首选 |
| `make_request` | 与 `get` 等价，保留旧名 |
| `fetch` | 需要浏览器渲染时使用（JS 动态页、懒加载） |
| `stealthy_fetch` | 隐身抓取，用于绕风控或挑战页，开销最大 |
| `bulk_get` | 批量抓静态页 |
| `bulk_fetch` | 批量渲染抓取 |
| `bulk_stealthy_fetch` | 批量隐身抓取（上限 20 条，较慢） |
| `scrape_with_selector` | 只取页面指定区块（CSS 选择器） |
| `download` | 下载文件（PDF / ZIP / 图片 / 音视频）到本地 |
| `screenshot` | 页面截图并保存到 `media/screenshot/` |
| `open_session` | 打开浏览器会话（登录态 / 过验证） |
| `open_request_session` | 打开纯 HTTP 会话（保持 cookie） |
| `session_fetch` | 在已开浏览器会话里抓取 |
| `session_make_request` | 在已开 HTTP 会话里发请求 |
| `list_sessions` | 查看当前还开着哪些会话 |
| `close_session` | 关闭会话、释放资源 |
| `browser_session` | 会话与截图的聚合入口（开 → 抓 → 截 → 关） |
| `collect_vulnerabilities` | 漏洞清单统一入口，读取 NVD 结构化数据（`days` 默认 7、`severity` 默认 HIGH、`limit` 默认 5） |

抓取插件另有 Prometheus 文本指标 `GET /metrics` 与 JSON 视图 `GET /api/scrapling/metrics`。

### 3.2 画图工作流：`plugins/archify.py`（15 个）

| 工具 | 用途 |
| --- | --- |
| `archify_doctor` | 体检 Archify 运行环境 |
| `archify_read_skill` | 读完整技能文档（画图第一步） |
| `archify_guide` | 按场景推荐图表类型与官方提示词 |
| `archify_read_schema` | 读某图表类型的 schema |
| `archify_read_example` | 读某图表类型的完整示例 JSON |
| `archify_validate` | 校验 JSON 是否符合规范（交付前必做） |
| `archify_inspect` | 只看结构、不渲染 |
| `archify_render` | 渲染成 HTML（基础版） |
| `archify_preview` | 预览渲染 |
| `archify_deliver` | 最终交付：渲染并生成正式 HTML |
| `archify_check` | 检查已生成的 HTML 是否正常 |
| `archify_visual_check` | 对已生成的 HTML 做视觉检查 |
| `archify_compare` | 对比两张架构图并列出差异 |
| `archify_batch` | 一次生成多张图 |
| `archify_metrics` | 查看画图调用的成功/失败/耗时统计 |

### 3.3 代码与工程：`plugins/code_intelligence.py`（7 个）

| 工具 | 用途 |
| --- | --- |
| `project_tree` | 生成目录树 |
| `ci_search_files` | 按文件名查找（支持通配符） |
| `ci_search_content` | 在文件内容里搜关键词或正则 |
| `ci_read_file` | 带行号读文件（可指定起止行） |
| `get_file_info` | 查看单个文件的大小、行数、修改时间 |
| `count_code_lines` | 按语言统计代码行数与注释占比 |
| `analyze_dependencies` | 列出项目依赖（按语言分组） |

### 3.4 数据库：`plugins/db_helper.py`（5 个）

| 工具 | 用途 |
| --- | --- |
| `connect_db` | 连接一个 SQLite 数据库 |
| `list_tables` | 列出库中的表 |
| `describe_table` | 查看表结构 |
| `query_db` | 执行一条 SELECT（只读，不允许 DDL/DML） |
| `export_table_json` | 把整张表导出为 JSON |

### 3.5 资产测绘：`plugins/asset_intel.py`（3 个）

| 工具 | 用途 |
| --- | --- |
| `asset_intel_lookup` | 给定 IP，列出它命中的 CVE（免 Key） |
| `asset_intel_search` | 给定 CVE 或关键词，反查受影响 IP（需数据源 Key） |
| `asset_intel_status` | 查看各数据源可用状态与缺失的 Key |

用法与 Key 配置见 [资产测绘插件](asset-intel.md)。

### 3.6 网络诊断：`plugins/netdoctor.js`（3 个）

| 工具 | 用途 |
| --- | --- |
| `net_ip` | 查本机公网 IP，可带归属地、ISP、时区 |
| `net_dns` | 解析域名的 A 记录与 MX 记录 |
| `net_port` | 测主机/端口 TCP 可达性与耗时 |

### 3.7 工作区检索：`plugins/workspace_search.py`（3 个）

| 工具 | 用途 |
| --- | --- |
| `ws_search_files` | 在工作区内按文件名查找 |
| `ws_search_content` | 在工作区内按内容搜索 |
| `ws_list_directory` | 列出工作区某目录的条目 |

### 3.8 其余插件（合计 9 个）

| 插件 | 工具 | 用途 |
| --- | --- | --- |
| `plugins/memory.py` | `save_memory`、`read_memory` | 写入 / 读回长期记忆 |
| `plugins/ip.json` | `get_ip`、`get_ip_info` | 查本机公网 IP；查指定 IP 的归属地 |
| `plugins/search.py` | `web_search` | 联网搜索（另有内置同名能力，重名时按先到先得处理） |
| `plugins/weather.py` | `get_weather` | 查指定城市天气 |
| `plugins/js-calc.js` | `js_calc` | 计算数学表达式 |
| `plugins/video_generation.py` | `generate_video` | 调用视频大脑生成视频 |
| `plugins/music_generation.py` | `generate_music` | 本地生成音乐片段（首次使用会自动下载模型） |

### 3.9 声明了但不下发的插件

| 插件 | 工具 | 说明 |
| --- | --- | --- |
| `plugins/openai-demo.json` | `get_time`、`calc` | 外部清单格式示例，未提供 `url`，因此不进入模型工具表 |

## 4. 运行依赖与外部组件

以下组件决定"哪些功能可用"，其中必需项缺失会拦住启动（详见 [安装](install.md) 第 3 节）。

| 组件 | 分级 | 作用 |
| --- | --- | --- |
| Python 依赖（`requirements.txt`） | 必需 | 全部工具的基础运行环境 |
| `llama-server.exe`（llama.cpp） | 必需 | 本地大脑推理引擎 |
| 大脑模型（本地 GGUF 或云端 OpenAI 兼容接口） | 必需 | 对话与工具调用的大脑 |
| 小脑模型（`*.pth` + `vocab*.pkl`） | 必需 | 自研 MiniGPT，项目核心组件 |
| llama-swap | 必需 | 多大脑热切换管理（默认端口 9292） |
| ComfyUI 便携版 | 可选 | 视频生成的执行引擎（默认端口 8188），缺了只少视频功能 |
| `ComfyUI-AnyDeviceOffload` | 可选 | 视频模型的显存/内存卸载节点 |
| `ComfyUI-WanVideoWrapper` | 可选 | Wan 视频工作流节点 |
| Wan2.1 视频模型三件套（`dit_fp8` / `umt5_fp8` / `vae_fp8`） | 可选 | 视频生成本体、文本编码器、VAE |
| Node.js | 可选 | 运行 `.js` 插件（`plugins/plugin_runner.js`） |
| 浏览器内核（Chromium / 自备 Chrome） | 可选 | 抓取插件的渲染能力（`scrapling.executable_path` 可指定自备 Chrome） |
| NVIDIA 显卡 | 可选 | CPU 也能对话；有 N 卡时本地推理与视频生成更快，显存需求随所选模型规模变化 |

ComfyUI 与视频模型使用 ComfyUI 自带的 Python 环境（`python_embeded`），与主环境相互隔离；视频模型在 `brain.keep_warm` 为真时保持常驻，可省去每次重新加载的时间。

## 5. 环境变量总表

所有路径类配置都可以用环境变量覆盖，代码里不写死绝对路径。

| 变量 | 作用 |
| --- | --- |
| `XIAOJIAO_LLAMA_SERVER` | `llama-server.exe` 路径 |
| `XIAOJIAO_GGUF` | 本地大脑 GGUF 路径（启动器与大脑管理器读这个） |
| `XIAOJIAO_LLAMA_GGUF` | 同上，体检接口 `/api/env` 读这个变量名 |
| `XIAOJIAO_LLAMA_SWAP` | `llama-swap.exe` 路径 |
| `XIAOJIAO_BRAIN_MODEL` / `XIAOJIAO_BRAIN_VOCAB` / `XIAOJIAO_BRAIN_CONFIG` | 小脑三件套路径 |
| `XIAOJIAO_API_KEY` | 云端大脑的 API Key（优先级高于控制文件，密钥可不落盘） |
| `XIAOJIAO_COMFY_DIR` / `XIAOJIAO_COMFY_PORT` | ComfyUI 目录 / 端口 |
| `XIAOJIAO_VIDEO_ROOT` / `XIAOJIAO_WAN_MODEL` | 视频模型总目录 / Wan 模型名 |
| `XIAOJIAO_KEEP_COMFY` | 设为 `1` 时视频模型保持常驻 |
| `XIAOJIAO_VIDEO_MODE` | 视频大脑模式：`api`（云端）或 `local`（本地 ComfyUI） |
| `XIAOJIAO_AGNES_KEY` | 云端视频接口的 Key |
| `XIAOJIAO_ACESTEP_URL` / `XIAOJIAO_ACESTEP_KEY` | ACE-Step 音乐服务地址与 Key |
| `XIAOJIAO_TTS_MODEL` | 播客配音模型目录 |
| `XIAOJIAO_VISION_URL` / `XIAOJIAO_VISION_MODEL` | 视觉识图接口与模型名 |
| `XIAOJIAO_NEKO_DIR` / `XIAOJIAO_NEKO_AUTO` | N.E.K.O. 目录；设为 `1` 时启动不再询问 |
| `XIAOJIAO_WORKSPACE` / `XIAOJIAO_DB_PATH` | 工作区根目录 / 数据库路径 |
| `XIAOJIAO_TOOLS_HOST` / `TOOLS_PORT` | 工具调用服务的监听地址与端口（默认本机 5003） |
| `PORT` | Web 端口（优先级低于 `--port` 与控制文件 `web_port`） |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 无控制文件时的 OpenAI 兼容接口配置 |
| `LLAMA_API` | 蒸馏脚本调用的 llama-swap 接口 |
| `HF_ENDPOINT` | 模型下载镜像（默认 `https://hf-mirror.com`） |
| `XIAOJIAO_LOG_LEVEL` / `XIAOJIAO_LOG_CONSOLE` | 日志级别与是否输出到控制台 |

## 6. 相关文档

- [插件开发指南](PLUGINS.md)：插件机制与写法
- [扩展开发](extend.md)：加工具之外的扩展方式
- [安装](install.md)：各组件的获取与检测分级
- [资产测绘插件](asset-intel.md)：`asset_intel_*` 三个工具的完整用法
- [抓取插件](scrapling.md)：抓取与漏洞清单相关能力的深入说明

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
