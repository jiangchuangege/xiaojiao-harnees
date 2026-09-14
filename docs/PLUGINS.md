# 插件开发指南

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：说明小焦的插件机制（如何被扫描、注册、开关、去重）以及怎么写一个插件。当前有哪些工具、每个工具做什么，见 [工具清单](tools.md)；其它扩展方式（改人设、加模型、接外部系统）见 [扩展开发](extend.md)。

## 目录

1. [机制](#1-机制)
2. [写一个 Python 插件](#2-写一个-python-插件)
3. [四种插件类型](#3-四种插件类型)
4. [生效与验证](#4-生效与验证)
5. [契约与边界](#5-契约与边界)
6. [可参考的现有插件](#6-可参考的现有插件)
7. [相关文档](#7-相关文档)

---

## 1. 机制

插件机制由 `xiaojiao_app.py` 的 `load_plugins()` 实现，思路是"往目录丢文件即生效，不为主程序改一行代码"：

1. 启动时扫描项目根目录下的 `plugins/`，按后缀识别插件类型；
2. 每个插件登记为一条记录：插件名（= 文件名去掉后缀）、类型、工具描述列表、开关状态、文件路径；
3. 全部记录汇总进全局 `PLUGINS`；
4. 依据 `xiaojiao_control.json` 的 `capabilities.plugins` 设置每个插件的 `on` 状态；
5. 立即重建系统提示词：`compose_system_prompt()` 会把"当前可用的工具清单"动态拼进去（`_plugin_list()`，最多列 90 条，超出部分标注"另有 N 个工具"）。

因此模型"知道现在有哪些工具"这件事是跟着 `PLUGINS` 走的：重启后新增插件自动出现在清单里，不需要人工改人设。

载体层另有一个能力登记处 `core/carrier/capability.py`（类 `CapabilityRegistry`），用于回答"现在有哪些工具、跟上次比多了少了什么、刚丢进来的文件算不算数"。它优先调用主程序的真实接口（`load_plugins()` + `all_tool_names()`），主程序不可用时退化为扫描目录并按正则粗估工具名。它的定位是**清点与留档**（能力清单会落盘到 `logs/carrier/`，该目录已被 `.gitignore` 忽略），不影响工具的实际执行路由。

### 1.1 工具的路由

内置工具与插件工具统一在 `_build_tools()` 里合并成给模型的功能列表，并建立"工具名 → 插件名"的路由表 `_TOOL2PLUGIN`；执行时由 `run_tool()` 统一进入，插件工具再转到 `run_plugin()`。

### 1.2 重名防呆

不同插件或内置工具使用同一个工具名时，后加载的会覆盖路由表，导致"模型以为调的是 A，实际执行的是 B"。当前的处理是：

- 内置工具名先占位（`check_env`、`run_command`、`read_file` 等 14 个）；
- 插件里与之同名的工具**直接跳过**，并写一条 `工具名冲突，已跳过` 告警日志；
- 插件之间重名同样按先到先得处理。

因此插件作者应保证工具名互不重复，看到该告警就去改名。

### 1.3 外部清单类插件的过滤

`.json` 清单插件里若只声明工具、没写 `url`，该工具实际无法执行（调用只会返回"需对应运行时或填写 url"）。这类工具不会下发给模型，判据由插件自身的 `has_url()` 决定。

## 2. 写一个 Python 插件

Python 插件是一个 `.py` 文件，文件里至少有一个类同时提供两个方法：

| 方法 | 作用 |
| --- | --- |
| `get_tool_descriptions()` | 返回该插件提供的工具列表，每项含 `name` / `description` / `parameters`（JSON Schema） |
| `execute(name, params)` | 按工具名执行，返回字符串 |

一个文件只注册**第一个**同时具备这两个方法的类（找到即停止），但这个类可以一次声明多个工具，在 `execute` 里按 `name` 分发。

### 2.1 最小示例：无参数工具

```python
# plugins/my_time.py
import datetime


class MyTimePlugin:
    """时间助手插件。"""

    def get_tool_descriptions(self):
        return [{
            "name": "get_time",
            "description": "获取当前日期和时间",
            "parameters": {"type": "object", "properties": {}},
        }]

    def execute(self, name, params):
        if name == "get_time":
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return None
```

### 2.2 带参数的工具

```python
# plugins/my_weather.py
import requests


class MyWeatherPlugin:
    def get_tool_descriptions(self):
        return [{
            "name": "get_weather",
            "description": "查询城市天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名，如 北京"}},
                "required": ["city"],
            },
        }]

    def execute(self, name, params):
        if name == "get_weather":
            city = params.get("city", "北京")
            r = requests.get(f"https://wttr.in/{city}?format=%C+%t", timeout=8)
            return f"{city}天气：{r.text.strip()}"
        return None
```

把文件放进 `plugins/` 后重启小焦即可被扫描到。

## 3. 四种插件类型

| 类型 | 识别方式 | 提供什么 | 依赖 |
| --- | --- | --- | --- |
| Python 插件 | 文件名以 `.py` 结尾且不以 `__` 开头 | 类里的 `get_tool_descriptions()` + `execute()` | 无额外依赖 |
| JS 插件 | 文件名以 `.js` 或 `.mjs` 结尾（`plugin_runner.js` 除外） | 导出对象提供 `getToolDescriptions()` 与 `execute(name, params)`，可选 `getSettings()`；执行时由 `plugins/plugin_runner.js` 起 node 子进程 | 需要 Node.js |
| JSON 插件 | 文件名以 `.json` 结尾 | 分三种：`type` 为 `skin` 的是皮肤；带 `tools` 数组的是工具清单（支持 OpenAI / Claude / DSH 三种写法，只有带 `url` 的才可执行）；否则按 API 插件处理，把 HTTP 接口声明成工具 | 无额外依赖 |
| 技能文档 | 文件名以 `.md` 结尾 | 内容拼进系统提示词（人设层），本身不提供可调用工具 | 无额外依赖 |

### 3.1 JS 插件示例

```javascript
// plugins/js-calc.js
module.exports = {
  getToolDescriptions() {
    return [{
      name: "js_calc",
      description: "计算数学表达式，如 (3+4)*2",
      parameters: {
        type: "object",
        properties: { expr: { type: "string", description: "数学表达式" } },
        required: ["expr"],
      },
    }];
  },
  execute(name, params) {
    if (name === "js_calc") {
      const expr = String(params.expr || "");
      if (!/^[\d\s+\-*/().%^]+$/.test(expr)) return "只支持纯数字运算表达式";
      return String(Function('"use strict";return (' + expr.replace(/\^/g, "**") + ')')());
    }
    return null;
  },
};
```

`execute` 允许返回 Promise，运行器会等待它 settle 后再取结果。

### 3.2 API 插件（JSON）示例

```json
{
  "name": "ip",
  "description": "查询本机公网 IP",
  "tools": [
    {
      "name": "get_ip",
      "description": "查本机公网 IP，只返回地址",
      "parameters": {"type": "object", "properties": {}},
      "method": "GET",
      "url": "https://api.ipify.org",
      "response": "text"
    },
    {
      "name": "get_ip_info",
      "description": "查某个 IP 的归属地",
      "parameters": {"type": "object", "properties": {"ip": {"type": "string"}}},
      "method": "GET",
      "url": "https://ipapi.co/{ip}/json",
      "response": "json"
    }
  ]
}
```

执行规则由 `_api_execute()` 实现：

- `{参数名}` 占位符会被入参替换；
- `GET` 把入参作为查询串；`POST` / `PUT` / `PATCH` 把入参（可用 `body_exclude` 排除若干字段）作为 JSON 请求体；
- `response` 为 `json` 时返回解析后的对象（可用 `field` 指定只取某个字段），否则返回文本（截断到 2000 字）；
- 单个工具可单独设置 `headers` 与 `timeout`（默认 30 秒）。

## 4. 生效与验证

1. 把文件放进 `plugins/`；
2. 重启小焦（`python start_xiaojiao.py`）；
3. 查看已注册的插件：

```powershell
python -c "import xiaojiao_app as x; print(list(x.PLUGINS.keys()))"
```

4. 也可以在「设置」页看到插件列表与开关状态（数据来自 `GET /api/settings` 的 `plugins` 字段）。
5. 想默认启用或停用某个插件，在 `xiaojiao_control.json` 里配置：

```json
{
  "capabilities": {
    "plugins": {
      "my_time": true,
      "my_weather": false
    }
  }
}
```

`capabilities.plugins` 必须是**对象**（插件名 → 布尔）。写成布尔值 `true` 会让插件加载阶段抛 `AttributeError`，导致小焦无法启动。

临时停用某个插件：把文件移进 `plugins/_disabled/` 子目录。载体扫描会跳过该目录，主程序也只扫描 `plugins/` 一层，因此其中的文件不会被加载。

## 5. 契约与边界

| 项 | 约定 |
| --- | --- |
| 插件名 | 等于文件名去掉后缀；重名文件会互相覆盖 |
| 工具名 | 不可与其它工具重复，也不要与 14 个内置工具重名（见 [工具清单](tools.md)） |
| 返回值 | 返回 `str` 会原样交给模型与用户；返回 `None` 表示"本次没做事"，模型继续 |
| 异常 | `run_plugin()` 会捕获插件抛出的异常并返回空串（不转成中文报错）。若希望用户看到可读信息，请在 `execute` 内部自行 `try/except` 并返回中文说明 |
| 耗时 | `execute` 是同步调用，长时间阻塞会拖慢对话；耗时任务建议改为后台执行并在后续轮次取结果 |
| 依赖 | 只使用已安装的库（`requests`、`json`、`datetime`、标准库等），不要在插件里临时装包 |
| 加载失败 | 任何插件导入失败都会被静默跳过，只影响该插件本身；排查时先用第 4 节的命令确认它是否出现在 `PLUGINS` 里 |
| 安全 | `execute` 能做的事等于你的代码能做的事。危险动作小焦侧另有删除红线与危险命令确认，但插件自身的网络与文件行为由作者负责 |

## 6. 可参考的现有插件

| 插件 | 提供工具数 | 可借鉴之处 |
| --- | --- | --- |
| `plugins/scrapling_bridge.py` | 18 | 多工具分发、内网地址闸门、会话回收、抓取指标 |
| `plugins/archify.py` | 15 | 把外部工具链封装成"读技能 → 读 schema → 校验 → 交付"的固定工作流 |
| `plugins/code_intelligence.py` | 7 | 大结果截断，避免把整份源码塞进上下文 |
| `plugins/db_helper.py` | 5 | 只读约束（只允许 SELECT）、连接状态保持在插件实例里 |
| `plugins/asset_intel.py` | 3 | 免费源与付费源混用、未配置 Key 时给出可操作的说明、异常一律转中文 |
| `plugins/workspace_search.py` | 3 | 限定工作区范围的文件检索 |
| `plugins/netdoctor.js` | 3 | JS 插件写法：网络诊断类工具 |
| `plugins/ip.json` | 2 | JSON API 插件写法：声明式接入第三方 HTTP 接口 |

`asset_intel` 的数据源接入说明见 [资产测绘插件](asset-intel.md)。

## 7. 相关文档

- [工具清单](tools.md)：内置工具与插件工具的实际清单
- [扩展开发](extend.md)：改人设、加模型、把已有系统包成工具
- [资产测绘插件](asset-intel.md)：一个完整插件的用法说明

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
