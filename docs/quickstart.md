# 快速开始

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：从已有的仓库目录出发，用三步把小焦跑起来并完成第一次对话。前置条件（Python 版本、依赖、模型来源）见 [安装](install.md)；本文只讲"怎么跑起来、跑起来之后怎么用"。

## 目录

1. [三步启动](#1-三步启动)
2. [第一次使用](#2-第一次使用)
3. [常用命令行](#3-常用命令行)
4. [接入其它客户端](#4-接入其它客户端)
5. [下一步](#5-下一步)

---

## 1. 三步启动

### 1.1 装依赖

在项目目录下执行：

```powershell
python -m pip install -r requirements.txt
```

### 1.2 指定大脑

小焦需要一个"大脑"：本地 GGUF 模型，或任意 OpenAI 兼容接口。二选一：

| 方式 | 配置位置 | 说明 |
| --- | --- | --- |
| 本地 GGUF | `xiaojiao_control.json` → `brain.llama.gguf` | 已有 GGUF 就填它的路径；没有可从 Hugging Face 下载 Qwen 系 GGUF。留空时启动器会在 `C:/llama`、项目目录、用户目录、`Downloads` 里自动找 |
| 云端接口 | `xiaojiao_control.json` → `brain.api` | 填 `base_url` / `api_key` / `model`，并把 `brain.engine` 设为 `api` |

`brain.engine` 保持 `auto`（或 `llama`）。不要选 `xiaojiao`，那表示只用自研小脑（MiniGPT），能力明显弱于大模型，默认不启用。

### 1.3 启动

```powershell
python start_xiaojiao.py
```

启动器依次完成：

1. 拉起 llama-swap 多大脑管理器（默认 9292）；
2. 若 `brain.engine` 为 `auto` 或 `llama`，用自动探测到的 `llama-server.exe` + GGUF 拉起本地大脑；
3. 确定 Web 端口（`--port` 参数 > 控制文件 `web_port` > 环境变量 `PORT` > 默认 5000）；
4. 询问是否同时启动 N.E.K.O. 桌面端（可选）；
5. 打开浏览器指向 `http://127.0.0.1:<端口>`。

启动日志出现 `大脑 … 已就绪 (port …)` 表示本地大脑已就绪。若提示"没找到大模型文件/服务，跳过自动启动"，说明走了 `brain.api` 或小脑兜底路径，对话仍可用，但质量取决于所配接口。

## 2. 第一次使用

| 想做的事 | 操作 |
| --- | --- |
| 聊天 | 直接在底部输入框提问 |
| 让它动手做事 | 确认界面上方的「工具」开关为开（`开` / `关` 状态由 `/api/tools_toggle` 读写），再说清目标，例如"在桌面建一个 xxx 文件夹并写一个 a.html" |
| 切换大脑 | 顶部模型下拉框；或「设置」→ 模型管理 → 添加 |
| 新建会话 | 左侧「＋ 新对话」 |
| 查看成本 | 浏览器打开 `http://127.0.0.1:5000/cost` |
| 看屏幕内容 | 设 `XIAOJIAO_VISION_URL`（与可选 `XIAOJIAO_VISION_MODEL`）指向视觉模型接口，再走截屏识图 |

N.E.K.O. 桌面端属于可选组件：启动时命令行会先问一句是否同时启动，回答 `y` 才拉起（后端端口 48911/48912），回答 `n` 或非交互环境下不拉起，也不影响小焦本体。自动化场景可设 `XIAOJIAO_NEKO_AUTO=1` 免询问直接拉起。

## 3. 常用命令行

```powershell
python start_xiaojiao.py --port 8081      # 换 Web 端口；也可改控制文件的 web_port
python install_all.py                     # 完整安装/检测向导
python install_auto.py                    # 精简安装器：装依赖 → 检查模型 → 启动
```

`install_all.py` 的检测分级与可选组件清单见 [安装](install.md) 第 3 节。

## 4. 接入其它客户端

小焦的 `/v1` 是 OpenAI 兼容接口。把任意客户端（dsh、open-webui、自写脚本）的模型地址填成：

```text
http://127.0.0.1:5000/v1
```

即可用上小焦的人设、工具与记忆。接口明细见 [HTTP API](api.md)。

## 5. 下一步

- [安装](install.md)：一键安装的检测分级、迁移换机、常见安装问题
- [常见问题](faq.md)：工具不执行、会话持久化、云端 Key 报错排查
- [插件开发指南](PLUGINS.md)：往 `plugins/` 丢一个文件就多一个工具
- [工具清单](tools.md)：当前实际有哪些工具、需要哪些运行时组件

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
