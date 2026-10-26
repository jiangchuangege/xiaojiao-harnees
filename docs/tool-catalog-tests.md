# 工具可调用性 · 测试通过表

> 由脚本实跑生成，数字不是手写的。配套清单见 [tool-catalog.md](tool-catalog.md)。

**工具表 99 个 ｜ 契约合格 99 个 ｜ 相关自测 21 个，通过 21 个**

## 一、逐条自测结果

| 自测 | 验什么 | 结果 | 统计 |
| --- | --- | --- | --- |
| `tools/test_tool_contract.py` | 工具调用契约（说明 / 参数 / 执行入口 / 清单一致性） | ✅ 通过 | 通过 12 / 共 12 |
| `tools/test_tool_isolation.py` | 通用与专用工具的隔离（这一轮摆哪几个） | ✅ 通过 | 通过 28 / 共 28 |
| `tools/test_rea_plugin.py` | REA 插件本体（假 MCP 服务） | ✅ 通过 | 通过 40 / 共 40 |
| `tools/test_rea_router.py` | REA 意图路由（20 条真实意图） | ✅ 通过 | 通过 12 / 共 12（其中路由命中 19/19 = 100%） |
| `tools/test_causal_memory_plugin.py` | 因果记忆插件 A（6 个工具） | ✅ 通过 | 通过 25 项, 失败 0 项, 跳过 0 项 |
| `tools/test_causal_memory_ext.py` | 因果记忆插件 B（10 个工具） | ✅ 通过 | 通过 37 项, 失败 0 项 |
| `tools/test_causal_hooks.py` | 因果记忆自动埋点 | ✅ 通过 | 通过 37 项, 失败 0 项 |
| `tools/test_memory_depth.py` | 记忆深度（分层 / 降级 / 压缩 / 巩固 / 联想） | ✅ 通过 | 通过 73 / 共 73 |
| `tools/test_memory_gate.py` | 记忆口径判据 | ✅ 通过 | 通过 64 / 共 64 |
| `tools/test_memory_gate_wiring.py` | 记忆口径接线 | ✅ 通过 | 通过 16 / 共 16 |
| `tools/test_memory_upkeep.py` | 记忆保养本体 | ✅ 通过 | 通过 36 / 共 36 |
| `tools/test_memory_upkeep_wiring.py` | 记忆保养接线 | ✅ 通过 | 通过 14 / 共 14 |
| `tools/test_memory_vec_index.py` | 向量索引一致性 | ✅ 通过 | 通过 18 / 共 18 |
| `tools/test_mem_filter.py` | 写入侧过滤 | ✅ 通过 | 通过 26 / 共 26 |
| `tools/test_mem_source.py` | 记忆来源可信度 | ✅ 通过 | 通过 15 / 共 15 |
| `tools/test_memory_write_dedupe.py` | 写入侧去重 | ✅ 通过 | — |
| `tools/test_video_ui_wiring.py` | 视频界面接线 | ✅ 通过 | 通过 37 项, 失败 0 项 |
| `tools/test_video_audio.py` | 视频与配音 | ✅ 通过 | 通过 27 项, 失败 0 项 |
| `tools/test_cloud_video_spec.py` | 云端视频协议适配 | ✅ 通过 | 通过 57 项, 失败 0 项 |
| `tools/test_cloud_video_worker.py` | 云端视频 worker | ✅ 通过 | 通过 10 项, 失败 0 项 |
| `tools/test_model_add_keeps_video_api.py` | 加模型不丢视频协议 | ✅ 通过 | 通过 9 项, 失败 0 项 |

## 二、凭什么说模型能精准调用

1. **看得懂**：每个工具的说明都被压成一句（不超过 60 字，统一在 `core/tool_desc.py` 里做），
   读的是「什么时候用它」。参数缺说明会先查通用词典（url / selector / session_id / diagram_type 等），
   词典里也没有就如实标「作者未写说明」，**不编语义**。
2. **知道填什么**：清单里每个工具都给了调用示例，必填参数已填成能直接抄的值；
   契约自测会校验「示例里的参数名必须真实存在于 schema 里」。
3. **不会静默失败**：所有插件收到不认识的工具名都返回中文说明（列出自己有哪些工具），
   不再返回 None 或裸 dict —— 那两种在调用方看来都是「没有输出」，出问题毫无线索。
4. **清单不许过期**：契约自测会比「清单里的工具集合」和「当前真实工具表」是否相等，
   改了工具却没重新生成清单，直接判不合格。

## 三、怎么维护这份清单

```
python tools/gen_tool_catalog.py       # 改了插件说明或参数后重新生成
python tools/test_tool_contract.py     # 契约自测，不到全绿不算交付
python tools/gen_tool_test_report.py   # 重新生成这份通过表
```

模型侧的实际调用姿势：不确定时先说一句中文「要干什么」（`rea_do` 这类意图入口会替它选工具、
补参数）；确定工具名时直接按清单里的那一行调。

