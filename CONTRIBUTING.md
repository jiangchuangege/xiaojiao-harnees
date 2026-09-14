# 贡献指南

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：本文说明本仓库的目录结构、本地搭建步骤、提交前必须通过的自检命令、硬性代码约束，以及加插件、换大脑这两类最常见贡献的具体做法。目标只有一条：让改动可以被评审、被 CI 接受、被回滚。

## 目录

1. [仓库结构](#1-仓库结构)
2. [快速上手](#2-快速上手)
3. [分支与提交](#3-分支与提交)
4. [提交前自检](#4-提交前自检)
5. [硬性约束](#5-硬性约束)
6. [加一个插件](#6-加一个插件)
7. [换大脑与换小脑](#7-换大脑与换小脑)
8. [报缺陷与提需求](#8-报缺陷与提需求)
9. [行为准则](#9-行为准则)
10. [免责声明](#10-免责声明)

---

## 1. 仓库结构

| 路径 | 内容 |
| --- | --- |
| `xiaojiao_app.py` | Web 服务与主程序：路由、会话、提示词合成、工具表与工具调用 |
| `start_xiaojiao.py` | 一键启动入口：加载大脑与插件、拉起 Web、按需拉起 N.E.K.O. |
| `xiaojiao_log.py` | 统一日志与脱敏（`get_logger()`、`scrub()`） |
| `xiaojiao_tools.py` | 命令类工具的本机端点 |
| `brain_manager.py` | 大脑的探测、切换与健康检查 |
| `core/` | 骨架层与结构化输出等核心模块 |
| `plugins/` | 插件目录：`.py` 工具插件、`.json` 清单插件 |
| `presets/` | Agent 预设（`.json`） |
| `docs/` | 文档；`docs/modules/` 为模块级说明 |
| `tools/` | 质量闸门与维护脚本（文档校验、静态审计、密钥扫描等） |
| `tests/stress/` | 压力测试与验收脚本，统一入口 `tests/stress/run_all.py` |
| `static/` | 前端静态资源 |
| `video_service/`、`podcast_service/`、`music_service/` | 视频、播客、音乐三个独立服务 |
| `self_learn/`、`neko_plugin/` | 学习沉淀与 N.E.K.O. 对接 |
| `.github/` | CI 工作流与 Issue／PR 模板 |

顶层说明文档：`README.md`（总览）、`ARCHITECTURE.md`（架构）、`CHANGELOG.md`（变更历史）、`LICENSE`。

---

## 2. 快速上手

```powershell
git clone https://github.com/jiangchuangege/xiaojiao-harness.git
cd xiaojiao-harness

python -m pip install -r requirements.txt         # 宽松版本，日常开发用
# 或：python -m pip install -r requirements.lock  # 与验证环境完全一致

python tests/stress/run_all.py --offline          # 先跑离线用例，本机约 11 秒
python start_xiaojiao.py                          # 启动
```

启动后打开 <http://127.0.0.1:5000>。默认只监听本机，不对局域网暴露。

没有云端模型也能运行：在配置里填任意 OpenAI 兼容端点（`brain.api`），或把本地 GGUF 路径填进 `brain.llama.gguf`；小脑的三件套文件放进项目目录后会被自动探测。

启动脚本会尝试拉起本机的 N.E.K.O. 客户端，探测不到就跳过，不阻塞小焦自身的启动。

---

## 3. 分支与提交

| 规则 | 说明 |
| --- | --- |
| 不要直接改 `main` | 使用 `feat/xxx`、`fix/xxx`、`release/stabilize-YYYYMMDD` |
| 一个改动一个 commit | 便于回滚；不要把互不相关的改动塞进同一个提交 |
| commit message 用中文 | 格式：`类型(范围): 做了什么（为什么）`，例如 `fix(scrapling): 下载 404 时不再落盘错误页` |
| 不 force push | 需要修正就追加一个提交，历史可读优先于历史「干净」 |

类型取值建议：`feat` / `fix` / `docs` / `refactor` / `test` / `chore`。

---

## 4. 提交前自检

以下五条与 CI 的五道质量闸门一一对应，先本地跑通可以省下一轮往返。

```powershell
# 语法 + 离线用例（每次都该跑）
python -m py_compile <你改动的文件>
python tests/stress/run_all.py --offline

# 改了抓取插件 → 跑全量（含联网，本机约 100~140 秒）
python tests/stress/run_all.py --json tests/stress/results.json --min-pass-rate 95

# 改了文档或原理图 → 校验 Mermaid 语法
python tools/check_mermaid.py --all

# 改了文档 → 校验链接、路径、接口名、工具名与代码一致
python tools/check_docs.py

# 改动收尾 → 未定义名与语法级缺陷，以及静默吞异常／明文密钥
python -m ruff check --select E9,F63,F7,F82 .
python tools/audit_static.py
```

注意两点：

- `tools/check_mermaid.py` 要加 `--all`。手工传 `docs/*.md` 不会递归到子目录，`docs/` 下子目录里的图会被漏掉。
- 通过率低于 95% 的 PR 会被 CI 挡下，这是有意为之：宁可失败，也不要一个「看起来能用」的改动合入。

---

## 5. 硬性约束

以下条款违反即退稿。

1. **禁止硬编码**：不写死绝对路径、IP、端口、API Key。路径一律走「配置 → 环境变量 → 自动探测」三级。
2. **禁止明文密钥**：密钥只写入 `xiaojiao_control.json`（已被 `.gitignore` 忽略）。日志与报错必须经过 `xiaojiao_log.scrub()`，裸凭据（`sk-` 前缀、`ghp_` 前缀、JWT、AWS Access Key）不得出现在输出中。
3. **错误信息必须中文可读**：不把 Python 堆栈或英文库报错直接抛给使用者。
4. **不许静默吞异常**：`except Exception: pass` 必须改成「记日志 + 明确降级」。批量整改可用 `tools/fix_silent_except.py`；确属故意忽略的，写 `# noqa: silent-ok` 并说明原因（`tools/audit_static.py` 会识别该豁免标记）。
5. **库与插件代码用 logging，不用 print**：交互式脚本（安装向导、启动横幅）除外。
6. **新功能要带测试**：放在 `tests/stress/` 下，并能被 `tests/stress/run_all.py` 收集执行。
7. **安全红线**：SSRF 拦截、robots 合规、同域限速、下载不逃逸目录。不得为了「抓得到」而放宽。
8. **文档与代码同步**：改动配置项、工具数量或命令时，同步更新 `README.md`、`docs/` 下相关文档、`ARCHITECTURE.md` 与 `CHANGELOG.md`；`python tools/check_docs.py` 会核对链接、路径、接口名与工具名。

---

## 6. 加一个插件

插件放在 `plugins/` 下。加载器会扫描模块中第一个同时具备 `get_tool_descriptions()` 与 `execute()` 的类并实例化它；文件末尾的 `get_plugin()` 是主程序插件模板约定的工厂函数，一并保留。

```python
# plugins/my_tool.py
from xiaojiao_log import get_logger

log = get_logger(__name__)


class MyTool:
    def get_tool_descriptions(self):
        return [{
            "name": "my_tool",
            "description": "一句话说明它做什么（≤60 字）。什么时候用：用户要求 XXX 时；输入 text；输出 处理结果",
            "parameters": {"type": "object",
                           "properties": {"text": {"type": "string", "description": "text: 输入"}},
                           "required": ["text"]},
        }]

    def execute(self, tool_name, params):
        if tool_name != "my_tool":
            return "未知工具：%s" % tool_name
        text = str((params or {}).get("text") or "").strip()
        try:
            return "处理完成：%s" % text
        except Exception as e:
            log.warning("my_tool 失败: %s", e)
            return "处理失败：%s" % str(e)[:120]


def get_plugin():
    return MyTool()
```

要点：

- **`execute()` 必须返回字符串**。主程序会把非字符串返回值统一归一化为字符串，但历史的非字符串返回曾导致下游切片与解包崩溃，插件侧不要依赖这层兜底。
- `execute()` 内部自己接住异常，返回中文可读说明，不要把异常抛给调用方。
- **描述要写「什么时候用」并且写短**。参数数量少的本地模型靠这句话选工具；应用逻辑套件会自动检查工具描述是否包含「什么时候用」，缺了会被判失败。
- 描述长度以 60 字左右为宜，该约定来自主程序内置的插件模板提示词。
- 需要被 `/metrics` 采集，额外实现 `metrics_prometheus()` 即可。
- 插件在启动时加载，改完需重启小焦生效。

---

## 7. 换大脑与换小脑

- **大脑（对话模型）**：编辑 `xiaojiao_control.json` 的 `brain.api`，填入任意 OpenAI 兼容端点与模型名；或填 `brain.llama.gguf` 指向本地 GGUF 文件。两种情况都不需要改代码。
- **小脑（MiniGPT）**：需要三件套文件——权重 `*.pth`、词表 `vocab*.pkl`、结构 `model_config.json`。把路径填进 `brain.xiaojiao`；留空时按关键词与文件体积自动探测。

---

## 8. 报缺陷与提需求

提交前请先自查日志中是否含密钥：日志文件位于 logs/xiaojiao.log。

请附上：现象、复现步骤、期望结果、实际结果、日志片段。

- [缺陷 Issue 模板](.github/ISSUE_TEMPLATE/bug_report.yml)
- [需求 Issue 模板](.github/ISSUE_TEMPLATE/feature_request.yml)
- [Pull Request 模板](.github/PULL_REQUEST_TEMPLATE.md)

---

## 9. 行为准则

参与本项目即表示同意 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。提问不存在「太基础」这一说。

---

## 10. 免责声明

本项目为个人本地 AI 助手框架。抓取能力仅用于公开可访问内容；请遵守目标站点条款与当地法律，不得用于绕过付费墙、破解版权或任何违法用途，后果由使用者自负。

---

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
