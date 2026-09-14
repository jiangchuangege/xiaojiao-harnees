# 编码大脑与显存调度（双模型热切换）

| 项目 | 内容 |
|---|---|
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |
| 代码位置 | `brain_manager.py`（大脑注册表与调度）、`llama-swap.yaml`（模型路由）、`video_service/model_switch.py`（显存协调） |
| 相关接口 | `/api/model/addlocal`、`/monitor`、`/api/monitor`、`/api/monitor/op` |

## 摘要

本文说明小焦如何在一张消费级显卡上同时提供聊天、编码、视频与音乐能力：把每个模型注册成一颗
"大脑"，由 `llama-swap` 与显存协调器负责卸载与加载，使任一时刻只有一颗大脑占用显存。
本文重点在编码大脑（Qwen3-8B）与聊天大脑（Qwen 4B）之间的切换。

## 1. 背景与问题

编码任务需要更大的模型，日常聊天不需要。两个模型同时驻留会超出单卡显存，表现为显存溢出
（OOM）或推理速度骤降。直接按需"杀进程再重启"会让每次切换都要重新加载权重，体验上是分钟级等待。

小焦采用的方案是让模型进程常驻，切换时只搬运权重：把不用的模型从显存卸到内存，
把要用的模型从内存装回显存。

## 2. 设计目标

- 任一时刻最多一颗大脑占用显存。
- 最近用过的一颗大脑留在内存，切回时不重新读盘。
- 切换不重启小焦主进程，会话与记忆不丢。
- 新增大脑不需要改调度代码，只改配置与注册表。

## 3. 大脑清单

| 大脑 | 模型 | 服务与端口 | 用途 |
|---|---|---|---|
| 聊天大脑 | `xiaojiao1.0-4B`（Qwen 4B），llama-swap 路由键 `xiaojiao` | llama-swap，端口 9292 | 日常对话 |
| 编码大脑 | `Qwen3-8B-Q4_K_M`，llama-swap 路由键 `coder`，`useModelName` 为 `qwen3-8b` | llama-swap，端口 9292 | 写代码、调工具 |
| 视频大脑 | Wan2.1 加 ComfyUI | ComfyUI，端口 8188 | 文生视频 |
| 播客大脑 | 写稿、配音与封面（Chatterbox TTS 加 SD1.5） | 注册表登记端口 5000 | 生成播客 |
| 云端视频大脑 | Agnes 兼容接口 | 无本地端口 | 云端文生视频 |

聊天大脑与编码大脑共用同一个 llama-swap 进程与端口 9292，由请求里的模型名区分；
其余大脑各自独立。注册表在 `brain_manager.py` 的 `BRAINS` 字典中，每项记录名称、端口、
类型、状态与一个 `vram_gb` 估算值。该估算值只用于监控页展示，并非实测占用；
`app_monitor.py` 在渲染时会用实际观测替换其中的聊天大脑数值。

模型定义在 `llama-swap.yaml`：

```yaml
models:
  xiaojiao:
    cmd: <llama-server 路径> --port ${PORT} --model <GGUF 路径> -c 20000 --reasoning off
    ttl: 0
    useModelName: xiaojiao1.0-4B
  coder:
    cmd: "<llama-server 路径> --port ${PORT} --model <Qwen3-8B 权重路径> -c 20000 --reasoning off"
    ttl: 0
    useModelName: qwen3-8b
```

`ttl: 0` 表示不按空闲时间自动卸载，卸载由小焦主动发起（切到别的大脑，或生成视频、音乐前让位）。

## 4. 显存管理规则

小焦把每颗大脑的状态记为下列四种之一，规则围绕状态转换展开。

| 状态 | 含义 |
|---|---|
| `RUN` | 权重在显存，正在服务请求 |
| `WARM` | 权重在内存，进程仍在，切回不需要重新读盘 |
| `SLEEP` | 初始状态，未加载 |
| `OFF` | 已彻底卸载，显存与内存都不占 |

四条约束：

1. `RUN` 只允许一颗。任一时刻最多一颗大脑占用显存。
2. `WARM` 只允许一颗。被新的温存顶掉的那一颗会被彻底卸载，不留驻留进程。
3. 切换目标 X 时，执行三步：先卸载已处于 `WARM` 且不是 X 的大脑；再把当前 `RUN` 的大脑转为 `WARM`；
   最后把 X 唤醒到 `RUN`。实现见 `brain_manager.switch_to()`。
4. 生成前主动让位。视频与音乐在加载自己的模型前会先卸载 llama 大脑，使当前任务独占显存。

由此得到三条使用性质：

- 谁在用谁全速：正在服务的大脑独占显存，不与其他大脑争抢。
- 上次用的留内存：切回上一个大脑时无需重新读盘。
- 不出现双模型驻留：切走是真正卸载权重，不是只改一个状态标记。

## 5. 禁用思考

聊天大脑与编码大脑的启动参数里都写了 `--reasoning off`。开启思考的模型会先生成一段内部推理
再给答案，在本地小模型上表现为等待变长，有时还会把答案挤空。关掉之后模型直接回复，
工具调用照常。两个模型的上下文窗口都设为 20000（`-c 20000`）。

## 6. 切换耗时

下表是原文档记录的本机观测值，本轮重写未重新测量，仅供量级参考。

| 操作 | 耗时 |
|---|---|
| 首次切到编码大脑 | 约 20 秒，8B 权重从硬盘加载到显存 |
| 编码大脑已在显存 | 快，独占显存全速 |
| 切回聊天大脑（4B 已完全卸载） | 约 9 秒，4B 权重冷加载 |
| 温存状态下切回 | 秒级，权重从内存搬到显存 |

前两行与后两行的差别来自一个前提：llama-swap 是否还持有该模型的权重。只要模型处于 `WARM`，
切换就是内存到显存的搬运；一旦被顶掉而要读盘，就退回冷加载的量级。

## 7. 一键添加本地模型

设置页的「一键加本地GGUF」调用 `POST /api/model/addlocal`，参数为 `name`（显示名）、
`gguf`（模型文件绝对路径）、`ctx`（上下文，默认 20000）。该接口依次完成四件事：

1. 往 `llama-swap.yaml` 追加一条模型定义，模型标识取 `name` 的小写形式并把空格换成连字符。
2. 往 `brain_manager.py` 的 `BRAINS` 插入一项，端口 9292、类型 `llama`、初始状态 `OFF`。
3. 往 `xiaojiao_control.json` 的 `models` 列表追加一条，使模型出现在网页下拉中。
4. 重启 llama-swap 进程。

第 2、3 步是直接改写源码与配置文件。运行前建议确认工作副本已纳入版本管理，
否则新增模型会以未提交改动出现在 `brain_manager.py` 中。

## 8. 边界与限制

1. 显存容量决定实际可选模型。本文档不给出具体的显存或内存数值要求，请以本机实测为准。
2. `switch_to()` 的"秒级"取决于底层服务是否支持权重卸载与重新加载。llama-swap 的
   `/api/models/unload/<模型标识>` 是卸载入口；ComfyUI 侧靠 `--lowvram` 与进程常驻。
   vLLM 等其他引擎的睡眠模式尚未接入。
3. 编码大脑的"工具、代码更强"是模型选择层面的判断，量化对比未实测。
4. `brain_manager._evict_ram_brains()` 已定义但没有任何调用方，`switch_to()` 里已包含等价逻辑，
   该函数属冗余代码。
5. 第 7 节的接口会改写 `brain_manager.py` 源码，属于"配置即代码"的做法，升级时可能与
   上游改动冲突。
6. `llama-swap.yaml` 文件头的注释写的是"监听 8080"，实际监听地址由启动参数
   `--listen 127.0.0.1:9292` 决定，注释已过期。

## 9. 故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 切到编码大脑后无响应 | llama-swap 未运行，或 GGUF 路径失效 | 打开 `/monitor` 看状态；确认 9292 端口在线 |
| 切换后显存仍被占满 | 上一个模型未被卸载 | 调 `POST /api/monitor/op` 的 `release` 或 `clearVram` |
| 回复很慢或内容为空 | 模型开启了思考 | 检查 `llama-swap.yaml` 中该模型是否带 `--reasoning off` |
| 一键加模型后下拉里没有 | 第 3 步写控制文件失败 | 查看返回 JSON 的 `note`；手工确认 `xiaojiao_control.json` 的 `models` |
| 新增模型未生效 | llama-swap 未重启成功 | 查看返回的 `note`；确认能找到 `llama-swap.exe` 或设置 `XIAOJIAO_LLAMA_SWAP` |
| 编码请求仍走 4B | 请求里的模型名不是 `coder` | 确认控制文件 `brain.api.model` 与 llama-swap 路由键一致 |

## 10. 参考

- 调度机制全文：[brain-switch.md](brain-switch.md)
- 大脑监控面板：[monitor.md](monitor.md)
- 模型接入与可替换性：[architecture.md](architecture.md)、[xiaojiao_model.md](xiaojiao_model.md)
- 生成视频时的显存让位：[video.md](video.md)
- 代码：`brain_manager.py`、`llama-swap.yaml`、`video_service/model_switch.py`、`app_monitor.py`

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
| 2026-09-14 | v1.0 | 补全 `RUN`/`WARM`/`SLEEP`/`OFF` 四状态；标注 `_evict_ram_brains()` 为冗余、`llama-swap.yaml` 文件头注释过期 |
