# 工具调用清单（模型精准调用指南）

> 这份文件是 `tools/gen_tool_catalog.py` **自动生成**的，别手改 —— 
> 改了工具描述就重跑一次；`tools/test_tool_contract.py` 会校验它和实际工具表是否一致。

**全部工具：122 个 ｜ 契约合格：122 个 ｜ 不合格：0 个**

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
| `ask_user` | 向用户提问并给选项，等你拍板。什么时候用：需要你决定时；输入 question/options；输出 你的选择 | `ask_user({"question": "值"})` | ✅ |
| `background` | 后台跑命令，立即返回 job_id。什么时候用：任务耗时长等不了；输入 command；输出 任务号 | `background({"command": "dir"})` | ✅ |
| `background_result` | 查后台任务结果。什么时候用：拿到 job_id 之后要看结果；输入 job_id；输出 输出文本 | `background_result({"job_id": "值"})` | ✅ |
| `check_env` | 查电脑装没装 python/git/node/ffmpeg（只读）。什么时候用：问环境/能不能跑； | `check_env({})` | ✅ |
| `edit_file` | 在文本文件里替换首次出现的一段。什么时候用：改代码/配置的小改；输入 path/old/new；输出 结果 | `edit_file({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "old_string": "值", "new_string": "值"})` | ✅ |
| `fetch_url` | 直接读一个网址/接口的返回内容(纯HTTP，最轻)。什么时候用：只想快速拿文本/JSON，不需要渲染或过风控； | `fetch_url({"url": "https://example.com"})` | ✅ |
| `grep_files` | 在文件**内容**里搜关键词/正则。什么时候用：找某段代码/配置在哪； | `grep_files({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "pattern": "值"})` | ✅ |
| `list_files` | 列目录里有什么。什么时候用：要知道某目录下的文件清单；输入 path；输出 条目列表(不含内容) | `list_files({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `open_app` | 用系统默认方式打开一个应用/文件/网址。什么时候用：用户说「打开 XX」； | `open_app({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `read_file` | 读文本文件内容。什么时候用：查看文件写了什么； | `read_file({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `run_command` | 跑一条系统命令并回显输出(PowerShell 语法)。什么时候用：要真的执行程序/脚本/安装/查系统信息； | `run_command({"command": "dir"})` | ✅ |
| `search_files` | 按文件名找文件(glob)。什么时候用：找某个文件在哪； | `search_files({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "pattern": "值"})` | ✅ |
| `suggest_organize` | 扫目录给出整理建议（只读，不移动文件）。什么时候用：想整理桌面/文件夹；输入 path；输出 建议清单 | `suggest_organize({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe"})` | ✅ |
| `write_file` | 新建/覆盖写入文件(自动建目录)。什么时候用：要产出文件(代码/网页/文档/配置)； | `write_file({"path": "C:\\\\Windows\\\\System32\\\\notepad.exe", "content": "值"})` | ✅ |

### 插件 · archify（15 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `archify_batch` | 一次画多张图。什么时候用：用户要一批图；输入 items 数组；输出 每张的结果 | `archify_batch({"items": []})` | ✅ |
| `archify_check` | 检查已生成的 HTML 是否正常。什么时候用：交付后自检；输入 html_path；输出 检查结果 | `archify_check({"html_path": "值"})` | ✅ |
| `archify_compare` | 对比两张架构图并给差异。什么时候用：改版前后比一比(仅 architecture)；输入两份 spec；输出 差异清单 | `archify_compare({"base_json": "值", "head_json": "值"})` | ✅ |
| `archify_deliver` | **最终交付**：渲染并生成正式 HTML。什么时候用：validate 通过之后； | `archify_deliver({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_doctor` | 体检 Archify 环境(Node/依赖/schema 是否齐)。什么时候用：画图报错、或用户让你查环境； | `archify_doctor({})` | ✅ |
| `archify_guide` | 按场景推荐图表类型+配方+官方提示词。什么时候用：读完 SKILL.md 后、决定画哪种图之前； | `archify_guide({"scenario": "值"})` | ✅ |
| `archify_inspect` | 只看结构、不渲染。什么时候用：想快速确认节点/关系结构对不对； | `archify_inspect({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_metrics` | 看画图调用的统计(成功/失败/耗时)。什么时候用：排查画图为什么慢/失败；无参数；输出 统计表 | `archify_metrics({})` | ✅ |
| `archify_preview` | 预览渲染(服务端用，不开浏览器)。什么时候用：想先看看效果再决定交付；输入同 render；输出 预览结果 | `archify_preview({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_read_example` | 读该类型的**完整示例 JSON**。什么时候用：写 JSON 前照着抄结构(比只看 schema 稳)； | `archify_read_example({"diagram_type": "值"})` | ✅ |
| `archify_read_schema` | 什么时候用：按 archify_guide 推荐的类型，**生成 JSON 之前**读； | `archify_read_schema({"diagram_type": "值"})` | ✅ |
| `archify_read_skill` | 读 Archify 完整技能文档。什么时候用：**每次开始画图的第一步**(同一会话只读一次)； | `archify_read_skill({})` | ✅ |
| `archify_render` | 把 JSON 渲染成 HTML(基础版，不开浏览器)。什么时候用：只想拿文件、不需要报告； | `archify_render({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_validate` | **交付前必做**：校验 JSON 是否符合规范。什么时候用：写完 JSON 立刻校验； | `archify_validate({"diagram_type": "值", "spec_json": "值"})` | ✅ |
| `archify_visual_check` | 对已生成的 HTML 做**视觉**检查。什么时候用：交付后确认渲染质量(标签重叠等)； | `archify_visual_check({"html_path": "值"})` | ✅ |

### 插件 · asset_intel（3 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `asset_intel_lookup` | 给 IP 查它命中了哪些漏洞(免费，无需 Key)。什么时候用：用户给了具体 IP 想知道有没有已知漏洞； | `asset_intel_lookup({"ips": "值"})` | ✅ |
| `asset_intel_search` | 什么时候用：用户要「含这些漏洞的 IP」； | `asset_intel_search({"query": "本地大模型怎么部署"})` | ✅ |
| `asset_intel_status` | 看资产测绘数据源能不能用。什么时候用：反查失败或用户问「能查 IP 吗」； | `asset_intel_status({})` | ✅ |

### 插件 · causal_memory（6 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `causal_counterfactual` | 反事实对比（因果记忆）：两个候选方案，各自过去的结果分布是什么。什么时候用：在两个方案之间拿不定主意时。 | `causal_counterfactual({"decision": "值", "alternative": "值", "task_tag": "值"})` | ✅ |
| `causal_record` | 记一条「决策 → 结果」到因果记忆。什么时候用：**做完一件事、拿到结果之后**（尤其是踩坑、返工、意外成功）。 | `causal_record({"decision": "值", "outcome": "值", "relation": "值", "task_tag": "值", "context": "值"})` | ✅ |
| `causal_report` | 因果记忆的预测账本：以前那些判断押对了多少（总览/按领域）+ 还没结算的。什么时候用：想知道这套经验到底准不准的时候。 | `causal_report({})` | ✅ |
| `causal_search` | 什么时候用：遇到**非平凡的决策**之前（排障、换方案、改架构），先看看以前踩过什么坑。 | `causal_search({"query": "本地大模型怎么部署", "task_tag": "值", "limit": "值"})` | ✅ |
| `causal_trace` | 什么时候用：单看一个原因解释不了故障时。 | `causal_trace({"outcome_description": "值", "max_depth": "值"})` | ✅ |
| `causal_warn` | 什么时候用：要执行有副作用的操作前（改配置、删/覆盖文件、重启服务、装东西、动显卡/显存）。 | `causal_warn({"action": "值", "task_tag": "值"})` | ✅ |

### 插件 · causal_memory_ext（10 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `causal_facts` | 查因果记忆**它自己那边**的事实层（不是小焦自己的记忆库，两套别混）。什么时候用：明确知道东西记在它那边时。 | `causal_facts({"query": "本地大模型怎么部署", "limit": "值"})` | ✅ |
| `causal_invalidate` | 库里仍留痕）。什么时候用：发现某条经验已经不对了（世界变了、当时的结论是错的）。 | `causal_invalidate({"edge_id": "值", "reason": "值"})` | ✅ |
| `causal_invalidate_pattern` | 什么时候用：它把两条不相干的经验算成'相似'、或把不该算矛盾的算成矛盾时。 | `causal_invalidate_pattern({"edge_id": "值", "reason": "值"})` | ✅ |
| `causal_lesson` | 从库里多条散着的边**重建一条教训**（比单条边更适合直接照做）。什么时候用：要总结'这一类事我以前吃了什么亏'时。 | `causal_lesson({"query": "本地大模型怎么部署", "max_edges": "值"})` | ✅ |
| `causal_memory_map` | 什么时候用：想确认'它到底学过什么'，或者吃完一顿操作后看看记进去没有。 | `causal_memory_map({"limit": "值"})` | ✅ |
| `causal_patterns` | 什么时候用：怀疑自己前后做法不一致、或想找同类经验时。 | `causal_patterns({"query": "本地大模型怎么部署", "limit": "值"})` | ✅ |
| `causal_remember` | 什么时候用：刚做完一件有教训的事，懒得一条条手动记。 | `causal_remember({"messages": "值", "date": "值"})` | ✅ |
| `causal_resolve` | 什么时候用：觉得库里同一个做法有两种相反结论时。 | `causal_resolve({"apply": "值"})` | ✅ |
| `causal_trace_one` | 什么时候用：只想找最直接的原因（要找整条链用 causal_trace）。 | `causal_trace_one({"outcome_description": "值"})` | ✅ |
| `causal_unified` | 统一检索：它那边的事实层和因果层一起查。什么时候用：不确定要找的是'一个事实'还是'一条教训'时。 | `causal_unified({"query": "本地大模型怎么部署", "limit": "值"})` | ✅ |

### 插件 · code_intelligence（7 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `analyze_dependencies` | 列出项目依赖。什么时候用：想知道用了哪些库；输入 path；输出 依赖清单(按语言分组) | `analyze_dependencies({})` | ✅ |
| `ci_read_file` | 读文件内容(带行号，可指定范围)。什么时候用：要**看代码/配置内容**； | `ci_read_file({"file_path": "值"})` | ✅ |
| `ci_search_content` | 在**文件内容**里搜关键词/正则。什么时候用：找某个函数/配置写在哪； | `ci_search_content({"query": "本地大模型怎么部署"})` | ✅ |
| `ci_search_files` | )。什么时候用：知道大概文件名、不知道在哪个目录； | `ci_search_files({"pattern": "值"})` | ✅ |
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

### 插件 · ebook（2 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `ebook_grab` | 把公开电子书的文件下载到本地，遇付费墙跳过并说明。什么时候用：要成批存书；输入 url+out_dir | `ebook_grab({"url": "https://example.com", "out_dir": "值", "limit": 1})` | ✅ |
| `ebook_manifest` | 解析公开书站目录页成书目清单（可存 CSV/MD）。什么时候用：要书目一览；输入 url；输出清单 | `ebook_manifest({"url": "https://example.com", "out": "值", "limit": 1})` | ✅ |

### 插件 · evolve（2 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `evolve_report` | 看它现在最弱的是哪几处、下一步该改什么。什么时候用：想知道短板/怎么变强；输入 limit；输出 改进清单 | `evolve_report({})` | ✅ |
| `experience_stats` | 看它踩过哪些坑、能力自增长成功了多少次。什么时候用：想知道它学过什么；输入 无；输出 统计 | `experience_stats({})` | ✅ |

### 插件 · forge（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `forge_plugin` | 你说要什么能力，它自己写插件补上。什么时候用：现有工具做不到的新能力；输入 need；输出 校验结果 | `forge_plugin({"need": "值"})` | ✅ |

### 插件 · gen_cap_20261027_173718（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `cn_num_to_int` | 把中文数字（一百零五、两千三百、十五）转成阿拉伯数字。什么时候用：文本里的中文数字要参与计算；输入 text；输出 数字 | `cn_num_to_int({"text": "你好"})` | ✅ |

### 插件 · gen_x_20261027_191800（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `int_to_cn_num` | 把阿拉伯数字（3020、105）转成中文数字（三千零二十）。什么时候用：要按中文习惯念数字； | `int_to_cn_num({"text": "你好"})` | ✅ |

### 插件 · ip（2 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `get_ip` | 查本机公网 IP(只返回地址)。什么时候用：只要一个 IP 字符串； | `get_ip({})` | ✅ |
| `get_ip_info` | 查某个 IP 的归属地/ISP/时区。什么时候用：**已经知道**要查哪个 IP； | `get_ip_info({})` | ✅ |

### 插件 · js-calc（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `js_calc` | 算数学表达式(如 (3+4)*2)。什么时候用：用户要算数且不需要解释过程；输入纯数字/运算符表达式；输出 计算结果 | `js_calc({"expr": "1+1"})` | ✅ |

### 插件 · memory（2 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `read_memory` | 读回所有已保存的记忆。什么时候用：用户问「你记得什么」或需要核对偏好；无参数；输出 记忆列表 | `read_memory({})` | ✅ |
| `save_memory` | 把用户明确要求记住的事存进长期记忆。什么时候用：用户说「记住…」「以后都…」；输入 content；输出 保存结果 | `save_memory({"content": "值"})` | ✅ |

### 插件 · music_generation（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `generate_music` | 本地生成一段音乐(MusicGen)。什么时候用：用户要「来段音乐/BGM」； | `generate_music({"prompt": "画一只在窗台晒太阳的猫"})` | ✅ |

### 插件 · netdoctor（3 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `net_dns` | 解析域名的 DNS 记录。什么时候用：要知道某域名指向哪个 IP/有没有邮件记录； | `net_dns({"host": "值"})` | ✅ |
| `net_ip` | 查本机公网 IP(可带归属地/ISP/时区)。什么时候用：用户问「我的 IP/公网 IP/我在哪」； | `net_ip({})` | ✅ |
| `net_port` | 测主机/端口通不通(TCP)。什么时候用：排查「服务起没起/端口开没开」； | `net_port({"host": "值", "port": 1})` | ✅ |

### 插件 · nginx-vts（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `get_nginx_status` | 获取 Nginx 实时流量状态。什么时候用：用户问「nginx 状态」「流量」「请求数」「错误数」「响应时间」时。 | `get_nginx_status({})` | ✅ |

### 插件 · proof（11 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `audit_answer` | 什么时候用：用户问「这句话有依据吗/你凭什么这么说/审计一下」； | `audit_answer({})` | ✅ |
| `audit_history` | 审最近若干轮，给汇总（支持率、复算一致率、失效产物）。什么时候用：用户问「你最近说的话都靠得住吗/把最近几轮都审一遍」； | `audit_history({})` | ✅ |
| `cross_check` | 什么时候用：用户问「你确定吗」「换个模型看看」「交叉核验一下」，或答案涉及要害事实； | `cross_check({})` | ✅ |
| `evidence_stats` | 什么时候用：用户问「你的证据账本有多少东西/有没有被改过」； | `evidence_stats({})` | ✅ |
| `evolve_gate` | 什么时候用：用户问「你自己改了什么/为什么改/能不能自己调得更好」； | `evolve_gate({})` | ✅ |
| `parity_report` | 换火种会不会变傻：裸模型 vs 装载体跑同一批题的实测。什么时候用：用户问「换个模型会不会变笨/凭什么说模型可替换」； | `parity_report({})` | ✅ |
| `project_list` | 看最近的项目（哪个没跑完、哪个卡住了）。什么时候用：忘了项目号，或者想看看有没有上次没做完的； | `project_list({})` | ✅ |
| `project_resume` | 接着跑一个没做完的项目（重启后也能接，因为状态在磁盘上）。什么时候用：用户说「接着做/继续那个项目」； | `project_resume({"project_id": "值"})` | ✅ |
| `project_start` | 把一件要很久的事交给它（多里程碑、跨重启、有预算）。什么时候用：一件事要几个阶段、可能要几小时几天； | `project_start({"goal": "值"})` | ✅ |
| `project_status` | 查项目做到哪了（每个里程碑的验收结论、花了多少预算）。什么时候用：开了长项目要跟进； | `project_status({"project_id": "值"})` | ✅ |
| `proof_panel` | 什么时候用：用户问「给我看看你的凭据/自证面板在哪」； | `proof_panel({})` | ✅ |

### 插件 · rea（5 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `rea_call` | 按工具名精确调用 REA。什么时候用：已知工具名与参数；输入 tool/args(JSON)；输出 结果 | `rea_call({"tool": "open_binary"})` | ✅ |
| `rea_do` | 一句话说想逆向什么，载体自己选工具。什么时候用：只说目标不说工具；输入 task；输出 结果 | `rea_do({"intent": "反编译 main 函数"})` | ✅ |
| `rea_help` | 查 REA 某工具要哪些参数。什么时候用：调之前确认参数；输入 tool；输出 参数表 | `rea_help({"tool": "open_binary"})` | ✅ |
| `rea_status` | REA 逆向引擎在线状态与工具数。什么时候用：先确认它活着；输入 无；输出 版本/工具数 | `rea_status({})` | ✅ |
| `rea_tools` | 按关键词搜 REA 能做什么（229 个工具目录）。什么时候用：不确定用哪个工具；输入 keyword；输出 清单 | `rea_tools({})` | ✅ |

### 插件 · scrapling_bridge（18 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `browser_session` | 什么时候用：不想分步调 open/session_fetch/close； | `browser_session({"action": "值"})` | ✅ |
| `bulk_fetch` | 批量用浏览器渲染抓取。什么时候用：多个页面都需渲染；输入 urls；输出 各页正文(较慢) | `bulk_fetch({"urls": []})` | ✅ |
| `bulk_get` | 一次抓多个**静态**网页(比逐个 get 快)。什么时候用：给了多个 URL 且都是普通页； | `bulk_get({"urls": []})` | ✅ |
| `bulk_stealthy_fetch` | 批量隐身抓取。什么时候用：多个都被风控拦的页面；输入 urls(≤20)；输出 各页正文(很慢，慎用) | `bulk_stealthy_fetch({"urls": []})` | ✅ |
| `close_session` | 关闭会话、释放资源。什么时候用：session_fetch/screenshot 做完立刻关，别让会话堆着； | `close_session({"session_id": "值"})` | ✅ |
| `collect_vulnerabilities` | **漏洞清单唯一入口**(NVD 结构化数据)。什么时候用：用户要「最近的漏洞/CVE/高危漏洞」； | `collect_vulnerabilities({})` | ✅ |
| `download` | 下载**文件**(PDF/EPUB/ZIP/图片/音视频)到本地。什么时候用：URL 指向文件而不是网页； | `download({"url": "https://example.com"})` | ✅ |
| `fetch` | **需要浏览器渲染**时用(JS 动态页/懒加载)。什么时候用：get 只拿到空壳或内容不全； | `fetch({"url": "https://example.com"})` | ✅ |
| `get` | **抓网页首选**(纯HTTP，最快)。什么时候用：静态页/接口/JSON 一律先用它； | `get({"url": "https://example.com"})` | ✅ |
| `list_sessions` | 查现在还有哪些会话开着。什么时候用：排障、确认自己有没有忘记 close_session；无参数；输出 会话列表 | `list_sessions({})` | ✅ |
| `make_request` | 抓普通网页的官方同名工具(纯HTTP，最快)。什么时候用：和 get 完全等价，脚本/老习惯用这个名； | `make_request({"url": "https://example.com"})` | ✅ |
| `open_request_session` | 开纯 HTTP 会话(保持 cookie，不开浏览器)。什么时候用：要连续请求同一站点且需带 cookie； | `open_request_session({})` | ✅ |
| `open_session` | 开浏览器会话，用于登录态/过验证后再抓。什么时候用：目标页要登录或要先过 Cloudflare 挑战； | `open_session({})` | ✅ |
| `scrape_with_selector` | 只取页面**指定区块**(CSS 选择器)，且自适应抗改版。什么时候用：只要某一块(正文/列表)或站点常改版； | `scrape_with_selector({"url": "https://example.com", "selector": "值"})` | ✅ |
| `screenshot` | 给页面截图并存到本地。什么时候用：需要页面长什么样/留证据； | `screenshot({"url": "https://example.com"})` | ✅ |
| `session_fetch` | 在**已开浏览器会话**里抓页面(保持登录态/已过验证)。什么时候用：先 open_session 再抓； | `session_fetch({"url": "https://example.com"})` | ✅ |
| `session_make_request` | 什么时候用：open_request_session 之后； | `session_make_request({"url": "https://example.com"})` | ✅ |
| `stealthy_fetch` | 什么时候用：get 和 fetch 都失败(403/挑战页)才用，开销最大； | `stealthy_fetch({"url": "https://example.com"})` | ✅ |

### 插件 · skill（2 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `skill_list` | 看它固化了哪些成套做法（多步任务的工具序列）。什么时候用：想知道它学会了什么；输入 limit；输出 技能清单 | `skill_list({})` | ✅ |
| `skill_recall` | 问「这类事以前怎么做的」，返回当时的工具序列。什么时候用：想复用或核验旧路径；输入 question；输出 序列与耗时 | `skill_recall({"question": "值"})` | ✅ |

### 插件 · task（3 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `task_list` | 看最近开过哪些任务。什么时候用：忘了任务号；输入 limit；输出 任务清单 | `task_list({})` | ✅ |
| `task_start` | 给一个目标，它自己拆步骤并做完（后台跑）。什么时候用：一件事要好几步；输入 goal；输出 任务号 | `task_start({"goal": "值"})` | ✅ |
| `task_status` | 查任务做到哪了、每步结果和验收结论。什么时候用：开了长任务要跟进；输入 task_id；输出 进度与每步详情 | `task_status({"task_id": "值"})` | ✅ |

### 插件 · video_generation（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `generate_video` | 本地生成一段视频(ComfyUI+Wan2.1)。什么时候用：用户要「生成/画一段视频」； | `generate_video({"prompt": "画一只在窗台晒太阳的猫"})` | ✅ |

### 插件 · weather（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `get_weather` | 查某个城市的天气。什么时候用：用户问「X 天气怎么样」； | `get_weather({"city": "济南"})` | ✅ |

### 插件 · web-search（1 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `web_search` | 什么时候用：查新闻/百科/资料这类**网页信息**（问天气用 get_weather，问本机 IP 用 net_ip）； | `web_search({"query": "本地大模型怎么部署"})` | ✅ |

### 插件 · workspace_search（3 个工具）

| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |
| --- | --- | --- | --- |
| `ws_list_directory` | 列工作区某目录有什么。什么时候用：想看看目录里有哪些文件；输入 path；输出 条目列表 | `ws_list_directory({})` | ✅ |
| `ws_search_content` | 在工作区里按**内容**搜关键词。什么时候用：在项目里找某段代码/配置； | `ws_search_content({"query": "本地大模型怎么部署"})` | ✅ |
| `ws_search_files` | 在工作区里按**文件名**找文件(如 *.py)。什么时候用：在小焦工作区里找文件； | `ws_search_files({"pattern": "值"})` | ✅ |

