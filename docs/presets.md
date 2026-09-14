# Agent 预设切换

| 项目 | 内容 |
|---|---|
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |
| 代码位置 | `xiaojiao_app.py` 的「Agent 预设切换」段，预设文件在 `presets/` |
| 界面入口 | 网页顶部预设下拉，以及设置页的预设编辑区 |

## 摘要

预设是一份 JSON 文件，记录一组人格、大脑与工具开关。选中一个预设即把这组设置合并进
`xiaojiao_control.json` 并热更新内存，不需要重启进程，也不需要改代码。本文给出预设的
字段定义、全部接口、合并规则与新增步骤。

## 1. 背景与问题

小焦的可调项分布在操控文件的多个段落里：人设（`role`）、大脑（`brain`）、工具开关
（`capabilities`）与采样参数（`behavior`）。手工改文件有三个问题：改完要重启或重新加载、
来回切换容易漏项、不同场景的配置无法保存复用。预设把"一套完整设置"变成一个可命名、
可切换、可导出的文件。

## 2. 设计目标

- 一次选择即完成人格、大脑、工具开关与采样参数的切换。
- 生效不依赖重启。
- 未在预设中出现的键保持原值，不被清空。
- 新增预设只需新增一个文件，界面自动列出。

## 3. 预设文件格式

预设是 UTF-8 编码的 JSON 文件，放在 `presets/` 目录下。读取时允许带 BOM。

```json
{
  "name": "编程助手",
  "desc": "简洁专业，工具全开",
  "role": "你是小焦·编程助手。回答要简洁专业，代码一律用代码块，中文注释。给出的命令用绝对路径。",
  "brain": {"engine": "llama", "llama": {"ctx": 20000}},
  "capabilities": {"web_search": true, "memory": true, "run_tools": true, "context_len": 30},
  "behavior": {"temperature": 0.2, "max_tokens": 2048}
}
```

| 字段 | 类型 | 含义 |
|---|---|---|
| name | 字符串 | 预设显示名；接口 `/api/presets/current` 返回的 current 是**文件名**，current_name 才是显示名 |
| desc | 字符串 | 界面上的说明文字；缺省时取 role 的前 70 个字符 |
| role | 字符串 | 人设，写入操控文件的 role |
| brain.engine | 字符串 | 大脑引擎，取值 `auto`、`llama`、`xiaojiao`、`api` |
| brain.llama.ctx | 数字 | 本地大脑的上下文窗口 |
| capabilities.web_search | 布尔 | 联网搜索开关 |
| capabilities.memory | 布尔 | 记忆开关 |
| capabilities.run_tools | 布尔 | 工具与代码执行开关 |
| capabilities.context_len | 数字 | 带入对话的上下文轮数 |
| behavior.temperature | 数字 | 采样温度 |
| behavior.max_tokens | 数字 | 单次回答的输出上限 |
| id | 字符串 | 可选的预设标识，仅随文件保存，不参与合并逻辑 |
| traits | 数组 | 可选的人设标签列表，随文件保存 |
| preinstalled | 布尔 | 可选标记，表示随仓库预置 |

各引擎取值对应的行为：`auto` 在本地大脑在线时用本地、否则用外接接口；`llama` 强制走本地
llama-swap；`xiaojiao` 用自研小脑 MiniGPT 当大脑；`api` 走操控文件里配置的 OpenAI 兼容端点。

仓库内现有预设文件：

| 文件 | 显示名 | 特点 |
|---|---|---|
| `presets/default.json` | 默认·小焦 | 最小配置，只有 `role` 与 `name` |
| `presets/编程助手.json` | 编程助手 | 本地引擎、低温、工具全开、上下文 30 轮 |
| `presets/闲聊陪伴.json` | 闲聊陪伴 | 本地引擎、高温、关联网、关工具、上下文 10 轮 |
| `presets/xiaojiao-default.json` | 小焦 · 默认 | 带 `id`、`traits`、`preinstalled` 的完整人设样板 |

`presets/preset_*.json` 是界面上"新建预设"生成的用户文件，命名取随机十六进制后缀。

## 4. 接口

| 接口 | 方法 | 参数 | 说明 |
|---|---|---|---|
| `/api/presets` | GET | 无 | 列出全部预设，返回 `presets` 数组、`current`（文件名）与 `current_name`（显示名） |
| `/api/presets` | POST | `name`、`parent` | 复制 `parent` 指向的预设（默认 `default.json`）并改名，生成一个新的用户预设文件（文件名形如 preset 加六位随机十六进制） |
| `/api/presets/detail` | GET | `file` | 读取单个预设的完整内容，供界面编辑 |
| `/api/presets/save` | POST | `file`、`data` | 只覆盖 `data` 中给出的键并写回文件；若保存的是当前预设，同时热更新 |
| `/api/presets/load` | POST | `file` 或 `name` | 加载预设：深合并进操控文件、写盘、热更新 |
| `/api/presets/delete` | POST | `file` | 删除预设文件 |
| `/api/presets/current` | GET | 无 | 当前预设名与生效中的引擎、联网、记忆、工具开关 |

`file` 参数不带 `.json` 后缀时自动补齐。

## 5. 合并规则

`POST /api/presets/load` 的执行顺序：

```text
选中预设
  → 读 presets/<file>.json
  → _deep_merge(CONTROL, preset)：递归合并，只覆盖预设提到的键
  → 写入 CONTROL["preset"] = 预设显示名
  → 引擎一致性校正（见下）
  → 写回 xiaojiao_control.json
  → reload_control() 热更新内存中的 SYSTEM_PROMPT / BRAIN / CAP
  → 返回 preset、role 摘要、capabilities、engine、temperature、max_tokens
```

`_deep_merge(base, override)` 的行为是：两边同为字典时递归下去，否则用 `override` 的值覆盖。
因此未在预设里出现的键保持原值，不会被清空。

**引擎一致性校正**：预设只写 `brain.engine` 而不写 `brain.api` 时，深合并会保留原有的云端地址，
出现"引擎声明本地、地址指向云端"的不一致。`api_presets_load()` 因此在合并后检查一次：
当引擎为 `llama` 或 `auto` 且当前 `brain.api.base_url` 不是本地地址时，把地址、密钥与模型名
统一改写为 `http://127.0.0.1:<llama_swap_port>/v1`。

## 6. 使用示例

列出预设并加载其中一个：

```bash
curl http://127.0.0.1:5000/api/presets
curl -X POST http://127.0.0.1:5000/api/presets/load \
  -H "Content-Type: application/json" \
  -d "{\"file\":\"编程助手.json\"}"
```

新建一个预设并写入人设：

```bash
curl -X POST http://127.0.0.1:5000/api/presets \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"我的预设\",\"parent\":\"default.json\"}"

curl -X POST http://127.0.0.1:5000/api/presets/save \
  -H "Content-Type: application/json" \
  -d "{\"file\":\"<新建返回的文件名>\",\"data\":{\"role\":\"你是小焦。\",\"behavior\":{\"temperature\":0.7}}}"
```

## 7. 新增一个预设

1. 在 `presets/` 下新建一个 `.json` 文件，按第 3 节的字段填写。
2. 刷新网页，下拉列表自动出现该预设。
3. 选中即可生效。

也可以复制 `presets/编程助手.json` 后修改，这是最不容易漏字段的做法。

## 8. 边界与限制

1. 加载预设会**写盘**：`api_presets_load()` 把合并后的结果写回 `xiaojiao_control.json`。
   预设不是"临时叠加层"，而是对当前配置的一次真实修改。
2. 深合并只增不减。预设里把某个开关写成 `false` 会生效，但"删掉某个键"无法通过预设表达。
3. `api_presets_save()` 判断"是否为当前预设"用的是 `old.get("name") == CONTROL.get("preset")`
   （显示名比较），而 `api_presets()` 判断当前项用的是文件名。两处判据不同，
   当两个预设文件使用相同显示名时，界面显示与热更新判断可能指向不同文件。
4. 新建预设的接口直接写 `presets/` 目录，不校验目录是否存在；`presets/` 被删除时新建会失败。
5. 预设只作用于当前进程的配置。多进程或多实例运行时，各自的内存配置互不感知。
6. `traits`、`id`、`preinstalled` 三个字段目前只随文件保存与展示，不参与任何运行时逻辑。

## 9. 故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 下拉里选中的预设名不显示 | `current` 回的不是文件名 | 请求 `/api/presets` 看 `current` 与 `current_name` 两个字段 |
| 切换预设后仍走云端 | 预设未写 `brain.api` | 查看 `xiaojiao_control.json` 的 `brain.api.base_url` 与 `brain.engine` 是否一致 |
| 切换后工具消失 | 预设把 `run_tools` 或 `web_search` 写成了 `false` | 请求 `/api/presets/current` 查看当前开关值 |
| 保存预设报格式错误 | 文件含 BOM 或不是合法 JSON | 用 UTF-8 无 BOM 保存；接口读取时允许 BOM，但手写工具可能不识别 |
| 新预设不在列表里 | 文件不在 `presets/` 下，或后缀不是 `.json` | 确认路径与扩展名 |

## 10. 参考

- 人格层如何消解"AI 味"：[modules/09-persona.md](modules/09-persona.md)
- 大脑引擎与模型接入：[brain-switch.md](brain-switch.md)、[coding-brain.md](coding-brain.md)
- 风格人设模板（可作为 `role` 的内容来源）：[xiaojiao-catgirl-style.md](xiaojiao-catgirl-style.md)
- 代码：`xiaojiao_app.py`（`_PRESETS_DIR`、`api_presets*`、`_deep_merge`）

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
| 2026-09-14 | v1.0 | 补全 5 个此前未记录的预设接口；标注"当前预设"在列表与保存在两处判据不同 |
