# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 工具说明的规范化（让模型能精准选工具、精准填参数）

【为什么需要这一层】工具表是模型选工具的唯一依据。实测下来它有三个通病：
① **说明太长**：历史插件里有 80~160 字的，长句里混着好几个触发词 → 每个工具都"像"，
   小模型反而更容易挑错（这个项目对插件作者的约定本来就是"一句话、≤60 字"）；
② **参数没说明**：模型知道要传 `spec_json`，但不知道里面写什么 → 于是瞎编一个；
③ **schema 不规范**：个别插件给的不是 `{type: object, properties: {...}}`。

逐个去改 20 个插件风险大（可能改坏原意）。所以**在合并工具表这一层统一规范化**：
   · 说明超长 → 只给模型看"第一句"（真源不动，全文仍留在插件里，清单文档会带全文）；
   · 参数缺说明 → 先查 `PARAM_ZH` 这张通用词典（url / selector / session_id / diagram_type… 这些
     名字各插件通用，含义是确定的）；词典里没有就如实标"作者未写说明"，**不编语义**；
   · schema 缺 type/properties → 补成合法 object。

【边界】这里只做"让模型看得懂"的规范化，**不改变任何工具的语义**、不删参数、不改 execute。
"""
import re

# 说明长度上限（中文按字数算；60 字是项目里插件示例一直用的标准）
DESC_LIMIT = 60

# 常见参数名的中文含义（各插件通用、语义确定，所以可以统一说明；**不猜**业务字段）
PARAM_ZH = {
    "url": "网址（http/https 开头）",
    "urls": "网址列表",
    "selector": "CSS 选择器（如 h1、.content、#main）",
    "session_id": "会话 ID（先 open_session 拿到的那个）",
    "session_type": "会话类型：dynamic（普通浏览器）或 stealthy（反检测）",
    "full_page": "是否整页截图（true/false）",
    "ignore_robots": "是否忽略 robots.txt（默认 false，建议保持 false）",
    "filename": "保存到本地时用的文件名",
    "path": "本地文件路径",
    "file": "本地文件路径",
    "dir": "目录路径",
    "text": "要处理/保存的文本内容",
    "content": "内容正文",
    "query": "要检索/查询的关键词或问题",
    "q": "要检索/查询的关键词或问题",
    "keyword": "关键词",
    "pattern": "匹配模式（正则或字面量）",
    "intent": "要做的事，用一句话说（中文即可）",
    "target": "目标文件路径",
    "focus": "关注的函数名/地址/关键词",
    "tool": "工具名（先用 rea_tools 搜）",
    "args": "该工具的参数对象",
    "limit": "最多返回几条",
    "top_k": "取前几条",
    "k": "取前几条",
    "n": "数量",
    "count": "数量",
    "lines": "行数",
    "seconds": "时长（秒）",
    "seconds_per_segment": "每段时长（秒）",
    "prompt": "生成用的提示词",
    "negative_prompt": "反向提示词（不要出现的东西）",
    "model": "模型名",
    "name": "名字/名称",
    "title": "标题",
    "topic": "主题",
    "style": "风格",
    "lang": "语言（zh/en）",
    "code": "代码文本",
    "command": "要执行的命令",
    "expr": "要计算的表达式",
    "expression": "要计算的表达式",
    "memory_id": "记忆条目 ID",
    "id": "条目标识",
    "kind": "类别",
    "reason": "理由/原因",
    "why": "为什么",
    "summary": "摘要",
    "diagram_type": "图表类型：architecture / workflow / sequence / dataflow / lifecycle",
    "spec_json": "图表的 JSON 规格（先用 read_example 看该类型的完整示例）",
    "output_name": "输出文件名（不含扩展名）",
    "quality": "质量档位：draft（快）/ standard / high",
    "html_path": "本地 HTML 文件路径",
    "base_json": "基线那份 JSON 的路径",
    "head_json": "要对比的那份 JSON 的路径",
    "items": "条目列表（数组）",
    "scenario": "使用场景名称",
    "action": "动作：open / close / list / fetch / request / screenshot",
    "messages": "消息列表（role + content）",
    "temperature": "温度（0~1，越低越稳）",
    "max_tokens": "最多生成多少 token",
    "message": "消息内容",
    "persona": "人格/角色名",
    "city": "城市名",
    "audio_path": "音频文件路径",
    "video_path": "视频文件路径",
    "task_tag": "任务标签（用来把记录分组）",
    "min_refs": "最少引用次数",
    "overwrite": "是否覆盖已有文件（true/false）",
    "dry_run": "只演算不落地（true/false）",
}

_BAD_DESC = ("todo", "占位", "placeholder", "xxx", "待补", "fixme")
_VERBS = ("查", "读", "写", "列", "跑", "做", "给", "看", "找", "搜", "生成", "算", "抓", "下",
          "解", "转", "切", "记", "问", "打开", "关", "收", "聚", "连", "取", "析", "检查", "统计",
          "执行", "调用", "保存", "加载", "清理", "对比", "校验", "测", "启动", "停", "换", "装",
          "导入", "导出", "渲染", "验证", "预览", "交付", "批", "诊断", "指导", "合并",
          "体检", "推荐", "作废", "溯源", "发", "开", "进", "回滚", "锁定", "丢弃", "评审", "喂")


def is_cjk(s):
    return bool(re.search(r"[\u4e00-\u9fff]", str(s or "")))


def short_desc(desc, limit=DESC_LIMIT):
    """压成"模型看一眼就够"的那一句。

    【挑哪一句】不是无脑取第一句 —— 实测有的说明第一句是纯名词短语
    （「**漏洞清单唯一入口**(NVD 结构化数据)。」），拿它给模型看等于没说清"什么时候用"。
    所以优先取**第一个带动词或带冒号**的短句；都没有才退回第一句，再不行硬切。
    """
    s = " ".join(str(desc or "").split())
    if not s:
        return ""
    if len(s) <= limit:
        return s
    clauses = [c for c in re.split(r"(?<=[。；;！!？?])", s) if c.strip()]
    for c in clauses:
        c = c.strip()
        if len(c) <= limit and (any(v in c for v in _VERBS) or "：" in c or ":" in c):
            return c
    for c in clauses:
        c = c.strip()
        if len(c) <= limit:
            return c
    for sep in ("。", "；", ";", "！", "!", "？", "?"):
        i = s.find(sep)
        if 0 < i + 1 <= limit:
            return s[:i + 1]
    return s[:limit - 1] + "…"


def normalize_schema(params):
    """保证是合法 JSON Schema object，并且**每个参数都有说明**。返回 (schema, 自动补过的参数名)。"""
    prm = params if isinstance(params, dict) else {}
    prm = dict(prm)
    prm.setdefault("type", "object")
    props = prm.get("properties")
    if not isinstance(props, dict):
        props = {}
    filled = []
    new_props = {}
    for pname, spec in props.items():
        spec = dict(spec) if isinstance(spec, dict) else {}
        spec.setdefault("type", "string")
        d = str(spec.get("description") or "").strip()
        if not d:
            zh = PARAM_ZH.get(str(pname).lower())
            if zh:
                spec["description"] = zh
                filled.append(str(pname))
            else:
                spec["description"] = "（作者未写说明；按参数名理解为：%s）" % pname
                filled.append(str(pname))
        new_props[pname] = spec
    prm["properties"] = new_props
    prm["required"] = [r for r in (prm.get("required") or []) if r in new_props]
    return prm, filled


def normalize_tool(fn):
    """规范化一个给模型看的 function 声明。返回 (新 fn, 报告 dict)。"""
    fn = dict(fn or {})
    rep = {"shortened": False, "filled_params": [], "desc_problem": ""}
    full = str(fn.get("description") or "")
    fn["description"] = short_desc(full)
    rep["shortened"] = fn["description"] != full
    prm, filled = normalize_schema(fn.get("parameters"))
    fn["parameters"] = prm
    rep["filled_params"] = filled
    d = fn["description"]
    if not d:
        rep["desc_problem"] = "没有说明"
    elif not is_cjk(d):
        rep["desc_problem"] = "说明不是中文"
    elif len(d) > DESC_LIMIT + 20:
        rep["desc_problem"] = "说明仍偏长（%d 字）" % len(d)
    elif any(w in d.lower() for w in _BAD_DESC):
        rep["desc_problem"] = "说明像占位符"
    elif not any(v in d for v in _VERBS) and "：" not in d and ":" not in d:
        # 带冒号的说明（"XX：用来做YY"）本身就是"场景+用途"，不必强行有动词
        rep["desc_problem"] = "说明读不出「什么时候用」"
    return fn, rep
