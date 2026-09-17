# -*- coding: utf-8 -*-
"""记忆插件（`save_memory` / `read_memory`）

【2026-09-17 加了写闸，为什么】
    这个文件的写入侧原来是**裸的**：`save_memory` 拿到什么就 `f.write` 什么。
    实测后果：一份早期遗留存盘里躺着模型退化出来的复读乱码
    （`亻命鸵次次次亻扑…` 重复 9 遍）与大量老胡话，而 `read_memory` 会**整份原样**
    读出来给模型 —— 用户就在界面上看见了它（那张卡片）。
    存量已经搬进隔离区（`logs/quarantine/`，见那份 README），**这里堵源头**。

【判据从哪来：复用，不另造一套】
    走的是 `core/mem_filter.py` —— **和"对话记忆"那条链完全同一个判据**
    （工具原始返回 / 坏回复 / 占位符，全部确定性正则）。项目吃过"留着两套同功能实现、
    模板和问法互相打脸"的亏，所以这里一个字都不自己写一套。
    在此之上补一条这个文件独有的：**完全重复的内容不重复追加**（同一条已经写过就不再写）。

【如实标注（没做到的）】
    · 复读乱码（`亻命鸵次次次` 那一类）**没有专门的判据**：试过的几条（重复子串、
      生僻字比例）都会误伤正常记忆（中文里「哈哈哈」「猫猫猫」这类重复是合法的），
      宁可不拦，也不许把真东西挡在门外。这一条留作已知缺口。
    · 写闸只在**这条工具路径**上；`xiaojiao_harness.py`（老入口）仍然直接 append。
"""
import datetime
import os
import sys

# 让 `from core import ...` 在两种入口下都成立（应用加载插件 / 直接跑这个文件）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class MemoryPlugin:
    """记忆管理插件"""

    def get_tool_descriptions(self):
        return [
            {"name": "save_memory", "description": "把用户明确要求记住的事存进长期记忆。什么时候用：用户说「记住…」「以后都…」；输入 content；输出 保存结果", "parameters": {"content": "要记住的内容"}},
            {"name": "read_memory", "description": "读回所有已保存的记忆。什么时候用：用户问「你记得什么」或需要核对偏好；无参数；输出 记忆列表", "parameters": {}}
        ]

    # ---------------------------------------------------------------- 写闸
    @staticmethod
    def _gate(content):
        """要不要写、写什么。返回 `(可写?, 正文或原因)`。**不写的时候必须给出原因**。"""
        c = str(content or "").strip()
        if not c:
            return False, "空内容"
        # ① 复用对话记忆那条写闸（工具原文 / 坏回复 / 占位符）
        try:
            from core import mem_filter as MF
            cleaned, why = MF.clean_answer(c)
            if not cleaned:
                return False, str(why or "被判为不该进记忆的内容")
            c = cleaned
        except Exception as e:      # noqa: silent-ok — 闸门不在就照常写（不能因闸门坏了把功能弄没）
            print("[memory] 写闸不可用，照常写入：%s" % e)
        # ② 完全重复不重复追加（同一条内容已经写过就不再写第二遍）
        try:
            if os.path.exists("xiaojiao_memory.txt"):
                with open("xiaojiao_memory.txt", "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        body = line.split(" - ", 1)[-1].strip() if " - " in line else line.strip()
                        if body and body == c:
                            return False, "这条已经记过了（完全一样，不重复写）"
        except Exception as e:      # noqa: silent-ok
            print("[memory] 查重失败，照常写入：%s" % e)
        # ③ 明显不成话的（一个字符连 5 次以上 / 整条没有任何中文或字母数字）
        import re as _re
        if _re.search(r"(.)\1{4,}", c):
            return False, "判为复读（同一个字符连着 5 次以上）"
        if not _re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", c):
            return False, "判为不成话（整条没有中文也没有字母数字）"
        return True, c

    def execute(self, tool_name, params):
        if tool_name == "save_memory":
            content = params.get("content", "")
            ok, payload = self._gate(content)
            if not ok:
                # **不写就说实话**：不假装"已记住"（那是粉饰），把原因带出去
                print("[memory] 这条不记：%s" % payload)
                return "这条**没有记**：%s" % payload
            with open("xiaojiao_memory.txt", "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now()} - {payload}\n")
            return f"已记住：{payload}"

        if tool_name == "read_memory":
            if not os.path.exists("xiaojiao_memory.txt"):
                return "还没有任何记忆"
            with open("xiaojiao_memory.txt", "r", encoding="utf-8") as f:
                return f.read()

        return None
