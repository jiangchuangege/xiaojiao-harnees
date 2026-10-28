# 自测报告（`tools/run_all_tests.py` 生成）

- 文件：130 个（跳过 1）｜ 断言：4078 / 4098 ｜ 没通过的文件：10 个
- 每文件单独子进程 + 超时 150 秒（超时算「卡死」）；5 路并行，没通过的已串行复测
- 总耗时 99.4 分钟

| 测试文件 | 结论 | 通过/共 | 耗时(秒) | 备注 |
| --- | --- | --- | --- | --- |
| `test_4_gaps.py` | 通过 | 60/60 | 5.1 |  |
| `test_6_capabilities.py` | 卡死 | 0/1 | 602.4 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_agnes_live.py` | 有失败 | 0/1 | 310.6 | 复测：有失败 |
| `test_answer_gate.py` | 通过 | 14/14 | 0.0 |  |
| `test_autonomy.py` | 通过 | 111/111 | 17.0 |  |
| `test_boost.py` | 通过 | 195/195 | 0.6 |  |
| `test_brain_line_cleanup.py` | 通过 | 12/12 | 7.2 |  |
| `test_bug2_dedup.py` | 通过 | 16/16 | 6.3 |  |
| `test_bug3_repeat.py` | 通过 | 20/20 | 1.2 |  |
| `test_bug45_ui.py` | 通过 | 42/42 | 17.9 |  |
| `test_bug6_open_html.py` | 通过 | 12/12 | 5.3 |  |
| `test_capability_parity.py` | 通过 | 37/37 | 0.1 |  |
| `test_carrier.py` | 通过 | 64/64 | 8.8 |  |
| `test_carrier_block.py` | 通过 | 26/26 | 4.7 |  |
| `test_causal_hooks.py` | 通过 | 37/37 | 6.2 |  |
| `test_causal_memory_ext.py` | 通过 | 37/37 | 0.1 |  |
| `test_causal_memory_plugin.py` | 通过 | 25/25 | 0.3 |  |
| `test_central.py` | 通过 | 44/44 | 0.4 |  |
| `test_chain.py` | 通过 | 16/16 | 3.6 |  |
| `test_channel_policy.py` | 通过 | 24/24 | 3.0 |  |
| `test_closed_loop.py` | 卡死 | 0/1 | 900.0 | 复测：卡死；超过 900 秒没结束（已杀掉） |
| `test_cloud_video_spec.py` | 通过 | 57/57 | 10.8 |  |
| `test_cloud_video_worker.py` | 通过 | 10/10 | 5.8 |  |
| `test_cn_number.py` | 通过 | 34/34 | 0.0 |  |
| `test_code_judge.py` | 通过 | 25/25 | 4.0 |  |
| `test_comments_audit.py` | 通过 | 34/34 | 4.1 |  |
| `test_context_merge.py` | 通过 | 91/91 | 3.7 |  |
| `test_cross_check_wired.py` | 通过 | 17/17 | 3.8 |  |
| `test_degen_strategy.py` | 通过 | 13/13 | 0.1 |  |
| `test_degeneration.py` | 通过 | 31/31 | 0.3 |  |
| `test_diagnose_code.py` | 通过 | 39/39 | 3.7 |  |
| `test_docs_audit.py` | 通过 | 42/42 | 0.0 |  |
| `test_dual_check.py` | 通过 | 15/15 | 10.5 |  |
| `test_ebook_plugin.py` | 通过 | 35/35 | 18.0 |  |
| `test_embedder_long.py` | 通过 | 18/18 | 2.6 |  |
| `test_energy.py` | 通过 | 46/46 | 32.1 |  |
| `test_event_what_retrieval.py` | 通过 | 1/1 | 44.0 |  |
| `test_evidence_ledger.py` | 通过 | 35/35 | 0.1 |  |
| `test_fact_doctor.py` | 通过 | 30/30 | 4.3 |  |
| `test_file_claim_correction.py` | 通过 | 11/11 | 0.1 |  |
| `test_fresh_clone.py` | 通过 | 13/13 | 48.8 |  |
| `test_gate_evolve.py` | 通过 | 31/31 | 7.6 |  |
| `test_health.py` | 通过 | 142/142 | 0.5 |  |
| `test_health_integration.py` | 通过 | 38/38 | 2.9 |  |
| `test_heart_back.py` | 通过 | 16/16 | 3.4 |  |
| `test_heartbeat.py` | 通过 | 40/40 | 51.3 |  |
| `test_impression_usage.py` | 有失败 | 0/1 | 191.2 | 复测：有失败 |
| `test_infinity_456.py` | 通过 | 32/32 | 5.2 |  |
| `test_inline_code.py` | 通过 | 13/13 | 7.5 |  |
| `test_inner.py` | 通过 | 54/54 | 4.8 |  |
| `test_inner_facts.py` | 通过 | 7/7 | 3.1 |  |
| `test_inner_joint.py` | 通过 | 28/28 | 1.7 |  |
| `test_input_infinity.py` | 通过 | 27/27 | 0.7 |  |
| `test_interoceptive.py` | 通过 | 23/23 | 198.3 | 复测：通过 |
| `test_last_jump.py` | 通过 | 1/1 | 71.2 |  |
| `test_log_rotation.py` | 通过 | 9/9 | 0.1 |  |
| `test_longform_quality.py` | 通过 | 29/29 | 0.4 |  |
| `test_math_render.py` | 有失败 | 0/1 | 33.2 | 复测：有失败 |
| `test_mem_filter.py` | 通过 | 26/26 | 3.8 |  |
| `test_mem_source.py` | 通过 | 15/15 | 3.3 |  |
| `test_memory_depth.py` | 有失败 | 72/73 | 3.0 | 复测：有失败 |
| `test_memory_gate.py` | 通过 | 64/64 | 0.7 |  |
| `test_memory_gate_wiring.py` | 通过 | 16/16 | 4.0 |  |
| `test_memory_plugin_gate.py` | 通过 | 22/22 | 2.1 |  |
| `test_memory_recall.py` | 通过 | 1/1 | 109.3 | 复测：通过 |
| `test_memory_upkeep.py` | 通过 | 36/36 | 4.1 |  |
| `test_memory_upkeep_wiring.py` | 通过 | 14/14 | 11.6 |  |
| `test_memory_vec_index.py` | 通过 | 18/18 | 3.6 |  |
| `test_memory_write_dedupe.py` | 通过 | 10/10 | 3.2 |  |
| `test_metacognition.py` | 通过 | 143/143 | 0.2 |  |
| `test_mind.py` | 通过 | 77/77 | 28.2 |  |
| `test_mind_facts.py` | 通过 | 12/12 | 0.0 |  |
| `test_mind_stream.py` | 通过 | 67/67 | 0.1 |  |
| `test_mind_stream_live.py` | 卡死 | 0/1 | 600.0 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_model_add_keeps_video_api.py` | 通过 | 9/9 | 4.7 |  |
| `test_model_name_reconcile.py` | 通过 | 18/18 | 2.7 |  |
| `test_model_router.py` | 通过 | 22/22 | 0.1 |  |
| `test_module_integration.py` | 有失败 | 8/19 | 490.0 | 复测：有失败 |
| `test_no_delete.py` | 通过 | 101/101 | 0.3 |  |
| `test_paths.py` | 通过 | 23/23 | 0.1 |  |
| `test_perception.py` | 通过 | 41/41 | 6.0 |  |
| `test_perception_infinity.py` | 通过 | 9/9 | 141.6 | 复测：通过 |
| `test_persona.py` | 通过 | 58/58 | 0.0 |  |
| `test_perspective.py` | 通过 | 16/16 | 0.1 |  |
| `test_platform_integration.py` | 通过 | 39/39 | 50.1 |  |
| `test_plugin_forge.py` | 通过 | 21/21 | 0.3 |  |
| `test_preference_gate.py` | 通过 | 18/18 | 0.1 |  |
| `test_preinstall.py` | 通过 | 31/31 | 0.2 |  |
| `test_profile_recall_integration.py` | 跳过 | 0/0 | 0.2 |  |
| `test_profile_system.py` | 通过 | 84/84 | 0.2 |  |
| `test_project_runner.py` | 通过 | 43/43 | 0.3 |  |
| `test_raw.py` | 通过 | 33/33 | 3.5 |  |
| `test_rea_plugin.py` | 通过 | 40/40 | 2.7 |  |
| `test_rea_router.py` | 通过 | 12/12 | 0.1 |  |
| `test_realtime_fact.py` | 通过 | 23/23 | 2.5 |  |
| `test_redline_integration.py` | 通过 | 40/40 | 5.1 |  |
| `test_repeat_all_paths.py` | 通过 | 30/30 | 4.7 |  |
| `test_rerank_gate.py` | 通过 | 14/14 | 0.1 |  |
| `test_retrieval_rerank.py` | 通过 | 22/22 | 0.1 |  |
| `test_route_table.py` | 通过 | 39/39 | 4.2 |  |
| `test_scrape_retry.py` | 通过 | 24/24 | 51.1 |  |
| `test_scrape_save.py` | 通过 | 23/23 | 4.1 |  |
| `test_search_intent.py` | 通过 | 58/58 | 4.1 |  |
| `test_search_modifier.py` | 通过 | 34/34 | 7.1 |  |
| `test_self_echo.py` | 通过 | 19/19 | 4.1 |  |
| `test_self_evolve.py` | 通过 | 28/28 | 10.3 |  |
| `test_self_model.py` | 通过 | 17/17 | 8.9 |  |
| `test_silent_evolve.py` | 通过 | 23/23 | 3.9 |  |
| `test_single_request_limit.py` | 卡死 | 0/1 | 600.1 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_spirit_memory.py` | 通过 | 41/41 | 2.8 |  |
| `test_state_policy.py` | 通过 | 19/19 | 3.5 |  |
| `test_stream_render.py` | 通过 | 22/22 | 299.3 | 复测：通过 |
| `test_task_runner.py` | 通过 | 35/35 | 2.1 |  |
| `test_thinking_loop_vector.py` | 通过 | 22/22 | 6.2 |  |
| `test_time_context.py` | 通过 | 15/15 | 83.5 | 复测：通过 |
| `test_timeline_search.py` | 有失败 | 0/1 | 5.3 | 复测：有失败 |
| `test_tool_contract.py` | 通过 | 12/12 | 4.1 |  |
| `test_tool_gate.py` | 通过 | 29/29 | 15.6 |  |
| `test_tool_infinity_live.py` | 通过 | 18/18 | 64.3 |  |
| `test_tool_isolation.py` | 通过 | 52/52 | 3.8 |  |
| `test_two_fixes.py` | 通过 | 11/11 | 4.0 |  |
| `test_user_profile.py` | 通过 | 48/48 | 0.3 |  |
| `test_video_audio.py` | 通过 | 27/27 | 130.1 |  |
| `test_video_ui_wiring.py` | 通过 | 37/37 | 4.3 |  |
| `test_vram_policy.py` | 通过 | 25/25 | 0.1 |  |
| `test_wholeness.py` | 通过 | 63/63 | 11.3 |  |
| `test_world.py` | 通过 | 12/12 | 6.6 |  |
| `test_world_firewall.py` | 通过 | 46/46 | 18.2 |  |
| `test_write_judge.py` | 通过 | 31/31 | 4.7 |  |
| `test_write_overwrite_path.py` | 通过 | 21/21 | 5.4 |  |
