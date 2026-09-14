# 音乐生成插件（MusicGen）

| 项目 | 内容 |
|---|---|
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |
| 代码位置 | `plugins/music_generation.py`（插件）；`music_service/ace_music.py`（另一条音乐链路，见 7.4 节） |
| 入口 | 对话工具 `generate_music`，无独立 HTTP 接口 |

## 摘要

本文说明小焦如何把一句文字描述变成一段本地生成的音频。实现方式是 `plugins/music_generation.py`
把 Meta 的 MusicGen（`facebook/musicgen-small`）注册成一个对话工具，模型在判断用户要音乐时调用它，
产物写入 `media/music/`，再由前端渲染成音频播放器。

## 1. 背景与问题

小焦的其余生成能力（视频、播客配音、播客封面）都各自占用显卡。若音乐模型与它们同时驻留，
显存会被占满。因此音乐能力有两条硬约束：一是必须能由对话直接触发，不需要用户记命令；
二是生成前必须先把占显存的大模型让出去。

## 2. 设计目标

- 能力以插件形式提供，放入 `plugins/` 即注册，不改主程序。
- 模型本地运行，默认不依赖任何云端服务。
- 首次使用时自动补齐依赖与权重，不需要用户手工准备环境。
- 生成前释放显存，避免与聊天大脑、视频模型互相争抢。

## 3. 接口与实现

### 3.1 工具定义

| 项 | 值 |
|---|---|
| 工具名 | `generate_music` |
| 参数 `prompt` | 音乐描述，中文或英文均可，必填；代码内截断到 120 字符 |
| 参数 `duration` | 时长秒数，默认 5，取值被钳制在 1 至 20 |
| 返回值 | 字符串；成功时包含 `[music]media/music/<时间戳>.wav[/music]` 标记 |
| 默认开关 | 开启。`capabilities.plugins` 里没有该插件名时按开处理 |

### 3.2 代码位置与函数

| 位置 | 名称 | 作用 |
|---|---|---|
| `plugins/music_generation.py` | `MusicGeneration.get_tool_descriptions()` | 向模型声明 `generate_music` 工具 |
| `plugins/music_generation.py` | `MusicGeneration.execute(tool_name, params)` | 参数校验、释放显存、加载模型、生成 wav |
| `plugins/music_generation.py` | `_free_vram()` | 卸载 llama 大脑并清空 `brain_manager` 注册表里的大脑 |
| `plugins/music_generation.py` | `get_plugin()` | 插件入口，返回 `MusicGeneration()` |

`_free_vram()` 做两件事：调用 `video_service.model_switch._llama_swap_unload()` 卸载 `xiaojiao`
与 `coder` 两个模型；再遍历 `brain_manager.BRAINS`，对每一项调用 `_full_stop()`。

### 3.3 生成流程

```text
对话触发
  → _free_vram()：卸载 llama 大脑，清空大脑注册表
  → 首次运行时 pip install audiocraft
  → MusicGen.get_pretrained("facebook/musicgen-small")
  → model.generate([prompt])，时长由 duration 决定
  → 写入 media/music/<YYYYmmdd_HHMMSS>.wav
  → 返回 [music]media/music/<文件>.wav[/music]
  → 前端匹配该标记并插入 audio 播放器
```

前端渲染逻辑在 `xiaojiao_app.py` 的界面脚本中：出现 `[music]` 标记时取出其中的路径，
生成 `<audio src="..." controls>` 元素，并把标记本身从正文里去掉。

## 4. 使用示例

对小焦说：

```text
用 generate_music 生成一段 5 秒的轻快钢琴曲
```

模型据此调用：

```json
{"name": "generate_music", "arguments": {"prompt": "轻快的钢琴曲", "duration": 5}}
```

返回内容形如：

```text
音乐生成完成：
[music]media/music/20260914_101530.wav[/music]
轻快的钢琴曲（5秒）
```

## 5. 依赖与首次运行

| 依赖 | 安装方式 | 说明 |
|---|---|---|
| `audiocraft` | 首次调用时自动 `python -m pip install audiocraft -q`，超时上限 600 秒 | 也可手工预装 |
| MusicGen 权重 | 首次调用时自动下载 | `facebook/musicgen-small`，占用空间约 1.5 GB，由 `get_pretrained` 完成 |
| `torch` | 随项目依赖安装 | 有 GPU 时用 `cuda`，否则回落到 `cpu` |

首次调用明显慢于后续调用，因为要装依赖并下载权重。后续调用只加载模型。

## 6. 边界与限制

1. 无独立 HTTP 接口。音乐能力只通过对话工具暴露，仓库内没有 /api/music 一类的路由。
2. 时长上限 20 秒，且 `duration` 小于 1 时被抬到 1。
3. 生成结束后**不自动恢复**聊天大脑。`execute()` 里只有卸载，没有对应的加载调用；
   下一次聊天、视频或其他大脑请求会由 llama-swap 与各服务按需重新加载。
4. 释放显存的范围比"腾出音乐所需的空间"更大：`_free_vram()` 会清空
   `brain_manager.BRAINS` 里的全部大脑，而不只是聊天大脑。
5. `audiocraft` 的安装命令不带版本约束，`-q` 只压输出，不保证可复现的版本组合。
6. 生成失败时返回以"音乐生成失败："开头的字符串，插件不抛异常，主流程不会中断。
7. 未实测项：MusicGen 在消费级单卡上的单次生成耗时、`audiocraft` 与当前
   Python 版本的兼容边界，本文档不给出具体数字。

### 6.1 关于 `music_service/ace_music.py`

仓库里还有一套 ACE-Step 音乐链路：`music_service/ace_music.py` 通过外部的
ACE-Step FastAPI 服务（默认 `http://127.0.0.1:8001`）生成音乐，支持歌词与更长时长，
由环境变量 `XIAOJIAO_ACESTEP_URL`、`XIAOJIAO_ACESTEP_KEY` 配置。

**该模块目前是库，未接入主流程**：仓库内没有任何位置 `import` 它，也没有路由或工具调用它。
`install_all.py` 只在安装自检时判断 `music_service/` 目录是否非空。因此上述内容属
「设计，未落地」——只有 MusicGen 插件这条链路是当前可用的音乐能力。

## 7. 故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 回复"音乐生成失败" | `audiocraft` 未装成功，或权重下载中断 | 看返回字符串尾部的异常文本；手工执行 `python -m pip install audiocraft` 复现 |
| 首次调用长时间无响应 | 正在下载 `musicgen-small` 权重 | 观察 `media/music/` 是否出现新文件；权重下载没有进度回溯 |
| 音频不显示播放器 | 前端没有匹配到 `[music]...[/music]` 标记 | 确认返回文本里标记完整、路径以 `media/music/` 开头 |
| 生成后聊天变慢 | 聊天大脑已被 `_free_vram()` 卸载 | 正常现象；下一次请求会触发 llama-swap 重新加载 |
| 工具不出现在模型可调用清单里 | 插件未加载或被关闭 | 在设置页的插件列表确认 `music_generation` 为开启；重启小焦 |

## 8. 参考

- 插件开发约定：[PLUGINS.md](PLUGINS.md)
- 大脑调度与显存让位：[brain-switch.md](brain-switch.md)、[coding-brain.md](coding-brain.md)
- 播客（同样用到本地语音与出图模型）：[podcast.md](podcast.md)
- 代码：`plugins/music_generation.py`、`music_service/ace_music.py`

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
| 2026-09-14 | v1.0 | 更正"生成完恢复大脑"的说法（代码无恢复步骤）；补充 ACE-Step 链路未落地的事实 |
