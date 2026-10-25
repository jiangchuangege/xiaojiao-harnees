# 工具调用清单（模型精准调用指南）

> 这份文件是 `tools/gen_tool_catalog.py` **自动生成**的，别手改 —— 
> 改了工具描述就重跑一次；`tools/test_tool_contract.py` 会校验它和实际工具表是否一致。

**全部工具：99 个 ｜ 契约合格：99 个 ｜ 不合格：0 个**

## 怎么读这张表

- **什么时候用**：说明里的第一句就是触发场景；模型按这句话决定要不要挑这个工具。
- **精准调用**：括号里是**必填参数**，值已经填成能直接抄的例子。
- **参数说明**：所有参数都必须有中文说明（没有说明的参数 = 模型不知道该填什么，审计会判不合格）。

## 一句话总则

1. 只挑**说明里明确提到当前这件事**的工具；挑不出就不调，直接问用户。
2. 必填参数齐了才调；缺就先问（`rea_do` 这类入口会替模型把参数补齐或把缺口列出来）。
3. 同一个意思有多个工具时，优先**更具体**的那个（名字里有具体对象的）。
4. 工具返回空/报错时，把它说的原话转达给用户，不要自己编结果。

### 内置 · 内置（14 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `ask_user` | 向用户提问并给出选项，等待用户选择。用于需要用户拍板时。question=问题, options=选项列表(逗号分隔)。 | `ask_user({"question": "值"})` | ✅ |
| `background` | 在后台运行一条命令(不阻塞)，立即返回任务id。稍后用 background_result 查结果。用于耗时任务。 | `background({"command": "dir"})` | ✅ |
| `background_result` | 查询后台任务(background启动的)的结果。job_id=任务id。 | `background_result({"job_id": "值"})` | ✅ |
| `check_env` | 检测电脑环境装没装东西(只读): 检查 python/git/node/ffmpeg 等是否安装及版本。 | `check_env({})` | ✅ |
| `edit_file` | 在文本文件里精准替换一段内容(第一次出现的)。 | `edit_file({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "old_string": "值", "new_string": "值"})` | ✅ |
| `fetch_url` | 直接读一个网址/接口的返回内容(纯HTTP，最轻)。 | `fetch_url({"url": "https://example.com"})` | ✅ |
| `grep_files` | 在文件**内容**里搜关键词/正则。 | `grep_files({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "pattern": "值"})` | ✅ |
| `list_files` | 列目录里有什么。什么时候用：要知道某目录下的文件清单；输入 path；输出 条目列表(不含内容) | `list_files({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `open_app` | 用系统默认方式打开一个应用/文件/网址。 | `open_app({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `read_file` | 读文本文件内容。 | `read_file({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `run_command` | 跑一条系统命令并回显输出(PowerShell 语法)。 | `run_command({"command": "dir"})` | ✅ |
| `search_files` | 按文件名找文件(glob)。 | `search_files({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "pattern": "值"})` | ✅ |
| `suggest_organize` | 整理文件建议(只读): 扫描一个目录, 按类型/日期给出整理到哪里的建议。 | `suggest_organize({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `write_file` | 新建/覆盖写入文件(自动建目录)。 | `write_file({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "content": "值"})` | ✅ |

### 插件 · archify（15 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `archify_batch` | 一次画多张图。什么时候用：用户要一批图；输入 items 数组；输出 每张的结果 | `archify_batch({"items": []})` | ✅ |
| `archify_check` | 检查已生成的 HTML 是否正常。什么时候用：交付后自检；输入 html_path；输出 检查结果 | `archify_check({"html_path": "值"})` | ✅ |
| `archify_compare` | 对比两张架构图并给差异。什么时候用：改版前后比一比(仅 architecture)；输入两份 spec；输出 差异清单 | `archify_compare({"base_json": "值", "head_json": "值"})` | ✅ |
| `archify_deliver` | **最终交付**：渲染并生成正式 HTML。 | `archify_deliver({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_doctor` | 体检 Archify 环境(Node/依赖/schema 是否齐)。 | `archify_doctor({})` | ✅ |
| `archify_guide` | 按场景推荐图表类型+配方+官方提示词。 | `archify_guide({"scenario": "值"})` | ✅ |
| `archify_inspect` | 只看结构、不渲染。 | `archify_inspect({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_metrics` | 看画图调用的统计(成功/失败/耗时)。什么时候用：排查画图为什么慢/失败；无参数；输出 统计表 | `archify_metrics({})` | ✅ |
| `archify_preview` | 预览渲染(服务端用，不开浏览器)。什么时候用：想先看看效果再决定交付；输入同 render；输出 预览结果 | `archify_preview({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_read_example` | 读该类型的**完整示例 JSON**。 | `archify_read_example({"diagram_type": "值"})` | ✅ |
| `archify_read_schema` | 读该图表类型的 schema(含公共部分)。 | `archify_read_schema({"diagram_type": "值"})` | ✅ |
| `archify_read_skill` | 读 Archify 完整技能文档。 | `archify_read_skill({})` | ✅ |
| `archify_render` | 把 JSON 渲染成 HTML(基础版，不开浏览器)。 | `archify_render({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_validate` | **交付前必做**：校验 JSON 是否符合规范。 | `archify_validate({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_visual_check` | 对已生成的 HTML 做**视觉**检查。 | `archify_visual_check({"html_path": "值"})` | ✅ |

### 插件 · asset_intel（3 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `asset_intel_lookup` | 给 IP 查它命中了哪些漏洞(免费，无需 Key)。 | `asset_intel_lookup({"ips": "值"})` | ✅ |
| `asset_intel_search` | 反过来查：某个 CVE/产品在**全网有哪些 IP** 受影响(需数据源 Key)。 | `asset_intel_search({"query": "本地大模型怎么部署"})` | ✅ |
| `asset_intel_status` | 看资产测绘数据源能不能用。 | `asset_intel_status({})` | ✅ |

### 插件 · causal_memory（6 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `causal_counterfactual` | 反事实对比（因果记忆）：两个候选方案，各自过去的结果分布是什么。什么时候用：在两个方案之间拿不定主意时。 | `causal_counterfactual({})` | ✅ |
| `causal_record` | 记一条「决策 → 结果」到因果记忆。 | `causal_record({})` | ✅ |
| `causal_report` | 因果记忆的预测账本：以前那些判断押对了多少（总览/按领域）+ 还没结算的。什么时候用：想知道这套经验到底准不准的时候。 | `causal_report({})` | ✅ |
| `causal_search` | 查以前的教训（因果记忆）：过去同类事情上，什么做法导致了什么结果。 | `causal_search({})` | ✅ |
| `causal_trace` | 什么时候用：单看一个原因解释不了故障时。 | `causal_trace({})` | ✅ |
| `causal_warn` | 动手前预警（因果记忆·抑制侧）：告诉我这个动作以前造成过什么后果，尤其是**以前这么做出过事**。 | `causal_warn({})` | ✅ |

### 插件 · causal_memory_ext（10 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `causal_facts` | 查因果记忆**它自己那边**的事实层（不是小焦自己的记忆库，两套别混）。什么时候用：明确知道东西记在它那边时。 | `causal_facts({})` | ✅ |
| `causal_invalidate` | 把一条**错的**教训软作废（不是删除，可回滚； | `causal_invalidate({})` | ✅ |
| `causal_invalidate_pattern` | 把引擎挖出来的某条**关系**软作废（相似/矛盾/重复那类 meta 边）。 | `causal_invalidate_pattern({})` | ✅ |
| `causal_lesson` | 从库里多条散着的边**重建一条教训**（比单条边更适合直接照做）。什么时候用：要总结'这一类事我以前吃了什么亏'时。 | `causal_lesson({})` | ✅ |
| `causal_memory_map` | 看一眼因果记忆库的全貌（多少条因果边、多少节点、最近记了什么）。 | `causal_memory_map({})` | ✅ |
| `causal_patterns` | 看引擎自己挖出来的关系：哪些经验**相似**、哪些**互相矛盾**、哪些在**重复**。 | `causal_patterns({})` | ✅ |
| `causal_remember` | 直接把一段对话（几条消息）喂进因果记忆的提炼链路，由它自己拆出决策与结果。 | `causal_remember({})` | ✅ |
| `causal_resolve` | 让引擎评审'同一个决策反复记录、结局却不一样'的发散项，并决定要不要取代旧结论。 | `causal_resolve({})` | ✅ |
| `causal_trace_one` | 单跳溯源：这个结果**直接**是哪个决策造成的。 | `causal_trace_one({})` | ✅ |
| `causal_unified` | 统一检索：它那边的事实层和因果层一起查。什么时候用：不确定要找的是'一个事实'还是'一条教训'时。 | `causal_unified({})` | ✅ |

### 插件 · code_intelligence（7 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `analyze_dependencies` | 列出项目依赖。什么时候用：想知道用了哪些库；输入 path；输出 依赖清单(按语言分组) | `analyze_dependencies({})` | ✅ |
| `ci_read_file` | 读文件内容(带行号，可指定范围)。 | `ci_read_file({"file_path": "值"})` | ✅ |
| `ci_search_content` | 在**文件内容**里搜关键词/正则。 | `ci_search_content({"query": "本地大模型怎么部署"})` | ✅ |
| `ci_search_files` | 按**文件名**找文件(支持 * ? | `ci_search_files({"pattern": "值"})` | ✅ |
| `count_code_lines` | 统计代码规模。什么时候用：想知道项目多少行、注释占比；输入 path；输出 按语言分类的行数统计 | `count_code_lines({})` | ✅ |
| `get_file_info` | 看单个文件的元信息。什么时候用：想知道大小/行数/改动时间；输入 path；输出 大小/行数/修改时间 | `get_file_info({"file_path": "值"})` | ✅ |
| `project_tree` | 生成目录树。什么时候用：想快速了解项目结构；输入 path(可选忽略规则)；输出 树状文本 | `project_tree({})` | ✅ |

### 插件 · db_helper（5 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `connect_db` | 连一个 SQLite 库。什么时候用：要对某个 .db 做查询前的第一步；输入 db_path；输出 连接结果 | `connect_db({"db_path": "值"})` | ✅ |
| `describe_table` | 看某张表的结构。什么时候用：写查询前确认列名/类型；输入 table；输出 列定义 | `describe_table({"table_name": "值"})` | ✅ |
| `export_table_json` | 把整张表导成 JSON。什么时候用：要把数据给别的程序/看全量；输入 table；输出 JSON | `export_table_json({"table_name": "值"})` | ✅ |
| `list_tables` | 列出库里所有表。什么时候用：不知道表名时先看这个；无参数；输出 表名列表 | `list_tables({})` | ✅ |
| `query_db` | 跑一条 **SELECT**(只读)。什么时候用：要查数据；输入 sql；输出 结果集。不会写库、不许 DDL/DML | `query_db({"sql": "值"})` | ✅ |

### 插件 · ip（2 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `get_ip` | 查本机公网 IP(只返回地址)。 | `get_ip({})` | ✅ |
| `get_ip_info` | 查某个 IP 的归属地/ISP/时区。 | `get_ip_info({})` | ✅ |

### 插件 · js-calc（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `js_calc` | 算数学表达式(如 (3+4)*2)。什么时候用：用户要算数且不需要解释过程；输入纯数字/运算符表达式；输出 计算结果 | `js_calc({"expr": "1+1"})` | ✅ |

### 插件 · memory（2 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `read_memory` | 读回所有已保存的记忆。什么时候用：用户问「你记得什么」或需要核对偏好；无参数；输出 记忆列表 | `read_memory({})` | ✅ |
| `save_memory` | 把用户明确要求记住的事存进长期记忆。什么时候用：用户说「记住…」「以后都…」；输入 content；输出 保存结果 | `save_memory({})` | ✅ |

### 插件 · music_generation（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `generate_music` | 本地生成一段音乐(MusicGen)。 | `generate_music({"prompt": "画一只在窗台晒太阳的猫"})` | ✅ |

### 插件 · netdoctor（3 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `net_dns` | 解析域名的 DNS 记录。 | `net_dns({"host": "值"})` | ✅ |
| `net_ip` | 查本机公网 IP(可带归属地/ISP/时区)。 | `net_ip({})` | ✅ |
| `net_port` | 测主机/端口通不通(TCP)。 | `net_port({"host": "值", "port": 1})` | ✅ |

### 插件 · nginx-vts（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `get_nginx_status` | 获取 Nginx 实时流量状态。 | `get_nginx_status({})` | ✅ |

### 插件 · rea（5 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `rea_call` | REA 逆向引擎：按工具名精确调用（tool+args）。不确定用哪个就先用 rea_do | `rea_call({"tool": "open_binary"})` | ✅ |
| `rea_do` | REA 逆向：用一句话说想干什么（如 反编译 main、看哈希、列出字符串），载体自己选工具并调 | `rea_do({"intent": "反编译 main 函数"})` | ✅ |
| `rea_help` | REA 逆向：查某个工具要哪些参数（不知道 rea_do 选对了没、或要精确调时用） | `rea_help({"tool": "open_binary"})` | ✅ |
| `rea_status` | REA 逆向引擎：查它在不在线、版本、可用工具数（不启动任何程序） | `rea_status({})` | ✅ |
| `rea_tools` | REA 逆向引擎：搜它能做哪些分析（pe、apk、反编译、frida、gguf 等） | `rea_tools({})` | ✅ |

### 插件 · scrapling_bridge（18 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `browser_session` | 会话+截图的**聚合入口**(一个工具走完 开→抓→截→关)。 | `browser_session({"action": "值"})` | ✅ |
| `bulk_fetch` | 批量用浏览器渲染抓取。什么时候用：多个页面都需渲染；输入 urls；输出 各页正文(较慢) | `bulk_fetch({"urls": []})` | ✅ |
| `bulk_get` | 一次抓多个**静态**网页(比逐个 get 快)。 | `bulk_get({"urls": []})` | ✅ |
| `bulk_stealthy_fetch` | 批量隐身抓取。什么时候用：多个都被风控拦的页面；输入 urls(≤20)；输出 各页正文(很慢，慎用) | `bulk_stealthy_fetch({"urls": []})` | ✅ |
| `close_session` | 关闭会话、释放资源。 | `close_session({"session_id": "值"})` | ✅ |
| `collect_vulnerabilities` | 什么时候用：用户要「最近的漏洞/CVE/高危漏洞」； | `collect_vulnerabilities({})` | ✅ |
| `download` | 下载**文件**(PDF/EPUB/ZIP/图片/音视频)到本地。 | `download({"url": "https://example.com"})` | ✅ |
| `fetch` | **需要浏览器渲染**时用(JS 动态页/懒加载)。 | `fetch({"url": "https://example.com"})` | ✅ |
| `get` | **抓网页首选**(纯HTTP，最快)。 | `get({"url": "https://example.com"})` | ✅ |
| `list_sessions` | 查现在还有哪些会话开着。什么时候用：排障、确认自己有没有忘记 close_session；无参数；输出 会话列表 | `list_sessions({})` | ✅ |
| `make_request` | 抓普通网页的官方同名工具(纯HTTP，最快)。 | `make_request({"url": "https://example.com"})` | ✅ |
| `open_request_session` | 开纯 HTTP 会话(保持 cookie，不开浏览器)。 | `open_request_session({})` | ✅ |
| `open_session` | 开浏览器会话，用于登录态/过验证后再抓。 | `open_session({})` | ✅ |
| `scrape_with_selector` | 只取页面**指定区块**(CSS 选择器)，且自适应抗改版。 | `scrape_with_selector({"url": "https://example.com", "selector": "值"})` | ✅ |
| `screenshot` | 给页面截图并存到本地。 | `screenshot({"url": "https://example.com", "session_id": "值"})` | ✅ |
| `session_fetch` | 在**已开浏览器会话**里抓页面(保持登录态/已过验证)。 | `session_fetch({"url": "https://example.com", "session_id": "值"})` | ✅ |
| `session_make_request` | 在**已开 HTTP 会话**里发请求(保持 cookie)。 | `session_make_request({"url": "https://example.com", "session_id": "值"})` | ✅ |
| `stealthy_fetch` | **隐身抓取，专门绕 Cloudflare/风控**。 | `stealthy_fetch({"url": "https://example.com"})` | ✅ |

### 插件 · video_generation（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `generate_video` | 本地生成一段视频(ComfyUI+Wan2.1)。 | `generate_video({"prompt": "画一只在窗台晒太阳的猫"})` | ✅ |

### 插件 · weather（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `get_weather` | 查某个城市的天气。 | `get_weather({})` | ✅ |

### 插件 · web-search（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `web_search` | 上网搜资料(百度)。 | `web_search({})` | ✅ |

### 插件 · workspace_search（3 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `ws_list_directory` | 列工作区某目录有什么。什么时候用：想看看目录里有哪些文件；输入 path；输出 条目列表 | `ws_list_directory({})` | ✅ |
| `ws_search_content` | 在工作区里按**内容**搜关键词。 | `ws_search_content({"query": "本地大模型怎么部署"})` | ✅ |
| `ws_search_files` | 在工作区里按**文件名**找文件(如 *.py)。 | `ws_search_files({"pattern": "值"})` | ✅ |

