# 小焦 · 项目全景（Project Overview）

> 分支：`release/stabilize-20260913`（本地，**未推送**）｜ 安全第一批已全部完成
> 本文是**新会话的入口文档**：先读它，再动手。数字取自真实执行，不是估计。

---

## 1. 这是什么

小焦（XiaoJiao）是一个**本地部署的联网搜索 AI 助手**：一个 Flask Web 应用 + 自研小脑
（MiniGPT 蒸馏模型）+ 可选云端大脑（OpenAI 兼容）+ 一套工具/插件（网页抓取、漏洞情报、
画图、资产测绘、视频、播客、音乐…）。

一句话调用链：

```
用户 / DSH / 客户端
   → 小焦 Web（Flask，xiaojiao_app.py）
   → agent_run（选大脑 + 工具循环）
   → 大脑（本地 llama-swap:9292 / 云端 API）
   → 工具（内置 + plugins/*）
```

---

## 2. 架构约定（改代码前必须知道）

1. **提示词分层是硬约定**：`系统提示词 = role（纯人设） + 检索铁律 + 工具铁律 + 插件清单`。
   `role` 只许放人设；规则与清单由代码独立拼接（`compose_system_prompt()` 是**唯一**合成入口）。
   原因：规则一旦写进 `role`，就会出现"改人设丢规则、加插件要手改人设、role 越写越长"。
2. **控制文件是唯一配置源**：`xiaojiao_control.json`（**不入库**，`.gitignore` 忽略）。
   模板是 `xiaojiao_control.json.example`。改完文件后 `maybe_reload_control()` 会自动热重载。
3. **插件契约**：`plugins/*.py` 实现 `get_tool_descriptions()` + `execute()`；工具名全局唯一，
   描述必须写清"什么时候用"（有测试在查）。插件的异常**绝不**抛给调用方，要给中文提示。
4. **两条启动路径必须共用同一套规则**：`xiaojiao_app.py` 的 `main()` 与一键启动器
   `start_xiaojiao.py`。历史上它们各写各的（启动器写死 `0.0.0.0`），直接把安全防护绕过去了 ——
   所以监听地址这类决策抽成了 `bind_host()`，**两边都调它**，不要再复制一份。
5. **一个任务一个 commit**：中文 message，改前先备份，中间过程不打 tag、不推送。
6. **不许扩散**：改 A 模块不要顺手动前端 HTML / 视频 / 播客 / 音乐 / Scrapling。

---

## 3. 关键文件清单

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `xiaojiao_app.py` | ~5606 | **主程序**：配置加载、大脑调用、工具循环、全部 HTTP 路由（64 条）、内嵌前端 HTML |
| `start_xiaojiao.py` | ~287 | 一键启动器：拉大脑 + Web + N.E.K.O. 猫娘（**监听地址必须走 `bind_host()`**） |
| `xiaojiao_control.json` | — | **实际配置**（不入库）：brain / role / capabilities / behavior / models / dsh |
| `xiaojiao_control.json.example` | — | 配置模板（入库），含各字段中文注释 |
| `plugins/*.py` | — | 11 个插件；`plugins/scrapling_bridge.py`（~3031 行）是抓取主力，对外 18 个工具 |
| `plugins/asset_intel.py` | — | 资产测绘（查 IP / 反查 / 状态），免费那半不用 Key |
| `tools/check_principles.py` | ~206 | 12 条项目铁律的机器化审计（P1~P12） |
| `tools/check_docs.py` | ~241 | 文档↔代码一致性（链接/路径/端点/工具名） |
| `tools/check_secrets.py` | ~201 | 明文密钥自查（`--include-logs` 连 logs/ 备份一起扫） |
| `tools/dangerous_commands.txt` | — | 危险命令黑名单（一行一个正则，改词不用动代码） |
| `tools/audit_static.py` | — | 静态审计（check_principles 会调用） |
| `tests/stress/run_all.py` | ~68 | **全量测试总入口**（4 个套件） |
| `tests/stress/test_units.py` | — | 离线用例 92 条 |
| `tests/stress/test_app_logic.py` | — | 应用逻辑用例 104 条 |
| `tests/stress/test_security.py` | — | 安全用例 18 条（SSRF/robots/脱敏/穿越/无明文密钥…） |
| `tests/stress/test_network.py` | — | 联网用例 35 条（真抓取/NVD 真实接口） |
| `README.md` / `CHANGELOG.md` | ~1314 / — | 对外说明 / 版本记录（版本号以 CHANGELOG 为准） |
| `docs/*.md` | 33 个 | 分主题文档（架构、安全审计、抓取、大脑切换、测试报告…） |

> 另有 `tests/stress/live_check.py`、`tests/stress/preset_check.py`、`tests/stress/stability_30m.py`、
> `tests/stress/ui_check.py` 等**独立实机脚本**，`tests/stress/run_all.py` 不跑它们
> （需要服务在跑 / 会连打 `/api/chat`）。

---

## 4. 启动与配置

```powershell
python xiaojiao_app.py                 # 直接跑 Web（默认 http://127.0.0.1:5000）
python start_xiaojiao.py               # 一键：大脑 + Web + N.E.K.O. 猫娘
python tests/stress/run_all.py         # 全量测试
```

**密钥**：优先读环境变量 `XIAOJIAO_API_KEY`，其次控制文件 `brain.api.api_key`。推荐只在环境变量里放：

```powershell
setx XIAOJIAO_API_KEY "sk-你的密钥"     # 永久（需重开终端）
$env:XIAOJIAO_API_KEY="sk-..."          # 只当前窗口
python tools/check_secrets.py           # 查还有没有明文残留
```

---

## 5. 安全模型（安全第一批成果）

| 机制 | 位置 | 说明 |
| --- | --- | --- |
| 只听本机 | `bind_host()` | 默认 127.0.0.1；只有 `lan_access=true` **且** `access_token` 非空才听 0.0.0.0 |
| 访问令牌 | `_require_token()` | 非本机请求必须带 `X-Auth-Token` 或 `?token=`；`/health` 与 `/favicon.ico` 免鉴权 |
| 危险命令确认 | `is_dangerous()` + `PENDING` | **只对危险命令**要确认（安全命令直接跑）；`full_access=true` 则完全不问 |
| 密钥不落文件 | `_resolve_llm_key()` | 环境变量优先；切模型也不把 `models[].api_key` 搬回 `brain.api.api_key` |
| 聊天限流 | `rate_limited()` | 令牌桶，默认 30/分钟、突发 5，`capabilities.rate_limit_per_minute` 可调 |
| 抓取防护 | `scrapling_bridge` | SSRF 100% 拦截、robots.txt、同域限速、熔断、日志脱敏 |
| 探活 | `GET /health` | 免鉴权，返回 `{"ok": true, "version": "1.0"}` |

控制文件里的开关（`capabilities`）：`lan_access` / `access_token` / `full_access` /
`rate_limit_per_minute` / `run_tools` / `context_len`。

---

## 6. 测试与质量闸门（当前基线）

```powershell
python tests/stress/run_all.py      # 全量 249/249 · 100%
python tools/check_principles.py    # 原理 12/12
python tools/check_docs.py          # 文档 0 错误（3 条既有警告）
ruff check --select E9,F63,F7,F82 . # 全过
```

- **全量 = 249 条**：离线 92 ｜ 应用逻辑 104 ｜ 安全 18 ｜ 联网 35，失败 0、跳过 0。
- 退出码：达标 `0`，低于门槛 `1`。**注意**：在 PowerShell 里带 `2>&1` 跑，
  宿主可能把 stderr 记成错误、`$LASTEXITCODE` 显示 1 —— 那不是用例失败，看脚本自己的汇总行。
- 文档闸门会把文档里"反引号包起来的仓库路径"逐个核对是否存在，**写文档别写不存在的路径**。

---

## 7. 踩坑清单（都是真实踩过的，别重复）

1. **往函数里插注释行 → IndentationError**。`reload_control()` 那种函数体内插注释必须保持同级缩进；
   改完**立刻** `python -c "import ast,io; ast.parse(...)"`，再看 ruff。
2. **正在运行的小焦实例会重写整个控制文件**：`/api/persona`、`/api/access`、`_save_control()`
   都会按**内存里的状态**把 `xiaojiao_control.json` 整份重写。后果：你手改的值会被"改回去"
   （实测把测试用的 `rate_limit_per_minute: 2` 又写回文件）。**改配置前先停实例，改完复查**。
3. **PowerShell 会把命令行参数里的双引号吃掉**：`python x.py '  "k": false,'` 传过去变成 `k: false`，
   直接写出非法 JSON。要改 JSON 就用**脚本文件读取替换文本**，别用命令行参数传带引号的串。
4. **令牌桶必须加锁**：Flask 是多线程的，"读-改-写"不加锁时并发请求会各自看到还有令牌，
   突发放过去（实测并发打 5 次本该只过 2 次）。
5. **前端 `fetch('/api/chat')` 不检查 `r.ok`**：它直接读 `d.answer`，还会调 `setToolsOn(d.tools_on)`。
   所以错误响应（如 429）也要带上 `answer` / `tools_on`，否则界面是空白气泡 + 工具开关被误判成"关"。
6. **测限流必须并发打**：单次回答要十几秒，串行打的话令牌桶早就回填了 —— 第一次串行实测 5 次全是 200。
7. **两条启动路径各写各的 = 防护被绕过**：任务 1 只改了 `main()`，启动器里的 `host="0.0.0.0"`
   照样把服务暴露到同网段。凡"启动期决策"都要抽成共用函数。
8. **静态检查查不出"返回值类型变了"**：曾差点把 `return "字符串"` 插进返回**列表**的
   `_llm_targets()`（ast/ruff 都不会报）。改完对关键函数做一次针对性自检。
9. **`typing` 在主程序里其实没导入**：`xiaojiao_app.py` 里出现的 `from typing import ...` 是
   **插件示例模板字符串**（约 2930 行），不是真代码。别在模块前部写 `Dict[str, Any]` 这类注解，会 NameError。
10. **代码自带的扫描器别只扫根目录**：`check_secrets` 起初没扫 `logs/`，默认扫描报"干净"，
    而备份里还躺着 4 个文件 8 处明文 —— 假阴性比不报还危险，已补 `--include-logs`。

---

## 8. 待办清单（Backlog）

| # | 事项 | 位置 | 状态 |
| --- | --- | --- | --- |
| 3.5 | 界面切模型会把 `models[i].api_key` 写回 `brain.api.api_key`，等于把明文密钥又写回控制文件 | `/api/model/select` | ✅ **已解决**（安全第一批·任务C） |

### 3.5 详情：明文密钥会被写回控制文件 —— ✅ 已解决

**现象**：控制文件 `xiaojiao_control.json` 的 `models` 数组里，每个模型各自带一份 `api_key`。
在设置页切换模型时，程序把选中模型的那份 `api_key` 直接搬进 `brain.api.api_key`，
于是任务 3 刚清空的明文密钥又被写回文件了。

**影响**：任务 3 的「环境变量优先」只覆盖 `brain.api.api_key` 这一处**读取**；
只要用户在界面上切一次云模型，明文就会重新落进文件 —— `models[1].api_key`
与 `brain.api.api_key` 本来就是同一个 key。

**实际修法（任务C 落地）**：
1. `/api/model/select` 里不再搬 `m.get("api_key")` 进 `brain.api.api_key`，只切 `model` 名，
   `brain["api"]["api_key"]` 一律写 `""`；密钥统一由 `_resolve_llm_key()` 从环境变量
   `XIAOJIAO_API_KEY` 读。
2. 云端探测改用**解析后的** key（`_cloud_key_problem(base, _resolve_llm_key(brain), model)`），
   否则会用空 Key 去撞 401、再把结论带偏。
3. `_cloud_key_problem()` 增加"压根没 Key"分支：直接提示去设环境变量。
4. 清空控制文件里 `models[*].api_key` 的历史明文。

**验收（已实测通过）**：
- 真实走 `/api/model/select` 来回切（agnes ↔ 本地）3 次：每次切完 `brain/api/api_key` 长度都是 0，
  `LLM_KEY` 始终等于环境变量，磁盘上所有 `api_key` 也都是空。
- 对照证明：**内存里**给 `models[1].api_key` 塞一把假明文再切一次，捕获到的 `brain["api"]`
  仍是 `{"api_key": ""}` —— "搬明文"的路径确实断了。

### 其它已知、暂未处理

- `tests/stress/live_check.py` 等实机脚本**不在** `tests/stress/run_all.py` 里，改动主程序后建议单独跑一次。
- `docs/architecture.md` 里提到的 status / distill 两个接口不在本仓库路由表里（check_docs 会给出警告），
  像是对外部服务的描述，尚未核实。

---

## 9. 安全第一批任务流水（已完成）

| 任务 | 内容 | commit |
| --- | --- | --- |
| 1 | Web 默认只听 127.0.0.1 + 访问令牌鉴权 | `04298a5` |
| 2 | 危险命令黑名单独立文件 + 只对危险命令要确认 | `8265ece` |
| 3 | 密钥优先读环境变量 + `tools/check_secrets.py` | `0121627` |
| 4 | 聊天接口令牌桶限流（30/分钟，突发 5，可配置） | `c0f40cd` |
| A | 启动器不再写死 `0.0.0.0`（补任务 1 的漏） | `b6d93a1` |
| B | 新增免鉴权 `/health`（带版本号） | `40acb32` |
| C | 切模型不再把 `models[].api_key` 搬进 `brain.api.api_key`（原 3.5） | `8c2acb6` |
| D | 清掉 `logs/` 下带明文密钥的历史备份 + `check_secrets --include-logs` | `c06d8b9` |

---

## 10. 后续路线与发布策略

- **四批推进**：安全（本批）→ 可维护性 → 质量工程 → 体验。**一批做完再开下一批**。
- **流程约定**：一次只做一个任务 → 一个 commit → 跑一次全量测试；修改前先备份
  （备份**不得含明文密钥**，放 `logs/backup_before_*/`，该目录已被 `.gitignore` 忽略）。
- **发布策略**：中间过程**不打 tag、不推送、不发 Release**；四批全部完成、测试全绿、
  稳定运行后，才统一打 **v1.0** 正式发布。当前 tags 只有旧的 `v1.0`（本轮未动）。
- **状态**：本地分支 `release/stabilize-20260913` 领先 `origin/main` 若干 commit，**未推送**。

---

## 📎 相关记录

- 改动细节与测试数据见各次 commit message（中文，写得较全）与 `CHANGELOG.md`。
- 密钥迁移方法见 `README.md` 的「🔑 密钥用环境变量（推荐）」一节。
- 安全审计结论见 `docs/security-audit.md`。
