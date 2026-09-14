# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 世界层 · 隔离区（污染物的**留观点**，不是垃圾场）

【一句话定位】
    隔离区 = 小焦吃互联网时的"观察室"：可疑的东西不吃进去，但**原封不动留着**，
    等三天/七天/三十天再回头看一次，也随时能让用户手动放行或驳回。

【为什么必须有隔离区（而不是"看着脏就丢掉"）】
    三条理由，缺一条这个设计就塌：
      ① **判断会错**。防火墙是规则，规则会误杀（一篇讲反诈的文章里全是"转账""验证码"）。
         没有隔离区，误杀就是**内容永久消失**；有隔离区，误杀只是"晚几天吃"。
      ② **删除是红线**。载体层不许删任何东西（core/security/no_delete.py）。
         "不吃"这个动作如果要靠"删掉"来实现，那免疫系统自己就违反了红线。
         所以"不吃"的工程实现只能是：**不写进记忆 + 另存一份原文**。
      ③ **要能复核**。"为什么这一段被判成污染"必须可查 ——
         隔离条目里存了 classes / reasons / spans（片段的起止 + 原因），
         用户或开发者能拿着原文一行行对回去，规则写错了才有机会被发现并修正。

【落盘形状】（目录 logs/world/quarantine/，logs/ 已被 .gitignore 忽略）
    index.jsonl   索引：一行一次动作（put / mark），**只追加**。
                  为什么索引和执行体分开：查"隔离区里现在有什么"要扫全目录太慢，
                  扫一个 jsonl 的末尾几百行就够；而原文必须一条一文件，
                  因为原文很大、且要求"写下去就不再被改写"。
    q_xxx.json    每个条目一个文件：原文 + 消毒后正文 + 判据 + 复审历史。
                  **写下去以后 raw_text 永不改写**（mark 只改 status/note，
                  并把改动追加进 revisions —— 旧状态留在文件里，不是被抹掉）。

【只新增、只改名、绝不删除（本模块的硬约束）】
    · 不 import shutil，不调用任何删除类 API，不截断任何文件；
    · `put` 遇到同名条目**换一个新编号**，绝不覆盖已有条目；
      去掉这一条 → 两次同秒写入会互相覆盖，先来的污染证物就没了；
    · `mark` 只改状态字段 + 追加 revisions（复审历史），raw_text 一个字符都不动；
      去掉 revisions → 复审把旧状态覆盖掉，"它到底是哪天被谁放行的"就查无对证；
    · 坏文件（写到一半被强杀）不会被抹掉，读取时按"读不出来"处理并如实回报。
      去掉容错 → 一个坏文件让整个隔离区读不出来，免疫系统形同报废。

【对外 API】
    q = Quarantine()                       # 默认 logs/world/quarantine/
    qid = q.put(url, raw, clean, classes, reasons)      # 收进观察室（原文留底）
    q.get(qid) / q.list(days=None) / q.mark(qid, "released", "用户放行")
    q.due_review()                          # 到期该复审的（3/7/30 天）
    q.stats() / q.files()                   # 体检数字 / 目录里现在有哪些文件
"""
import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# 仓库根：core/world/quarantine.py → 上溯三级。
# 为什么自己算一遍而不是 import 世界层：隔离区必须能**单独 import**
# （防火墙、后台复审任务、外部脚本都要用它）。为了一个路径常量把整个世界层拖进来不划算。
# 去掉它 → 从别的工作目录调用时目录会建到随机位置，污染排查会变得极其痛苦。
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORLD_DIR = os.path.join(_ROOT, "logs", "world")
QUARANTINE_DIR = os.path.join(WORLD_DIR, "quarantine")

# 复审节奏：3 天看一眼（是不是误杀）、7 天再看一眼（污染源还活着吗）、30 天做终审。
# 为什么是这三个点而不是每天扫一遍：复审要花人的注意力，天天问用户等于骚扰；
# 而 3/7/30 是"误杀纠正"和"长期污染源清理"两种需求的自然分界。
# 去掉它 → 进隔离区的东西再也没人回头看，隔离区会变成单行道（只能进不能出）。
REVIEW_DAYS = (3, 7, 30)

# 单条原文最多留多少字。为什么要有上限：一条垃圾网页可能几 MB，
# 全部留底会把磁盘吃满（日志目录没有配额）。超长时**留头部**并把截断事实写进
# raw_truncated 字段 —— 截断这件事本身也必须诚实地记下来。
# 去掉它 → 抓到超大页面时隔离区把磁盘写满，连带把主记忆的写入也拖垮。
MAX_RAW_CHARS = 200_000

# 状态机（值必须白名单化：这个词会被面板/统计读，写歪一个就统计不出来）
#   quarantined 观察中（等复审） · reviewed 已复审但仍在隔离区
#   released 用户/复审放行（内容已进主记忆） · rejected 用户驳回（内容判死，仍留底）
ST_QUARANTINED = "quarantined"
ST_REVIEWED = "reviewed"
ST_RELEASED = "released"
ST_REJECTED = "rejected"
_STATUSES = (ST_QUARANTINED, ST_REVIEWED, ST_RELEASED, ST_REJECTED)
_CLOSED = (ST_RELEASED, ST_REJECTED)      # 终态：不再安排复审


def _now():
    "「」当前时间戳（单独抽出来是为了自测能注入 now，不必等三天）。「」"
    return time.time()


def _safe_name(name):
    """把任意字符串变成安全的文件名片段（防目录穿越/非法字符）。

    为什么必须过这一道：qid 有可能来自索引文件，而索引文件是磁盘上的文本，
    理论上可以被手改成 "../../xxx"。把 `..`、路径分隔符、盘符都挡在文件名之外，
    "文件名"就永远只是文件名。
    去掉它 → 一个手改（或写坏）的 qid 就能让 put 写到目录外面去。
    """
    s = "".join(ch for ch in str(name or "") if ch.isalnum() or ch in "_-")
    return s[:120]


def _load_json(path, default=None):
    """读一个小 JSON；读不到/坏了返回 default（**绝不抛**）。

    为什么宽容：隔离条目可能正好在"写到一半被强杀"的状态。
    条目标坏只是"这一条读不出来"，不该让整个隔离区（乃至防火墙）崩掉。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:      # noqa: silent-ok — 坏文件等价于"这条读不出来"，如实回报即可
        return default


def _read_lines(path):
    "「」读一个 JSONL 的所有行（坏行跳过），返回 list[dict]。「」"
    out = []
    try:
        if not os.path.exists(path):
            return out
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:      # noqa: silent-ok — 半截行跳过，不能连累其它行
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except Exception:      # noqa: silent-ok — 读不动就当索引是空的
        return out
    return out


class Quarantine:
    """隔离区：只新增、只改名、绝不删除。

    参数 `root` 可以指定别的目录（自测用它把状态写在 logs/world/_selftest/<本次运行>/ 下，
    绝不碰小焦真正的隔离区）。**注入点是故意的** —— 自测不能污染真实数据。
    """

    def __init__(self, root=None):
        self.root = os.path.abspath(root or QUARANTINE_DIR)
        self.index_path = os.path.join(self.root, "index.jsonl")
        # 一把进程内锁：后台复审线程和主对话线程会同时写索引，
        # 不加锁的话两行内容可能交错（半截行只能靠跳过兜底，能不错位就别错位）。
        #
        # 【本轮实测抓到的真 bug：自锁死】`put()` 会**持着 `self._lock` 去调 `_new_qid()`**，
        # 而 `_new_qid()` 原来也要拿同一把 `Lock` —— threading.Lock **不可重入**，
        # 于是同一个线程把自己锁死：第一次收到需要隔离的内容就**永久挂住**，
        # 整个防火墙一次都跑不过去（"代码写了、接线了、从没真跑过"的典型症状）。
        # 修法：给自增计数单独一把锁（`_seq_lock`），`_new_qid()` 再也不碰 `self._lock`，
        # 这样"谁持着主锁都能安全地取编号"，从结构上消掉这类自锁。
        # 保留主锁为普通 Lock（**不用 RLock**）：RLock 会把真实的加锁错误藏起来，
        # 而这把锁保护的是"索引行不交错"这种一眼能看出问题的东西。
        self._lock = threading.Lock()
        self._seq_lock = threading.Lock()
        self._seq = 0
        try:
            os.makedirs(self.root, exist_ok=True)
        except Exception as e:      # noqa: silent-ok — 建不出目录后面写入会如实失败
            logger.warning("隔离区目录创建失败：%s", e)

    # ------------------------------------------------------------ 内部
    def _new_qid(self):
        """生成一个新编号：`q_日期_时间_序号`。

        为什么带日期时间而不是纯随机：人肉排查时一眼能看出"什么时候进来的"，
        时间顺序也天然等于文件名的排序顺序（列目录就等于按时间回溯）。
        为什么还带序号和进程内计数：同一秒内可能连收好几条，
        纯秒级时间戳会撞名 —— 撞名就必须退化成"覆盖"，而覆盖是绝不允许的。

        **用独立的 `_seq_lock`，不碰主锁**（原因见 `__init__` 里"自锁死"那段）：
        调用方 `put()` 是持着主锁进来的，这里再去拿主锁就是自己把自己锁死。
        """
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        return "q_%s_%03d" % (time.strftime("%Y%m%d_%H%M%S"), seq)

    def _path_of(self, qid):
        "「」条目文件路径（文件名已经过 _safe_name 过滤）。「」"
        return os.path.join(self.root, "%s.json" % _safe_name(qid))

    def _append_index(self, rec):
        "「」往索引追加一行。**只追加**，返回 True/False，绝不抛。「」"
        try:
            line = json.dumps(rec, ensure_ascii=False)
        except Exception as e:      # noqa: silent-ok — 序列化失败只丢这一行索引
            logger.warning("隔离索引序列化失败：%s", e)
            return False
        try:
            with self._lock:
                os.makedirs(self.root, exist_ok=True)
                with open(self.index_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            return True
        except Exception as e:      # noqa: silent-ok — 索引写不上不能中断整个筛查流程
            logger.warning("隔离索引写入失败：%s", e)
            return False

    @staticmethod
    def _next_review_at(ts, stage):
        """按阶段算下一次复审时间；阶段用完返回 None（不再打扰用户）。

        为什么是"从入库时间起算"而不是"从上一次复审起算"：
        污染的新鲜度取决于它**什么时候进来**，不是我们什么时候看过它。
        """
        try:
            stage = int(stage or 0)
        except Exception:      # noqa: silent-ok — stage 坏掉就当作第一段
            stage = 0
        if stage >= len(REVIEW_DAYS):
            return None
        return float(ts) + REVIEW_DAYS[stage] * 86400.0

    # ------------------------------------------------------------ 写入
    def put(self, url, raw_text, clean_text, classes, reasons, qid=None, ts=None,
            spans=None, domain=None, meta=None):
        """收进隔离区。返回条目编号 qid（**原文留底，绝不删**）。

        `qid` 由调用方给时只当作"想要的编号"：**已被占用就换一个新的**。
        为什么不让它覆盖：qid 撞名意味着先前那条污染的证物被后来的内容顶掉，
        而"证物"的全部价值就在于它是**当时那一份原文**。
        去掉这条 → 同一秒两条污染进来，先来的那条原文就永久没了（等于删除）。
        """
        t = _now() if ts is None else float(ts)
        wanted = _safe_name(qid) if qid else ""
        with self._lock:
            use = wanted or self._new_qid()
            path = self._path_of(use)
            n = 0
            while os.path.exists(path) and n < 10000:
                n += 1
                use = "%s_%d" % (wanted or self._new_qid(), n)
                path = self._path_of(use)
        raw = "" if raw_text is None else str(raw_text)
        truncated = len(raw) > MAX_RAW_CHARS
        entry = {
            "qid": use,
            "ts": round(t, 3),
            "url": str(url or ""),
            "domain": str(domain or ""),
            "classes": [str(c) for c in (classes or [])],
            "reasons": [str(r) for r in (reasons or [])],
            "spans": list(spans or []),
            "raw_text": raw[:MAX_RAW_CHARS],       # 原文留底（唯一不可改写的字段）
            "clean_text": "" if clean_text is None else str(clean_text),
            "raw_chars": len(raw),
            "raw_truncated": bool(truncated),
            "status": ST_QUARANTINED,
            "note": "",
            "stage": 0,
            "next_review_at": self._next_review_at(t, 0),
            "revisions": [],                        # 复审/放行/驳回的历史，只追加
            "meta": dict(meta or {}),
            "version": 1,
            "kept": "原文留底：raw_text 写下来以后永不改写（复审只改 status/note）",
        }
        try:
            # 用 "x"（独占创建）：文件已存在就直接失败，绝不覆盖 —— 这是"只新增"的代码级保证。
            os.makedirs(self.root, exist_ok=True)
            with open(path, "x", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=1)
        except FileExistsError:
            # 极端并发下真的撞上了：换编号重试一次（宁可多一个文件，不可覆盖）
            entry["qid"] = self._new_qid()
            with self._lock:
                path = self._path_of(entry["qid"])
            try:
                with open(path, "x", encoding="utf-8") as f:
                    json.dump(entry, f, ensure_ascii=False, indent=1)
            except Exception as e:      # noqa: silent-ok — 写不上也要让主流程继续（后面有索引兜底）
                logger.warning("隔离条目写入失败(%s)：%s", entry["qid"], e)
        except Exception as e:      # noqa: silent-ok — 磁盘满/权限问题不许炸掉筛查
            logger.warning("隔离条目写入失败(%s)：%s", entry["qid"], e)
        self._append_index({
            "ts": round(t, 3), "event": "put", "qid": entry["qid"], "url": entry["url"],
            "domain": entry["domain"], "classes": entry["classes"], "reasons": entry["reasons"],
            "chars": entry["raw_chars"], "status": entry["status"],
            "next_review_at": entry["next_review_at"], "spans": len(entry["spans"]),
        })
        logger.info("隔离区收进 %s（%s）｜原因：%s", entry["qid"], entry["domain"],
                    "；".join(entry["reasons"][:2]) or "未给原因")
        return entry["qid"]

    def mark(self, qid, status, note=""):
        """改条目状态（复审/放行/驳回）。返回改完的条目（读不到就返回 {}）。

        **只改 status/note/revisions，raw_text 一个字符都不动**：
        这是"隔离区不删东西"的具体落点 —— 状态是元数据，原文是证物，两者分开。
        为什么把旧状态推进 revisions 而不是丢掉：复审的价值在于"能回溯"，
        只看得到当前状态的历史等于没有历史。
        去掉 revisions → 用户问"这条是谁放行的/什么时候放行的"会答不出来。
        """
        st = str(status or "").strip()
        if st not in _STATUSES:
            st = ST_REVIEWED
        rec = self.get(qid, with_text=True)
        if not rec:
            logger.warning("隔离区 mark：找不到条目 %s", qid)
            return {}
        old = str(rec.get("status") or "")
        try:
            stage = int(rec.get("stage") or 0) + (0 if st in _CLOSED else 1)
        except Exception:      # noqa: silent-ok — stage 坏掉就从头算
            stage = 0
        rec["status"] = st
        rec["note"] = str(note or "")
        rec["stage"] = stage
        rec["next_review_at"] = None if st in _CLOSED else self._next_review_at(rec.get("ts"), stage)
        revs = rec.get("revisions")
        if not isinstance(revs, list):
            revs = []
        revs.append({"at": round(_now(), 3), "from": old, "to": st,
                     "note": str(note or ""), "stage": stage})
        rec["revisions"] = revs
        rec["updated"] = round(_now(), 3)
        try:
            with open(self._path_of(qid), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
        except Exception as e:      # noqa: silent-ok — 状态改不上时索引仍然记一笔，人工可查
            logger.warning("隔离条目状态写入失败(%s)：%s", qid, e)
        # 注意 mark 行用的是 `at` 而不是 `ts`：`ts` 是"入库时间"，是这条污染证的出生时间，
        # 汇总（list/stats/复审）全靠它。mark 行若也写 ts，合并时就会把入库时间顶掉，
        # "这条隔离多久了"和 days 过滤会全部算错。
        self._append_index({"at": round(_now(), 3), "event": "mark", "qid": self._safe_qid(rec),
                            "status": st, "note": str(note or ""), "from": old,
                            "next_review_at": rec.get("next_review_at")})
        return rec

    @staticmethod
    def _safe_qid(rec):
        return str((rec or {}).get("qid") or "")

    # ------------------------------------------------------------ 读取
    def get(self, qid, with_text=True):
        """按编号取条目（含原文）。读不到返回 {}。

        `with_text=False` 时把 raw_text/clean_text 摘掉（面板列表只要元信息，
        带全文会让一次列表响应变成几十 MB）。
        """
        p = self._path_of(qid)
        rec = _load_json(p, None)
        if not isinstance(rec, dict):
            return {}
        rec.setdefault("qid", _safe_name(qid))
        if not with_text:
            rec.pop("raw_text", None)
            rec.pop("clean_text", None)
        return rec

    def list(self, days=None):
        """列出隔离条目（按入库时间倒序）。`days` 只保留最近几天。

        为什么从索引读、而不是逐个打开条目文件：条目文件里带着原文（可能几十 KB 一条），
        列一次目录就要把几十 MB 读进内存；索引只记元信息，扫它便宜得多。
        为什么最后按 qid 去重取"最后一条状态"：索引是**动作流水**（put/mark 各一行），
        同一条会被记多次（改状态也记），流水本身不能直接当"当前状态"用。
        去掉去重 → 列表里同一条会出现好几次，统计数字全部翻倍。
        """
        recs = _read_lines(self.index_path)
        since = (_now() - float(days) * 86400.0) if days else None
        latest = {}
        for r in recs:
            qid = str(r.get("qid") or "")
            if not qid:
                continue
            merged = latest.setdefault(qid, {"qid": qid})
            for k, v in r.items():
                if k == "next_review_at":
                    # 这个字段**必须**认 None：None 的意思是"不再安排复审"（终态），
                    # 按"空值不覆盖"处理的话，已放行的条目会一直赖在复审清单里。
                    merged[k] = v
                elif v not in (None, "", [], {}):
                    merged[k] = v
        out = []
        for qid, r in latest.items():
            try:
                ts = float(r.get("ts") or 0)
            except Exception:      # noqa: silent-ok — ts 坏掉就当作最老的一条（仍然列出来）
                ts = 0.0
            if since is not None and ts < since:
                continue
            r["ts"] = ts
            out.append(r)
        out.sort(key=lambda x: (-float(x.get("ts") or 0), str(x.get("qid") or "")))
        return out

    def due_review(self, now=None):
        """到期该复审的条目（3/7/30 天节奏）。返回 list[dict]。

        为什么返回"到期清单"而不是自己动手改状态：复审的**决定**（放行还是继续隔离）
        属于策略层（防火墙/用户），隔离区只负责"谁到期了"。
        两件事混在一起，自测就没法单独验证"3 天到了会不会提醒"。
        """
        t = _now() if now is None else float(now)
        out = []
        for r in self.list():
            if str(r.get("status") or "") in _CLOSED:
                continue
            due = r.get("next_review_at")
            try:
                due_f = float(due) if due is not None else None
            except Exception:      # noqa: silent-ok — 坏掉的时间戳按"没安排复审"处理
                due_f = None
            if due_f is None or due_f > t:
                continue
            try:
                stage = int(r.get("stage") or 0)
            except Exception:      # noqa: silent-ok — 同上
                stage = 0
            item = dict(r)
            item["due_at"] = due_f
            item["overdue_s"] = round(t - due_f, 1)
            item["stage_days"] = REVIEW_DAYS[stage] if stage < len(REVIEW_DAYS) else REVIEW_DAYS[-1]
            item["path"] = self._path_of(r.get("qid"))
            out.append(item)
        out.sort(key=lambda x: float(x.get("due_at") or 0))
        return out

    def files(self):
        """隔离区目录里的文件名集合（排序后的 list）。

        为什么要有这个方法（而不是让调用方自己 listdir）：
        红线回归测试要断言"跑完一遍，文件只多不少"，需要一个**稳定口径**的
        "目录里有什么"。名字集合是最不容易出歧义的口径（比大小、比 mtime 都稳）。
        """
        try:
            return sorted(os.listdir(self.root))
        except Exception:      # noqa: silent-ok — 目录不存在等价于"空"
            return []

    def stats(self):
        "「」隔离区体检数字：多少条、各状态几条、待复审几条、按污染类型分布。「」"
        items = self.list()
        by_status, by_class = {}, {}
        for r in items:
            st = str(r.get("status") or "")
            by_status[st] = by_status.get(st, 0) + 1
            for c in (r.get("classes") or []):
                by_class[str(c)] = by_class.get(str(c), 0) + 1
        return {"total": len(items), "by_status": by_status, "by_class": by_class,
                "due": len(self.due_review()), "root": self.root,
                "index_path": self.index_path, "files": len(self.files())}

    def __repr__(self):
        return "<Quarantine root=%s items=%d>" % (self.root, len(self.list()))


__all__ = ["Quarantine", "QUARANTINE_DIR", "WORLD_DIR", "REVIEW_DAYS", "MAX_RAW_CHARS",
           "ST_QUARANTINED", "ST_REVIEWED", "ST_RELEASED", "ST_REJECTED"]
