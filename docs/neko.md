# N.E.K.O. 猫娘集成

| 项目 | 内容 |
|---|---|
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |
| 代码位置 | `start_xiaojiao.py` 的 `start_neko()` / `ask_start_neko()`、`learn_from_neko.py`、`neko_plugin/xiaojiao_install/` |
| 相关接口 | `/pet`、`/api/env` |

## 摘要

小焦把开源的 N.E.K.O. 猫娘桌面应用作为可选组件集成进一键启动：问一句是否同时拉起，
答是则启动桌面客户端并挂上后台学习通道；答否或非交互环境下跳过，不影响小焦本体。
本文说明集成边界、启动逻辑、记忆目录、插件安装方式与限制。

## 1. 定位

N.E.K.O. 猫娘**不是小焦自带的组件**，而是一个独立的开源项目，由使用者自行下载部署。
小焦做的是集成：按需拉起它、读取它的记忆、给它装一个把小焦介绍给主人的插件。
两者分工是"N.E.K.O. 提供桌面形象与语音界面，小焦提供本地大脑、工具与记忆"，
猫娘负责陪伴这一侧，小焦负责干活这一侧。小焦早期基于 Electron 的桌面宠物已移除
（见 `CHANGELOG.md`），桌面形象统一使用 N.E.K.O. 猫娘。

## 2. 为什么对接 N.E.K.O.

- 它是一个成熟、开箱即用的 Live2D 桌面应用，形象、动效与语音界面齐全。
- 它自带记忆与人格系统（`memory/` 与 `persona.json`），适合承载"记住主人"这件事。
- 它有插件系统，可以安装第三方插件，因此能把小焦的项目信息反向投喂给它。
- 小焦不需要重做一套桌面壳，只需要把两边的服务串起来。

## 3. 启动流程

`python start_xiaojiao.py` 会先启动 llama-swap（9292）与网页服务（5000），
然后在 `ask_start_neko()` 里询问是否同时启动猫娘：

| 输入 | 行为 |
|---|---|
| 直接回车、`y`、`yes`、`是`、`1` | 启动猫娘 |
| `n` 或其他任意输入 | 跳过，小焦照常运行 |
| 非交互环境（无法读取输入） | 跳过，不擅自拉起 |
| 环境变量 `XIAOJIAO_NEKO_AUTO=1` | 免询问，直接启动 |

`start_neko()` 的定位顺序：

1. 环境变量 `XIAOJIAO_NEKO_DIR` 指向的目录。
2. 内置候选列表：`C:\Program Files (x86)\Steam\steamapps\common\n.e.k.o`、
   `C:\Program Files\Steam\steamapps\common\n.e.k.o`、仓库目录下的 `N.E.K.O`、用户主目录下的 `N.E.K.O`，
   以及各盘符下的 `SteamLibrary`、`Steam`、`Games`、`游戏` 目录中的 `steamapps\common\n.e.k.o`。
3. 以上都未命中时，交给 `install_all.discover_neko()` 做全盘探测（按目录名关键词与 `N.E.K.O.exe` 特征）。

找到根目录后按形态拉起：

| 形态 | 判定依据 | 拉起方式 |
|---|---|---|
| Steam 版 | 目录内存在 `N.E.K.O.exe` | 直接启动桌面客户端，由它连带拉起后端 |
| 源码版 | 目录内存在 `launcher.py` 且存在 `.venv\Scripts\python.exe` | 分别启动 `app.memory_server` 与 `app.main_server` |

判定是否已在运行时，代码检查 `N.E.K.O.exe` 进程是否存在，或 48911 端口是否可连。
两种形态都找不到时打印提示并返回，不阻塞小焦启动。

## 4. 端口一览

| 端口 | 服务 | 说明 |
|---|---|---|
| 5000 | 小焦 Web | 聊天、`/v1`、工具、记忆 |
| 9292 | llama-swap | 多大脑热切换 |
| 48911 | N.E.K.O. main_server | 猫娘后端服务；不是网页入口，界面在桌面客户端 |
| 48912 | N.E.K.O. memory_server | 猫娘记忆服务 |
| 48915 | N.E.K.O. agent flags | 原文档记录的端口；本仓库代码中未引用，未能核实，仅供对照 N.E.K.O. 官方说明 |

小焦网页顶栏的猫娘按钮与 `/pet` 路由都会跳转到 `http://127.0.0.1:48911`。
需要再次强调：那只是后端服务端口，主人看到并交互的界面是桌面客户端窗口。

## 5. 记忆目录与学习通道

N.E.K.O. 的记忆目录固定为 `%LOCALAPPDATA%\N.E.K.O\memory\YUI\`，代码取值方式是在
`LOCALAPPDATA` 后拼上 `N.E.K.O\memory\YUI`，没有别名回落，因此只对角色目录为 `YUI` 的
安装生效。目录内被读取的两个文件：

| 文件 | 内容 |
|---|---|
| `facts.json` | 关于主人的事实与偏好；条目含 `text` 与 `entity` 字段 |
| `persona.json` | 猫娘的说话风格设定 |

`learn_from_neko.py` 把这两份内容写进小焦的记忆库 `xiaojiao_knowledge_memory.json`：

| 来源 | 过滤条件 | 写入的键 |
|---|---|---|
| `facts.json` 中文本含"主人"或"碳基生物"，或 `entity` 属于 `master`、`user`、`self` 的条目 | 按上述条件筛选 | `学会:<中文关键词>`，`know` 列表只保留最近 20 条 |
| `persona.json` 的整体内容（截断到 260 个字符） | 无 | `猫娘说话风格` |

运行方式：

```powershell
$env:PYTHONUTF8="1"
python learn_from_neko.py
```

**后台周期学习尚未落地。** `start_xiaojiao.py` 以
`python learn_from_neko.py --daemon --interval 300` 的形式拉起该脚本，但脚本本身没有
参数解析（未使用 `argparse`，`__main__` 直接调用 `learn_once()`）。多余参数会被忽略，
进程执行一次学习后即退出。也就是说，启动时学习一次是当前的实际行为，
"每 5 分钟学一次"属于「设计，未落地」。

## 6. 插件系统与 xiaojiao_install

N.E.K.O. 的插件有两个候选目录，只有其中一个可写：

| 目录 | 类型 | 结果 |
|---|---|---|
| `%LOCALAPPDATA%\N.E.K.O\plugins` | 市场与第三方插件 | 正常加载 |
| `resources\bin\plugin\plugins` | 应用内置（在 app.asar 内） | 只读，放入后加载失败，报"入口点:0" |

小焦提供的插件源码在仓库的 `neko_plugin/xiaojiao_install/`，包含三个文件：

| 文件 | 内容 |
|---|---|
| `plugin.toml` | `id = "xiaojiao_install"`、`name = "装小焦指引"`、`version = "1.0.0"`、`entry = "plugin.plugins.xiaojiao_install:XiaojiaoInstallPlugin"`，以及作者、SDK 版本区间与默认语言 |
| `__init__.py` | `XiaojiaoInstallPlugin`，实现两个 entry |
| `README.md` | 安装位置与使用说明 |

安装方式：把整个 `xiaojiao_install/` 目录复制到 `%LOCALAPPDATA%\N.E.K.O\plugins\`，
重启 N.E.K.O.。

两个 entry：

| entry | 行为 |
|---|---|
| `env_check` | 请求小焦后端的 `/api/env`，把体检项分成已装与缺失两类，并为每个缺失项附上"怎么补"的说明；小焦后端未响应时返回安装步骤作为兜底 |
| `install_guide` | 返回固定的五步安装指引：装依赖、摆好大脑、一键启动、打开使用、环境体检 |

插件读取的小焦后端地址由环境变量 `XIAOJIAO_XIAOJIAO_BASE` 决定，默认值
`http://127.0.0.1:5000`。

## 7. 配置项

| 配置 | 作用 |
|---|---|
| `XIAOJIAO_NEKO_DIR` | 指向 N.E.K.O. 根目录，优先级高于自动探测 |
| `XIAOJIAO_NEKO_AUTO` | 设为 `1` 时跳过询问直接启动猫娘 |
| `XIAOJIAO_XIAOJIAO_BASE` | 插件访问小焦后端的地址，默认 `http://127.0.0.1:5000` |

## 8. 与 `/api/env` 的关系

需要澄清一个常见误解：**`/api/env` 不检测 N.E.K.O.**，它不会去探测 48911 或 48912。
该接口返回的体检项是：Python 版本、llama-server、对话与工具模型是否连通、聊天大脑端口、
ComfyUI、Wan2.1 三件套权重、视频大脑端口、llama-swap（可执行文件与端口）、Node.js、
NVIDIA 显卡与显存。

判断猫娘是否就绪要看两处：`start_neko()` 的启动输出，以及 `install_all.py` 在安装自检时
打印的"N.E.K.O. 猫娘: <路径>"或"未找到 N.E.K.O. 猫娘(可跳过)"。

## 9. 边界与限制

1. 猫娘是可选组件。未安装时，`start_neko()` 只打印一行提示并返回，小焦的其余功能不受影响。
2. 记忆目录写死为 `YUI`，换角色名后学习通道读不到文件，且不会给出明显报错。
3. 周期学习未落地（见第 5 节），长期运行期间不会自动追加新记忆。
4. `facts.json` 的筛选条件包含中文关键词"主人"与"碳基生物"。换用其他语言或改写词时，
   匹配范围会明显变窄。
5. 不同版本的 N.E.K.O. 插件加载目录与 SDK 契约可能变化，`plugin.toml` 声明的是
   `>=0.1.0,<0.2.0` 推荐区间与 `>=0.1.0,<0.3.0` 支持区间；超出该区间时未实测。
6. 小焦只读取猫娘记忆，不写入。让猫娘了解小焦项目靠的是插件与人工投喂。

## 10. 故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 启动时没有询问猫娘 | 处于非交互环境，或已设 `XIAOJIAO_NEKO_AUTO` | 检查启动终端与 `XIAOJIAO_NEKO_AUTO` 的值 |
| 打印"未找到 N.E.K.O. 猫娘" | 路径既不在候选列表，全盘探测也未命中 | 设置 `XIAOJIAO_NEKO_DIR` 指向含 `N.E.K.O.exe` 或 `launcher.py` 的目录 |
| 插件加载报"入口点:0" | 放到了 `resources\bin\plugin\plugins` | 移到 `%LOCALAPPDATA%\N.E.K.O\plugins\` |
| 插件里体检一直失败 | 小焦后端未运行 | 确认 5000 端口可访问，`/api/env` 能返回 JSON |
| 学习装不进新记忆 | 只启动时学了一次，或记忆目录不是 `YUI` | 手工跑一次 `python learn_from_neko.py` 看输出条数 |
| 猫娘界面连不上 | 只启动了后端端口，未启动桌面客户端 | 直接运行 `N.E.K.O.exe` |

## 11. 参考

- 猫娘风格人设模板：[xiaojiao-catgirl-style.md](xiaojiao-catgirl-style.md)
- 依赖体检项明细：[dependency-check.md](dependency-check.md)
- 项目知识库（供人设回答项目问题）：[xiaojiao-kb.md](xiaojiao-kb.md)
- 代码：`start_xiaojiao.py`、`learn_from_neko.py`、`neko_plugin/xiaojiao_install/`

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
| 2026-09-14 | v1.0 | 更正 `/api/env` 不检测 N.E.K.O.；更正插件名为「装小焦指引」及其配置变量为 `XIAOJIAO_XIAOJIAO_BASE`；标注 `--daemon --interval` 未实现、48915 端口未能核实 |
