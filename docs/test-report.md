# 自测报告（`tools/run_all_tests.py` 生成）

- 文件：126 个（跳过 1）｜ 断言：3975 / 4015 ｜ 没通过的文件：8 个
- 每文件单独子进程 + 超时 150 秒（超时算「卡死」）；5 路并行，没通过的已串行复测
- 总耗时 90.3 分钟

| 测试文件 | 结论 | 通过/共 | 耗时(秒) | 备注 |
| --- | --- | --- | --- | --- |
| `test_4_gaps.py` | 通过 | 60/60 | 6.0 |  |
| `test_6_capabilities.py` | 有失败 | 9/19 | 555.4 | 复测：有失败 |
| `test_agnes_live.py` | 有失败 | 0/1 | 309.9 | 复测：有失败 |
| `test_answer_gate.py` | 通过 | 14/14 | 0.0 |  |
| `test_autonomy.py` | 通过 | 111/111 | 17.0 |  |
| `test_boost.py` | 通过 | 195/195 | 0.6 |  |
| `test_brain_line_cleanup.py` | 通过 | 12/12 | 7.0 |  |
| `test_bug2_dedup.py` | 通过 | 16/16 | 2.7 |  |
| `test_bug3_repeat.py` | 通过 | 20/20 | 0.7 |  |
| `test_bug45_ui.py` | 通过 | 42/42 | 17.6 |  |
| `test_bug6_open_html.py` | 通过 | 12/12 | 5.1 |  |
| `test_carrier.py` | 通过 | 64/64 | 8.3 |  |
| `test_carrier_block.py` | 通过 | 26/26 | 3.4 |  |
| `test_causal_hooks.py` | 通过 | 37/37 | 6.2 |  |
| `test_causal_memory_ext.py` | 通过 | 37/37 | 0.0 |  |
| `test_causal_memory_plugin.py` | 通过 | 25/25 | 0.3 |  |
| `test_central.py` | 通过 | 44/44 | 0.4 |  |
| `test_chain.py` | 通过 | 16/16 | 4.3 |  |
| `test_channel_policy.py` | 通过 | 24/24 | 2.8 |  |
| `test_closed_loop.py` | 卡死 | 0/1 | 900.0 | 复测：卡死；超过 900 秒没结束（已杀掉） |
| `test_cloud_video_spec.py` | 通过 | 57/57 | 10.8 |  |
| `test_cloud_video_worker.py` | 通过 | 10/10 | 5.8 |  |
| `test_cn_number.py` | 通过 | 34/34 | 0.1 |  |
| `test_code_judge.py` | 通过 | 25/25 | 3.8 |  |
| `test_comments_audit.py` | 通过 | 34/34 | 3.6 |  |
| `test_context_merge.py` | 通过 | 91/91 | 3.0 |  |
| `test_cross_check_wired.py` | 通过 | 17/17 | 3.1 |  |
| `test_degen_strategy.py` | 通过 | 13/13 | 0.1 |  |
| `test_degeneration.py` | 通过 | 31/31 | 0.3 |  |
| `test_diagnose_code.py` | 通过 | 39/39 | 3.7 |  |
| `test_docs_audit.py` | 通过 | 42/42 | 0.1 |  |
| `test_dual_check.py` | 通过 | 15/15 | 16.7 |  |
| `test_ebook_plugin.py` | 通过 | 35/35 | 15.5 |  |
| `test_embedder_long.py` | 通过 | 18/18 | 3.0 |  |
| `test_energy.py` | 通过 | 46/46 | 31.1 |  |
| `test_event_what_retrieval.py` | 通过 | 1/1 | 57.3 |  |
| `test_fact_doctor.py` | 通过 | 30/30 | 4.8 |  |
| `test_file_claim_correction.py` | 通过 | 11/11 | 0.0 |  |
| `test_fresh_clone.py` | 通过 | 13/13 | 31.6 |  |
| `test_health.py` | 通过 | 142/142 | 0.4 |  |
| `test_health_integration.py` | 通过 | 38/38 | 3.6 |  |
| `test_heart_back.py` | 通过 | 16/16 | 2.9 |  |
| `test_heartbeat.py` | 通过 | 40/40 | 70.8 |  |
| `test_impression_usage.py` | 有失败 | 0/1 | 157.5 | 复测：有失败 |
| `test_infinity_456.py` | 通过 | 32/32 | 4.3 |  |
| `test_inline_code.py` | 通过 | 13/13 | 7.8 |  |
| `test_inner.py` | 通过 | 54/54 | 5.0 |  |
| `test_inner_facts.py` | 通过 | 7/7 | 2.8 |  |
| `test_inner_joint.py` | 通过 | 28/28 | 1.7 |  |
| `test_input_infinity.py` | 通过 | 27/27 | 0.5 |  |
| `test_interoceptive.py` | 通过 | 23/23 | 212.1 | 复测：通过 |
| `test_last_jump.py` | 通过 | 1/1 | 18.4 | 复测：通过 |
| `test_log_rotation.py` | 通过 | 9/9 | 0.1 |  |
| `test_longform_quality.py` | 通过 | 29/29 | 0.3 |  |
| `test_math_render.py` | 有失败 | 0/1 | 56.9 | 复测：有失败 |
| `test_mem_filter.py` | 通过 | 26/26 | 3.3 |  |
| `test_mem_source.py` | 通过 | 15/15 | 2.9 |  |
| `test_memory_depth.py` | 通过 | 73/73 | 4.1 |  |
| `test_memory_gate.py` | 通过 | 64/64 | 0.6 |  |
| `test_memory_gate_wiring.py` | 通过 | 16/16 | 4.3 |  |
| `test_memory_plugin_gate.py` | 通过 | 22/22 | 1.6 |  |
| `test_memory_recall.py` | 通过 | 1/1 | 86.2 | 复测：通过 |
| `test_memory_upkeep.py` | 通过 | 36/36 | 2.9 |  |
| `test_memory_upkeep_wiring.py` | 通过 | 14/14 | 9.8 |  |
| `test_memory_vec_index.py` | 通过 | 18/18 | 2.6 |  |
| `test_memory_write_dedupe.py` | 通过 | 10/10 | 2.7 |  |
| `test_metacognition.py` | 通过 | 143/143 | 0.2 |  |
| `test_mind.py` | 通过 | 77/77 | 26.4 |  |
| `test_mind_facts.py` | 通过 | 12/12 | 0.1 |  |
| `test_mind_stream.py` | 通过 | 67/67 | 0.1 |  |
| `test_mind_stream_live.py` | 有失败 | 8/23 | 542.8 | 复测：有失败 |
| `test_model_add_keeps_video_api.py` | 通过 | 9/9 | 5.7 |  |
| `test_model_name_reconcile.py` | 通过 | 18/18 | 3.0 |  |
| `test_model_router.py` | 通过 | 22/22 | 0.1 |  |
| `test_module_integration.py` | 有失败 | 9/19 | 364.7 | 复测：有失败 |
| `test_no_delete.py` | 通过 | 101/101 | 0.2 |  |
| `test_paths.py` | 通过 | 23/23 | 0.1 |  |
| `test_perception.py` | 通过 | 41/41 | 5.9 |  |
| `test_perception_infinity.py` | 通过 | 9/9 | 137.2 | 复测：通过 |
| `test_persona.py` | 通过 | 58/58 | 0.1 |  |
| `test_perspective.py` | 通过 | 16/16 | 0.2 |  |
| `test_platform_integration.py` | 通过 | 39/39 | 50.3 |  |
| `test_plugin_forge.py` | 通过 | 21/21 | 0.3 |  |
| `test_preference_gate.py` | 通过 | 18/18 | 0.1 |  |
| `test_preinstall.py` | 通过 | 31/31 | 0.2 |  |
| `test_profile_recall_integration.py` | 跳过 | 0/0 | 0.1 |  |
| `test_profile_system.py` | 通过 | 84/84 | 0.1 |  |
| `test_raw.py` | 通过 | 33/33 | 2.6 |  |
| `test_rea_plugin.py` | 通过 | 40/40 | 2.6 |  |
| `test_rea_router.py` | 通过 | 12/12 | 0.1 |  |
| `test_realtime_fact.py` | 通过 | 23/23 | 3.0 |  |
| `test_redline_integration.py` | 通过 | 40/40 | 5.5 |  |
| `test_repeat_all_paths.py` | 通过 | 30/30 | 5.2 |  |
| `test_rerank_gate.py` | 通过 | 14/14 | 0.1 |  |
| `test_retrieval_rerank.py` | 通过 | 22/22 | 0.0 |  |
| `test_route_table.py` | 通过 | 39/39 | 4.0 |  |
| `test_scrape_retry.py` | 通过 | 24/24 | 81.5 |  |
| `test_scrape_save.py` | 通过 | 23/23 | 3.5 |  |
| `test_search_intent.py` | 通过 | 58/58 | 3.0 |  |
| `test_search_modifier.py` | 通过 | 34/34 | 2.5 |  |
| `test_self_echo.py` | 通过 | 19/19 | 3.1 |  |
| `test_self_evolve.py` | 通过 | 28/28 | 3.3 |  |
| `test_self_model.py` | 通过 | 17/17 | 3.8 |  |
| `test_silent_evolve.py` | 通过 | 23/23 | 3.1 |  |
| `test_single_request_limit.py` | 卡死 | 0/1 | 600.1 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_spirit_memory.py` | 通过 | 41/41 | 3.7 |  |
| `test_state_policy.py` | 通过 | 19/19 | 4.1 |  |
| `test_stream_render.py` | 通过 | 22/22 | 581.8 |  |
| `test_task_runner.py` | 通过 | 35/35 | 1.0 |  |
| `test_thinking_loop_vector.py` | 通过 | 22/22 | 5.7 |  |
| `test_time_context.py` | 通过 | 15/15 | 77.2 | 复测：通过 |
| `test_timeline_search.py` | 通过 | 24/24 | 7.5 |  |
| `test_tool_contract.py` | 通过 | 12/12 | 3.2 |  |
| `test_tool_gate.py` | 通过 | 29/29 | 5.9 |  |
| `test_tool_infinity_live.py` | 通过 | 18/18 | 55.8 |  |
| `test_tool_isolation.py` | 通过 | 52/52 | 3.5 |  |
| `test_two_fixes.py` | 通过 | 11/11 | 3.7 |  |
| `test_user_profile.py` | 通过 | 48/48 | 0.1 |  |
| `test_video_audio.py` | 通过 | 27/27 | 139.7 |  |
| `test_video_ui_wiring.py` | 通过 | 37/37 | 3.5 |  |
| `test_vram_policy.py` | 通过 | 25/25 | 0.1 |  |
| `test_wholeness.py` | 通过 | 63/63 | 7.7 |  |
| `test_world.py` | 通过 | 12/12 | 6.5 |  |
| `test_world_firewall.py` | 通过 | 46/46 | 13.4 |  |
| `test_write_judge.py` | 通过 | 31/31 | 5.0 |  |
| `test_write_overwrite_path.py` | 通过 | 21/21 | 3.0 |  |
