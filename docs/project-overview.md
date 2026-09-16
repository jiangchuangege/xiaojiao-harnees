# 小焦 · 项目总览

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 待审 |

**摘要**：本文是新会话的入口文档 —— 先读它，再动手改代码。它给出项目定位、必须遵守的架构约定、
关键文件清单、当前质量基线与踩坑清单。文中数字均为本轮实测，复核命令写在对应小节里。

## 目录

- [1. 这是什么](#1-这是什么)
- [2. 架构约定](#2-架构约定)
- [3. 关键文件清单](#3-关键文件清单)
- [4. 启动与配置](#4-启动与配置)
- [5. 安全模型](#5-安全模型)
- [6. 测试与质量闸门](#6-测试与质量闸门)
- [7. 踩坑清单](#7-踩坑清单)
- [8. 待办与历史遗留](#8-待办与历史遗留)
- [9. 安全第一批任务流水](#9-安全第一批任务流水)
- [10. 后续路线与发布策略](#10-后续路线与发布策略)
- [参考](#参考)
- [变更记录](#变更记录)

---

## 1. 这是什么

小焦（XiaoJiao）是一个**本地部署的联网搜索 AI 助手**：Flask Web 应用 + 自研小脑（MiniGPT 蒸馏模型）
+ 可选云端大脑（OpenAI 兼容接口）+ 一套工具与插件（网页抓取、漏洞情报、资产测绘、画图、视频、播客、音乐）。

一次调用的链路：

```text
用户 / DSH / 客户端
  → 小焦 Web（Flask，xiaojiao_app.py，默认 5000）
  → agent_run（上下文融合 + 意图识别 + 装载工具子集 + 记忆检索）
  → 火种（本地 llama-swap:9292 / 云端 OpenAI 兼容接口）
  → 工具（内置 12 个 + plugins/ 插件，共 77 个）
```

架构细节见 [architecture.md](architecture.md)，设计动机见 [design-philosophy.md](design-philosophy.md)。

---

## 2. 架构约定

改代码前必须知道这六条，它们都是踩过坑之后定下来的。

1. **提示词分层是硬约定**：`系统提示词 = role（纯人设） + 检索铁律 + 工具铁律 + 插件清单`。
   `role` 只许放人设；规则与清单由代码独立拼接，`compose_system_prompt()` 是**唯一**合成入口。
   原因：规则一旦写进 `role`，就会出现「改人设丢规则、加插件要手改人设、role 越写越长」。
2. **控制文件是唯一配置源**：`xiaojiao_control.json`（**不入库**，由 `.gitignore` 第 157 行的
   `xiaojiao_control*.json` 规则忽略）。模板是 `xiaojiao_control.json.example`。
   改完文件后 `maybe_reload_control()` 自动热重载。
3. **插件契约**：`plugins/*.py` 实现 `get_tool_descriptions()` 与 `execute()`；工具名全局唯一
   （重名时 `_build_tools()` 跳过并告警）；描述必须写清「什么时候用」；插件异常绝不抛给调用方，
   一律转成中文提示。
4. **两条启动路径必须共用同一套规则**：`xiaojiao_app.py` 与一键启动器 `start_xiaojiao.py`。
   历史上它们各写各的（启动器写死 `0.0.0.0`），把安全防护绕过去了。监听地址这类决策已抽成
   `bind_host()`，**两边都调它**，不要再复制一份。
5. **一个任务一个 commit**：中文 message；改前先备份；中间过程不打 tag、不推送。
6. **不许扩散**：改 A 模块不要顺手动前端 HTML、视频、播客、音乐、Scrapling。

---

## 3. 关键文件清单

行数为本轮实测（`io.open(...)` 逐文件统计），不是估计。

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `xiaojiao_app.py` | 10898 | **主程序**：配置加载、提示词分层、载体编排 `agent_run`、工具循环、53 条唯一 HTTP 路由、内嵌前端 |
| `start_xiaojiao.py` | 411 | 一键启动器：大脑 + Web + 可选 N.E.K.O.；监听地址必须走 `bind_host()` |
| `xiaojiao_control.json` | — | **实际配置**（不入库）：brain / role / capabilities / behavior / models / dsh |
| `xiaojiao_control.json.example` | — | 配置模板（入库），含各字段中文注释 |
| `core/`（11 个子包） | 37 个模块 | 载体器官：记忆、检索、健康、元认知、思维流、世界、自主性、中央黑板、人格 |
| `plugins/*.py` | 11 个插件 | Python 插件；`plugins/scrapling_bridge.py` 3031 行，是抓取主力，对外 18 个工具 |
| `plugins/netdoctor.js`、`plugins/ip.json`、`plugins/*.skill.md` | — | 同一批工具的 `js` / `json` / `md` 形态 |
| `app_monitor.py` | — | 大脑仓库监控面板：`/monitor`、`/api/monitor` |
| `video_service/` `podcast_service/` `music_service/` | — | 重依赖服务，经 Blueprint 挂进主程序（音乐为外部 ACE-Step 服务） |
| `tools/check_principles.py` | 251 | 12 条项目铁律的机器化审计（P1 至 P12） |
| `tools/check_docs.py` | 301 | 文档与代码一致性（链接 / 路径 / 端点 / 工具名） |
| `tools/check_secrets.py` | 201 | 明文密钥自查（`--include-logs` 连 `logs/` 备份一起扫） |
| `tools/check_mermaid.py` | 147 | Mermaid 图语法校验（`--all` 递归扫描） |
| `tools/check_prompt_size.py` | — | 单次请求体检：各段 token 占比、各意图的工具装载量 |
| `tools/dangerous_commands.txt` | — | 危险命令黑名单（一行一个正则，改词不用动代码） |
| `tools/audit_static.py` | — | 静态质量审计（`check_principles` 会调用） |
| `tests/stress/run_all.py` | 87 | **全量测试总入口**（4 个套件） |
| `tests/stress/test_units.py` | 345 | 离线用例 92 条（配置 / 会话 / 指标 / 脱敏 / 展示 / 渲染契约 / 漏洞聚合逻辑 / 参数校验） |
| `tests/stress/test_app_logic.py` | 410 | 应用逻辑用例 104 条（检索词清洗 / 漏洞意图 / 提示词铁律 / 工具注册 / 热重载） |
| `tests/stress/test_security.py` | 167 | 安全用例 18 条（SSRF / robots / 限速 / 脱敏 / 穿越 / 命令端点 / 无明文密钥） |
| `tests/stress/test_network.py` | 188 | 联网用例 35 条（真实抓取 / 批量 / 会话 / 对抗 / NVD 真实接口） |
| `README.md` | 898 | 对外说明：安装、用法、功能总览、抓取章节、安全说明 |
| `CHANGELOG.md` | 704 | 版本记录（版本号以它为准） |
| `docs/*.md` | 顶层 39 个 | 分主题文档（架构、设计哲学、安全审计、抓取、大脑切换、测试报告…）；含子目录共 57 个 |

`tests/stress/` 下另有 **独立实机脚本**，`run_all.py` 不跑它们（需要服务在运行，或会连打 `/api/chat`）：
`live_check.py`（33 处断言）、`ui_check.py`（Playwright 真浏览器渲染）、`ui_style_check.py`、
`preset_check.py`、`stability_30m.py`。

---

## 4. 启动与配置

```powershell
python xiaojiao_app.py                 # 只跑 Web（默认 http://127.0.0.1:5000）
python start_xiaojiao.py               # 一键：大脑 + Web + 可选 N.E.K.O.
python tests/stress/run_all.py         # 全量测试
```

**密钥读取顺序**：环境变量 `XIAOJIAO_API_KEY` 优先，其次控制文件的 `brain.api.api_key`。
推荐只放在环境变量里：

```powershell
setx XIAOJIAO_API_KEY "sk-你的密钥"     # 永久（需重开终端）
$env:XIAOJIAO_API_KEY="sk-..."          # 只对当前窗口生效
python tools/check_secrets.py           # 自查是否还有明文残留
```

控制文件里与运行相关的开关都在 `capabilities` 下：

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `lan_access` | `false` | `true` 才允许局域网访问，且必须同时配 `access_token` |
| `access_token` | `""` | 非本机请求需带 `X-Auth-Token` 或 `?token=` |
| `full_access` | `false` | `false` 时危险命令需二次确认；`true` 则不询问直接执行 |
| `rate_limit_per_minute` | `30` | 聊天接口每分钟次数上限（突发额度 5） |
| `run_tools` | `true` | 是否允许调用工具 |
| `context_len` | `20` | 进上下文的历史轮数上限 |

另有两个与显存策略相关的键：`brain.keep_warm`（视频模型是否常驻）、`brain.llama_swap_port`
（多大脑热切换端口，默认 9292）。

---

## 5. 安全模型

| 机制 | 位置 | 说明 |
| --- | --- | --- |
| 只听本机 | `bind_host()` | 默认 127.0.0.1；只有 `lan_access=true` **且** `access_token` 非空才听 0.0.0.0 |
| 访问令牌 | `_require_token()` | 非本机请求必须带 `X-Auth-Token` 或 `?token=`；免鉴权路径为 `/health`、`/favicon.ico`、`/api/central` |
| 危险命令确认 | `is_dangerous()` | 只对危险命令要确认，安全命令直接执行；`full_access=true` 则完全不问 |
| 删除红线 | `core/security/no_delete.py` | 删除类操作在载体层硬拦截，**与权限开关无关** |
| 密钥不落文件 | `_resolve_llm_key()` | 环境变量优先；切模型也不把 `models[].api_key` 搬回 `brain.api.api_key` |
| 聊天限流 | `rate_limited()` | 令牌桶，默认每分钟 30 次、突发 5，`capabilities.rate_limit_per_minute` 可调 |
| 抓取防护 | `plugins/scrapling_bridge.py` | SSRF 拦截（含数值型绕过）、robots.txt 合规、同域限速、熔断、日志脱敏 |
| 探活 | `GET /health` | 免鉴权，返回 `{"ok": true, "version": "1.0"}` |

完整结论与验证方法见 [security-audit.md](security-audit.md)；密钥相关操作见 `README.md` 的「安全说明」一节。

---

## 6. 测试与质量闸门

本轮实测的四条命令与结果：

```powershell
python tests/stress/run_all.py                    # 全量 249/249 · 通过率 100.00% · 128.0s
python tools/check_principles.py                  # 原理 9/12（P1、P6、P8 未过）
python tools/check_docs.py                        # 错误 0 · 警告 18
python -m ruff check --select E9,F63,F7,F82 .     # 真 bug 级 3 处
```

- **全量 249 条**：离线 92 ｜ 应用逻辑 104 ｜ 安全 18 ｜ 联网 35；失败 0、跳过 0。
- `python tests/stress/run_all.py --offline` 实测 215 条（214 通过 + 1 条联网套件跳过）。
- 退出码：达标 `0`，低于门槛 `1`。注意在 PowerShell 里带 `2>&1` 跑时，宿主可能把 stderr 记成错误、
  `$LASTEXITCODE` 显示 1 —— 那不是用例失败，看脚本自己的汇总行。
- 文档闸门会把文档里「反引号包起来的仓库路径」逐个核对是否存在，写文档不要写不存在的路径。
- `check_principles.py` 的 P1 直接调用 ruff 的真 bug 级规则集、P8 调用 `check_docs.py`，
  所以上面这些数字是联动变化的：文档或代码一改，重跑即可看到新结论。

---

## 7. 踩坑清单

都是真实踩过的，别重复。

1. **往函数里插注释行导致 IndentationError**。`reload_control()` 这类函数体内插注释必须保持同级缩进；
   改完立刻 `python -c "import ast,io; ast.parse(...)"`，再看 ruff。
2. **正在运行的小焦实例会重写整个控制文件**：`/api/persona`、`/api/access`、`_save_control()`
   都会按内存里的状态把 `xiaojiao_control.json` 整份重写，手改的值会被改回去
   （实测把测试用的 `rate_limit_per_minute: 2` 又写回了文件）。改配置前先停实例，改完复查。
3. **PowerShell 会吃掉命令行参数里的双引号**：用命令行参数传带引号的 JSON 片段会写出非法 JSON。
   要改 JSON 就用脚本文件读取替换文本。
4. **令牌桶必须加锁**：Flask 是多线程的，读-改-写不加锁时并发请求会各自看到还有令牌而突发放过去
   （实测并发打 5 次，本该只过 2 次）。
5. **前端 `fetch('/api/chat')` 不检查 `r.ok`**：它直接读 `d.answer`，还会调 `setToolsOn(d.tools_on)`。
   错误响应（如 429）也要带上 `answer` 与 `tools_on`，否则界面是空白气泡加工具开关被误判成关。
6. **测限流必须并发打**：单次回答要十几秒，串行打的话令牌桶早就回填了。
7. **两条启动路径各写各的等于防护被绕过**：只改 `main()` 而启动器里仍写死 `0.0.0.0`，
   服务照样暴露到同网段。凡「启动期决策」都要抽成共用函数。
8. **静态检查查不出「返回值类型变了」**：曾差点把 `return "字符串"` 插进返回**列表**的函数里，
   ast 与 ruff 都不会报。改完对关键函数做一次针对性自检。
9. **`typing` 在主程序里其实没导入**：`xiaojiao_app.py` 里出现的 `from typing import ...`
   是插件示例模板字符串的一部分（实测在 7614 行），不是真代码。别在模块前部写
   `Dict[str, Any]` 这类注解，会 NameError。
10. **代码自带的扫描器别只扫根目录**：`check_secrets` 起初没扫 `logs/`，默认扫描报「干净」，
    而备份里还躺着明文密钥。假阴性比不报更危险，现已补 `--include-logs`。

---

## 8. 待办与历史遗留

### 已解决：切模型会把明文密钥写回控制文件

**现象**：控制文件 `xiaojiao_control.json` 的 `models` 数组里每个模型各自带一份 `api_key`。
在设置页切换模型时，程序把选中模型的那份 `api_key` 搬进 `brain.api.api_key`，
于是刚清空的明文密钥又被写回文件。

**修法**（安全第一批·任务 C，commit `8c2acb6`）：

1. `/api/model/select` 不再搬 `m.get("api_key")`，只切模型名，`brain["api"]["api_key"]` 一律写 `""`。
2. 云端探测改用解析后的 key：`_cloud_key_problem(base, _resolve_llm_key(brain), model)`。
3. `_cloud_key_problem()` 增加「没有 Key」分支，直接提示去设环境变量。
4. 清空控制文件里 `models[*].api_key` 的历史明文。

**验收**：真实走 `/api/model/select` 来回切换 3 次，每次切完 `brain/api/api_key` 长度都是 0，
`LLM_KEY` 始终等于环境变量；再往**内存里**塞一把假明文切一次，捕获到的 `brain["api"]`
仍是 `{"api_key": ""}`，说明「搬明文」的路径确实断了。

### 尚未处理

| 事项 | 说明 |
| --- | --- |
| `web_monitor.py` 与 `xiaojiao_tools.py` 是独立入口 | 两者各自是独立 Flask 程序，默认都占 5000，与主程序互斥，主程序**不**挂载它们。`web_monitor.py` 的三个路由（看板首页、状态接口、蒸馏触发接口）因此不在主程序路由表里 —— 早先文档把它们当成主程序接口，是错的 |
| `learn_from_neko.py` 不解析命令行参数 | 脚本只执行一轮 `learn_once()` 就退出；`start_xiaojiao.py` 传入的 `--daemon --interval 300` 不产生循环效果，启动器打印的「每 5 分钟学一次」目前不成立 |
| 实机脚本不在 `run_all.py` 里 | `live_check.py`、`ui_check.py`、`preset_check.py`、`stability_30m.py` 改动主程序后建议单独跑一次 |
| ruff 真 bug 级规则未清零 | **2026-09-16 更正：已全过（0 处）**。原记录写"实测 3 处：`core/world/firewall.py` 的 `__all__` 含未定义名；`xiaojiao_app.py` 两处未定义变量" —— 那 3 处已经修完，现在 `ruff check --select E9,F63,F7,F82 .` 报 `All checks passed` |
| `check_principles.py` 未全过 | **2026-09-16 更正：实测 10/12**。原记录写"9/12，未过 P1（ruff）、P6、P8" —— 已过期：**P1 与 P8 现已通过**，现在未过的是 **P6**（面向用户的英文 error 文案 1 处）与 **P9**（版本号自洽，`neko_plugin` README 引的 `v3.13.13` 被判成"查无此版"） |

---

## 9. 安全第一批任务流水

八个 commit 均已在仓库中核实存在。

| 任务 | 内容 | commit |
| --- | --- | --- |
| 1 | Web 默认只听 127.0.0.1 + 访问令牌鉴权 | `04298a5` |
| 2 | 危险命令黑名单独立文件 + 只对危险命令要确认 | `8265ece` |
| 3 | 密钥优先读环境变量 + `tools/check_secrets.py` | `0121627` |
| 4 | 聊天接口令牌桶限流（30 每分钟，突发 5，可配置） | `c0f40cd` |
| A | 启动器不再写死 `0.0.0.0`（补任务 1 的漏） | `b6d93a1` |
| B | 新增免鉴权 `/health`（带版本号） | `40acb32` |
| C | 切模型不再把 `models[].api_key` 搬进 `brain.api.api_key` | `8c2acb6` |
| D | 清掉 `logs/` 下带明文密钥的历史备份 + `check_secrets --include-logs` | `c06d8b9` |

---

## 10. 后续路线与发布策略

- **四批推进**：安全（已完成）→ 可维护性 → 质量工程 → 体验。一批做完再开下一批。
- **流程约定**：一次只做一个任务 → 一个 commit → 跑一次全量测试；修改前先备份
  （备份不得含明文密钥，放 `logs/backup_before_*/`，该目录已被 `.gitignore` 忽略）。
- **发布策略**：中间过程不打 tag、不推送、不发 Release；四批全部完成、测试全绿、稳定运行后
  统一打 **v1.0** 正式发布。
- **当前仓库状态**（实测）：工作分支为 `main`；仓库内 tag 只有 `v1.0`；
  另有 `release/stabilize-20260912`、`release/stabilize-20260913` 两个本地分支存在
  （远端也有同名分支）。

---

## 参考

- [architecture.md](architecture.md) —— 架构总览
- [design-philosophy.md](design-philosophy.md) —— 设计哲学 22 节
- [landing-report.md](landing-report.md) —— 落地报告
- [security-audit.md](security-audit.md) —— 安全审计结论
- [testing-report.md](testing-report.md) —— 测试报告
- [tools.md](tools.md) —— 工具脚本说明
- `README.md` —— 对外说明；`CHANGELOG.md` —— 版本记录

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
| 2026-09-13 | v1.0 | 初版：安全第一批成果、踩坑清单、发布策略 |
