# 压力测试套件

| 项目 | 内容 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：本文说明 `tests/stress/` 下压力测试套件的组成、运行方式、覆盖范围、CI 门槛与本地实测基线。

## 目录

- [1. 设计约束](#1-设计约束)
- [2. 怎么跑](#2-怎么跑)
- [3. 覆盖范围](#3-覆盖范围)
- [4. 30 分钟极速压力测试](#4-30-分钟极速压力测试)
- [5. CI](#5-ci)
- [6. 本地实测基线](#6-本地实测基线)

## 1. 设计约束

1. **真实调用，禁止模拟**：抓取类用例真的发请求，安全类用例真的走闸门函数。
2. **结果可机读**：全部结果写入 `results.json`，字段为 `total` / `passed` / `failed` / `skipped` / `pass_rate` / `duration_s` / `rows`。
3. **通过率即质量闸门**：`--min-pass-rate` 默认 95，低于门槛退出码为 1，CI 据此判定失败。
4. **通过率只算已执行用例**：`pass_rate = 通过 / (通过 + 失败)`，被跳过的用例不进入分母。
5. **不污染使用者状态**：测试自建会话并在结束（含异常退出）后删除。

## 2. 怎么跑

```powershell
# 全部用例（离线 + 应用逻辑 + 安全 + 联网）——本机实测 155.9 秒
python tests/stress/run_all.py

# 只跑离线部分（离线 + 应用逻辑 + 安全）——本机实测 10.7 秒，不联网
python tests/stress/run_all.py --offline

# 快速模式（跳过并发与熔断自愈等耗时用例）
python tests/stress/run_all.py --quick

# 自定义结果文件与门槛
python tests/stress/run_all.py --json tests/stress/results.json --min-pass-rate 95

# 实机验收（需要小焦正在运行）
python tests/stress/live_check.py

# UI 真渲染检查（需要小焦正在运行 + playwright）
python tests/stress/ui_check.py --out ui_chat.png

# UI 样式检查（需要小焦正在运行 + Chrome/Chromium）
python tests/stress/ui_style_check.py

# Agent 预设真实生效验证（需要小焦正在运行）
python tests/stress/preset_check.py

# 30 分钟极速压力测试（需要小焦正在运行；在自己的终端里跑）
python tests/stress/stability_30m.py --minutes 30
```

退出码：`0` = 通过率达标；`1` = 低于门槛。

也可以用环境变量 `XJ_STRESS_OFFLINE=1` 代替 `--offline`。

## 3. 覆盖范围

### 3.1 四个套件（由 `run_all.py` 顺序编排）

| 文件 | 套件 | 覆盖内容 | 本机用例数 |
| --- | --- | --- | --- |
| `test_units.py` | 离线用例 | 安全闸门（SSRF 矩阵、脱敏）、JSON 展示（美化缩进、Markdown 转义修复、超长折叠、非 JSON 原样）、会话回收（LRU、TTL、非法配置回退、后台巡检线程）、指标（计数与延迟、熔断次数、错误脱敏、Prometheus 文本、落盘）、批量配置（非法配置给中文错误）、渲染契约、超大 JSON、工具集（原生 13 个工具 1:1 全暴露、对外总数 18）、参数校验（空参与非法参给中文错误）、漏洞聚合、兼容入口、日志挂载 | 92 / 92 |
| `test_app_logic.py` | 应用逻辑 | 检索词清洗（寒暄词与功能字拒绝、主题词提取）、漏洞查询意图、提示词铁律与分层、工具注册与热重载、切人设接口、检索质量、思维标签剥离、大脑错误文案（含密钥打码）、云端熔断与本地大脑识别、资产问答与资产插件、公网 IP 直答、别搜闸门、工具选择决策树 | 104 / 104 |
| `test_security.py` | 安全 | SSRF 拦截矩阵（21 个目标）与工具入口探针（5 个）、robots 按 RFC 9309、同域限速计时、日志脱敏（回读日志文件验证）、UA 合规、文件名净化与目录穿越、命令端点源码契约（3 项）、无遥测埋点、已跟踪文件中无明文密钥（274 个文件） | 18 / 18 |
| `test_network.py` | 联网 | 五种抓取方式真实抓取、批量（去重、部分失败隔离、保序、空列表报错）、会话类工具与回收器登记、对抗（重定向型 SSRF、参数注入、页面内容注入、10000 字符 URL、特殊字符、超时纪律、5 并发不串数据、熔断触发与 30 秒自愈）、NVD 漏洞聚合（真实接口） | 35 / 35 |

安全类用例全部离线可跑：被拦截的请求根本不会发出去。需要联网的对抗用例放在 `test_network.py`。

### 3.2 独立脚本

| 文件 | 套件 | 覆盖内容 | 前置条件 |
| --- | --- | --- | --- |
| `run_all.py` | 编排 | 四套件顺序执行 + 通过率门槛 + 退出码 | 无 |
| `harness.py` | 骨架 | 加载被测插件、统一调用封装与超时保护、结果统计与报告 | 无 |
| `live_check.py` | 实机验收 | 对**正在运行**的小焦发真实请求：端点、体检、指标与观测、真实抓取、JSON 展示、SSRF、日志与脱敏、会话删除、时间类提问等 12 组 | 小焦正在运行 |
| `ui_check.py` | UI 渲染 | 用 Playwright 真开浏览器：发消息 → 等回答 → 检查代码块与链接 → 截图 + 控制台错误 | 小焦正在运行 + playwright |
| `ui_style_check.py` | UI 样式 | 真浏览器量计算样式：代码块配色与底色、表格留白、思维标签剥离 | 小焦正在运行 + Chrome |
| `preset_check.py` | 预设生效 | 切预设 → 配置真的变化 → 行为真的跟着变（按搜索来源条数验证）；测试前后逐字节备份与还原控制文件 | 小焦正在运行 |
| `stability_30m.py` | 长稳 | 30 分钟高密度真实压测，覆盖整机端到端与插件直连两层 | 小焦正在运行 |

## 4. 30 分钟极速压力测试

用 30 分钟的高密度真实压力替代长跑方案，覆盖**整机端到端**（默认）与**插件直连**两层。

```powershell
python tests/stress/stability_30m.py                      # 整机 + 插件，30 分钟
python tests/stress/stability_30m.py --target app         # 只压整机（不动插件）
python tests/stress/stability_30m.py --minutes 1 --interval 4 --chat-every 30   # 1 分钟自检
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--target` | `both` | `app` 整机 / `plugin` 插件 / `both` 两者 |
| `--base` | `http://127.0.0.1:5000` | 小焦地址 |
| `--minutes` | `30` | 时长 |
| `--interval` | `10` | 主循环节奏（秒） |
| `--chat-every` | `90` | 整机层每多少秒发一次真实对话 |
| `--mem-abs-mb` | `10` | 内存判定的绝对增量地板 |
| `--out` | `logs/stability_30m.md` | 报告 |
| `--json` | `logs/stability_30m.json` | 机读明细（全部采样点 + 各相位原始数据） |

**内存泄漏判定（两条同时成立才判泄漏）**：

1. 绝对增量 > **10 MB**（`--mem-abs-mb`）。
2. 相对涨幅 > **30%**。

只满足涨幅不满足绝对量的一律按正常波动放行：极低基数（例如 0.19 MB → 0.20 MB）会被百分比放大而误报。
采样每 30 秒一次，对象为本进程堆与工作集，以及小焦进程工作集；判定为泄漏时立即中止并打印原始数据。

**其他自动核对**：HTTP 非 2xx、会话回收、熔断触发与 30 秒自愈、NVD 退避重试、工具异常。

退出码：`0` = 通过，`1` = 失败。

## 5. CI

工作流：`.github/workflows/stress-test.yml`（runner 为 `windows-latest`，超时 30 分钟，环境变量 `PYTHONUTF8=1`）。

**触发条件**

- 每天 03:00（UTC+8）定时。对应 cron 为 `0 19 * * *`（UTC）。
- 手动 `workflow_dispatch`（可勾选快速模式）。
- `push` 且改动命中：`plugins/scrapling_bridge.py`、`xiaojiao_app.py`、`xiaojiao_log.py`、`brain_manager.py`、`tests/stress/**`、`tools/**`、本工作流文件。
- `pull_request` 且改动命中：`plugins/scrapling_bridge.py`、`xiaojiao_app.py`、`xiaojiao_log.py`、`tests/stress/**`、`tools/**`。

**执行步骤**：安装 Python 3.12 → 装抓取栈依赖与 requests → `python -m playwright install chromium`（`continue-on-error`）→
生成最小可用配置 → 依次跑 `tools/check_mermaid.py --all`、`tools/audit_static.py`、`tools/check_docs.py`、
`ruff check --select E9,F63,F7,F82` → 跑压力测试（门槛 95）→ 上传产物 → 写 Job Summary。

**产物与摘要**

- 产物：`tests/stress/results.json` 与 `tests/stress/_metrics.json`，保留 30 天，无论成败都上传。
- 摘要：用例总数、通过、失败、跳过、通过率、耗时写入 GitHub Job Summary。

> 注意：CI 环境没有自备 Chrome，工作流会先安装 Chromium；若安装失败或内核缺失，浏览器类用例会失败并被计入通过率。
> 这是有意设计：通过率不达标时 CI 直接失败，不做兜底放行。

## 6. 本地实测基线

下表数字来自 2026-09-14 本机实测（Windows / Python 3.13.13），命令与输出末尾见括号内说明。

| 项目 | 实测值 | 来源 |
| --- | --- | --- |
| 离线用例 | 92 / 92 | `python tests/stress/run_all.py` 的套件小结「离线用例：通过 92 / 共 92」 |
| 应用逻辑 | 104 / 104 | 同上，「应用逻辑：通过 104 / 共 104」 |
| 安全用例 | 18 / 18 | 同上，「安全用例：通过 18 / 共 18」 |
| 联网用例 | 35 / 35 | 同上，「联网用例：通过 35 / 共 35」 |
| 全量合计 | **249 / 249，通过率 100.00%，耗时 155.9 秒**（失败 0，跳过 0） | `run_all.py` 汇总行 |
| 只跑离线 | 214 / 215，通过率 100.00%，耗时 10.7 秒（跳过 1 = 联网套件整体跳过） | `python tests/stress/run_all.py --offline` |
| 删除红线自测 | 通过 101 / 共 101，退出码 0 | `python tools/test_no_delete.py` |

以下脚本需要小焦正在运行（部分还需要浏览器），**本文未实测**，仅列出运行命令：

| 项目 | 命令 | 状态 |
| --- | --- | --- |
| 实机验收 | `python tests/stress/live_check.py` | 未实测（需小焦正在运行） |
| UI 渲染检查 | `python tests/stress/ui_check.py --out ui_chat.png` | 未实测（需小焦正在运行 + playwright） |
| UI 样式检查 | `python tests/stress/ui_style_check.py` | 未实测（需小焦正在运行 + Chrome） |
| 预设生效验证 | `python tests/stress/preset_check.py` | 未实测（需小焦正在运行） |
| 30 分钟长稳 | `python tests/stress/stability_30m.py --minutes 30` | 未实测（需小焦正在运行） |

## 参考

- 安全审计报告：[../../docs/security-audit.md](../../docs/security-audit.md)
- 抓取能力说明：[../../docs/scrapling.md](../../docs/scrapling.md)
- 发布与回滚：[../../docs/release-and-rollback.md](../../docs/release-and-rollback.md)

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
