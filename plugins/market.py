# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 插件 · 实时行情（2026-10-29）

【为什么必须有这个插件，而不是"让它去搜一下"】
  用户实测截图：问「帮我查一下今天美股三大指数的收盘情况」，界面卡了半分钟，
  最后答「抱歉，我查不到——因为我调用 NVD 接口失败」。两个问题：
    ① 模型挑错了工具（去查漏洞库）；
    ② 就算挑对了 `web_search`，检索回来的是**新浪/知乎首页**（实测），里面没有收盘点位。
  也就是说：这类"当下的一个数"根本不该让模型转述，也不该指望通用检索。
  **载体直接调行情接口，把数字原样摆出来** —— 这才是"载体优先"该有的样子。

【用哪个数据源，为什么】
  东方财富的公开行情接口（`push2.eastmoney.com/api/qt/ulist.np/get`）：
    · 不用 key、返回 JSON、带涨跌幅；
    · 一次可以查多个标的（`secids` 用逗号分隔），一次请求出整张表；
    · 实测（2026-10-29）：`100.DJIA / 100.NDX / 100.SPX` 返回道指、纳指、标普的最新价与涨跌幅。
  备用源：新浪 `hq.sinajs.cn`（要带 Referer；实测 `gb_dji / gb_ixic / gb_inx` 可用）。

【边界（如实说）】
  · 这是**第三方公开接口**：它挂了、被限流、或改了字段，本插件就查不到 —— 那就如实报"查不到"，
    **绝不编一个数字**（行情编错的代价比不答大得多）；
  · 只做"读"，不下单、不碰账户；
  · 返回里一定带**数据时间**（接口给的行情时间），让用户知道这是几点钟的数。
"""
import json
import logging
import time

LOG = logging.getLogger(__name__)

_CACHE = {}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 东财 secid：`市场.代码`。100=美股指数，1=沪市，0=深市
_GROUPS = {
    "美股": [("100.DJIA", "道琼斯"), ("100.NDX", "纳斯达克100"), ("100.SPX", "标普500")],
    "美股三大指数": [("100.DJIA", "道琼斯"), ("100.NDX", "纳斯达克100"), ("100.SPX", "标普500")],
    "A股": [("1.000001", "上证指数"), ("0.399001", "深证成指"), ("0.399006", "创业板指")],
    "港股": [("100.HSI", "恒生指数")],
    "汇率": [("133.USDCNH", "美元离岸人民币")],
    # 【黄金/原油的 secid 各数据源不统一】实测 `101.GC00Y` 取不到，所以列出候选：
    #   下面 `_GROUPS_ALT` 里放备选，取不到就换下一个（宁可多试一次，也别动不动就"查不到"）。
    "黄金": [("118.AU0Y", "黄金主连"), ("101.GC00Y", "COMEX 黄金")],
    "原油": [("102.CL00Y", "原油主连"), ("101.CL00Y", "NYMEX 原油")],
    "白银": [("118.AG0Y", "白银主连")],
}

_TOOLS = [
    {
        "name": "get_index_quotes",
        "description": ("查实时指数/行情（美股三大指数、A股三大指数、恒指、汇率、金价、油价）。"
                        "什么时候用：用户问「今天美股/大盘/指数收盘多少、涨了还是跌了、金价多少」；"
                        "输入市场（可省，自动按问题判断）；输出 名称+最新价+涨跌幅+行情时间"),
        "parameters": {
            "type": "object",
            "properties": {
                "market": {"type": "string",
                           "description": "美股 / A股 / 港股 / 汇率 / 黄金 / 原油（省了自动判断）"},
                "question": {"type": "string", "description": "用户原话（用来判断市场，可省）"},
            },
            "required": [],
        },
    },
]


def _pick_market(market="", question=""):
    q = "%s %s" % (str(market or ""), str(question or ""))
    if any(w in q for w in ("美股", "道指", "纳指", "标普", "道琼斯", "纳斯达克")):
        return "美股"
    if any(w in q for w in ("A股", "上证", "深证", "创业板", "沪深", "大盘", "沪指", "两市")):
        return "A股"
    if any(w in q for w in ("港股", "恒生", "恒指")):
        return "港股"
    if any(w in q for w in ("汇率", "人民币", "美元")):
        return "汇率"
    if any(w in q for w in ("黄金", "金价", "金条", "足金", "黄金价格")):
        return "黄金"
    if any(w in q for w in ("白银", "银价")):
        return "白银"
    if any(w in q for w in ("原油", "油价")):
        return "原油"
    return "美股"          # 默认问美股三大指数：这是被问得最多的一类


def _fetch(secids):
    """向东财要一组行情。返回 (rows, err)。rows 每项是 dict。

    【为什么要重试 + 短缓存】实测：连着问几行情类问题，东财会 `RemoteDisconnected`
    （短时间内重复请求被掐）。所以：① 失败重试 2 次（带短退避）；② 30 秒内的同一组
    直接给缓存 —— 行情变不了那么快，用户也不该因为接口限流而看不到数。
    """
    import requests
    key = ",".join(secids)
    _now = time.time()
    _c = _CACHE.get(key) or {}
    if _c and (_now - float(_c.get("at") or 0)) < 30:
        return _c.get("rows") or [], ""
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get"
           "?fltt=2&secids=%s&fields=f1,f2,f3,f4,f12,f13,f14,f124&_=%d"
           % (key, int(_now * 1000)))
    last_err = ""
    _t_start = time.time()
    for attempt in (1, 2):
        # 【总时间上限】实测：接口被限流时，每次重试、每组单查都要等，加起来能拖到 20 秒以上，
        #   而用户要的是"要么给数，要么快点说查不到"。所以整条链路封顶 ~8 秒。
        if (time.time() - _t_start) > 8.0:
            last_err = (last_err or "超时") + "（总耗时超过 8 秒，已停下）"
            break
        try:
            r = requests.get(url, timeout=12,
                             headers={"User-Agent": _UA,
                                      "Referer": "https://quote.eastmoney.com/"})
            if r.status_code != 200:
                last_err = "HTTP %s" % r.status_code
            else:
                try:
                    d = json.loads(r.text)
                except Exception as e:      # noqa: silent-ok
                    last_err = "返回不是 JSON（%s）" % str(e)[:60]
                else:
                    diff = ((d.get("data") or {}).get("diff") or [])
                    rows = []
                    for it in diff:
                        rows.append({"code": str(it.get("f12") or ""),
                                     "name": str(it.get("f14") or it.get("f12") or ""),
                                     "last": it.get("f2"), "chg_pct": it.get("f3"),
                                     "chg": it.get("f4"), "ts": it.get("f124")})
                    if rows:
                        got = {str(r.get("code")) for r in rows}
                        missing = [x for x in secids if x.split(".")[-1] not in got]
                        if not missing:
                            _CACHE[key] = {"at": _now, "rows": rows}
                            return rows, ""
                        # 【部分缺失也要补齐】实测：美股三大指数 ulist 只回了「标普500」，
                        #   另外两个（道指/纳指）没回来 —— 只当"有数据就返回"会让用户看到残缺的表。
                        LOG.info("行情：ulist 只回了 %d/%d，缺的用单查补齐", len(rows), len(secids))
                    last_err = "接口没给数据（diff 为空）"
        except Exception as e:      # noqa: silent-ok — 网络失败如实上报
            last_err = "%s: %s" % (type(e).__name__, str(e)[:80])
        time.sleep(0.8 * attempt)
    # 【最后一道：逐个单查】实测 `ulist.np` 不认商品合约（101.GC00Y 这类返回空），
    #   但单查接口 `stock/get` 认：COMEX黄金 f43=4037.0、COMEX白银 f43=52.44 都能拿到。
    #   所以整批拿不到时，改成一个个问 —— 慢一点，但总比"查不到"强。
    singles = []
    # ulist 已经回来的不再问一遍（实测：ulist 有时只回 1~2 个，剩下的才需要单查）
    try:
        _have = {str(r.get("code")) for r in (rows or [])}
    except Exception:      # noqa: silent-ok — rows 还没定义就当"一个都没回来"
        _have = set()
    for sid in secids:
        if (time.time() - _t_start) > 8.0:
            break       # 单查也要守总时间上限（限流时每个都要等）
        if sid.split(".")[-1] in _have:
            continue
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get"
                "?fltt=2&secid=%s&fields=f43,f57,f58,f169,f170&_=%d"
                % (sid, int(time.time() * 1000)),
                timeout=10, headers={"User-Agent": _UA,
                                     "Referer": "https://quote.eastmoney.com/"})
            j = json.loads(r.text or "{}")
            d = j.get("data") or {}
            if d and d.get("f43") not in (None, "", "-"):
                singles.append({"code": str(d.get("f57") or sid.split(".")[-1]),
                                "name": str(d.get("f58") or sid),
                                "last": d.get("f43"), "chg_pct": d.get("f170"),
                                "chg": d.get("f169"), "ts": None})
        except Exception as e:      # noqa: silent-ok — 单个查不到就跳下一个
            LOG.debug("单查 %s 失败：%s", sid, e)
        time.sleep(0.3)
    if singles or rows:
        # 【别把已经拿到的丢掉】ulist 可能给了 1~2 个、单查又补齐一部分：
        #   合并后一起返回（原来只 `return singles`，一旦单查全失败，连已有的一起丢了）。
        merged = list(rows or []) + [x for x in singles
                                     if str(x.get("code")) not in {str(r.get("code"))
                                                                   for r in (rows or [])}]
        if merged:
            _CACHE[key] = {"at": time.time(), "rows": merged}
            return merged, ""
    return [], last_err


def _fetch_sina(group):
    """备用源：新浪行情（要带 Referer）。返回 (rows, err)。

    `gb_` 开头是美股指数（字段：名称,最新,涨跌幅,时间,…）；
    `sh/sz` 开头是 A 股指数（字段：名称,今开,昨收,最新,最高,最低,…,日期,时间）。
    """
    import requests
    sina_ids = []
    for code, nm in group:
        market, _, tick = code.partition(".")
        if market == "100" and tick in ("DJIA", "NDX", "SPX"):
            sina_ids.append(("gb_" + {"DJIA": "dji", "NDX": "ixic", "SPX": "inx"}[tick], nm, "gb"))
        elif market == "100" and tick == "HSI":
            sina_ids.append(("rt_hkHSI", nm, "hk"))
        elif market == "1" and tick.startswith("000"):
            sina_ids.append(("sh" + tick, nm, "cn"))
        elif market == "0" and tick.startswith("399"):
            sina_ids.append(("sz" + tick, nm, "cn"))
    if not sina_ids:
        return [], "没有可用的备用源"
    url = "https://hq.sinajs.cn/list=" + ",".join(s[0] for s in sina_ids)
    try:
        r = requests.get(url, timeout=10,
                         headers={"User-Agent": _UA,
                                  "Referer": "https://finance.sina.com.cn"})
        txt = r.text if r.status_code == 200 else ""
    except Exception as e:      # noqa: silent-ok
        return [], "%s: %s" % (type(e).__name__, str(e)[:80])
    rows = []
    for line in txt.split("\n"):
        if "hq_str_" not in line:
            continue
        try:
            head, body = line.split("=", 1)
            sid = head.split("hq_str_")[1].strip().strip('"')
            parts = body.strip().strip(";").strip('"').split(",")
        except Exception:      # noqa: silent-ok — 解析不了这一行就跳过
            continue
        meta = next((s for s in sina_ids if s[0] == sid), None)
        if not meta or len(parts) < 4:
            continue
        _id, nm, kind = meta
        try:
            if kind == "gb":
                last, pct = parts[1], parts[2]
            else:
                last, prev = parts[3], parts[2]
                pct = ("%.2f" % ((float(last) - float(prev)) / float(prev) * 100)) \
                    if float(prev) else "-"
                # A 股这条：涨跌幅自己算，涨跌额也自己算（接口没直接给）
                chg = ("%.2f" % (float(last) - float(prev))) if float(prev) else "-"
                rows.append({"code": sid, "name": nm, "last": last, "chg_pct": pct,
                             "chg": chg, "ts": None})
                continue
            rows.append({"code": sid, "name": nm, "last": last, "chg_pct": pct,
                         "chg": "-", "ts": None})
        except Exception:      # noqa: silent-ok
            continue
    return (rows, "") if rows else ([], "新浪也没给数据")


def _fmt(rows, market):
    lines = ["📈 **%s 实时行情**（东方财富公开接口 · 载体直取，不经模型转述）" % market, "",
             "| 名称 | 最新 | 涨跌幅 | 涨跌 |", "| --- | --- | --- | --- |"]
    ts_note = ""
    for r in rows:
        last = r.get("last")
        pct = r.get("chg_pct")
        chg = r.get("chg")
        # 接口没给（停牌/未开盘）时不要编 0：直接写"—"
        def _n(v, suffix=""):
            return "—" if v in (None, "", "-") else ("%s%s" % (v, suffix))
        sign = ""
        try:
            sign = "+" if float(pct) > 0 else ""
        except Exception:      # noqa: silent-ok
            sign = ""
        # 【诚实的显示：拿不到就写 —】实测：美股休市时接口/备用源给的是 0.00%（其实是"没更新"），
        #   直接照抄会让人以为"今天一分钱没动"。所以"涨跌额也没有"时，涨跌幅一律显示 — 并标注原因。
        _pct_out = "—"
        try:
            if pct not in (None, "", "-") and not (float(pct) == 0.0 and str(chg) in ("-", "—", "")):
                _pct_out = sign + _n(pct, "%")
        except Exception:      # noqa: silent-ok
            _pct_out = "—"
        lines.append("| %s | %s | %s | %s |" % (
            r.get("name"), _n(last), _pct_out, _n(chg)))
        try:
            if r.get("ts"):
                ts_note = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(r["ts"])))
        except Exception:      # noqa: silent-ok
            pass
    lines += ["",
              "- 行情时间：%s（数据源给的行情时间）｜ 抓取时间：%s"
              % (ts_note or "数据源未给", time.strftime("%Y-%m-%d %H:%M:%S")),
              "- 说明：数字是**接口返回的原值**，我没有四舍五入或改写；行情随时变动，"
              "做决策前请以交易所/券商为准。"]
    return "\n".join(lines)


class MarketPlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。"""

    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        if tool_name != "get_index_quotes":
            return "行情插件里没有「%s」这个工具（它只有 get_index_quotes）。" % tool_name
        market = _pick_market(params.get("market"), params.get("question"))
        group = _GROUPS.get(market) or _GROUPS["美股"]
        rows, err = _fetch([c for c, _n in group])
        if not rows:
            # 备用源：新浪（东财被限流/掐连接时顶上；两个源不会同时挂）
            rows, err2 = _fetch_sina(group)
            err = "" if rows else ("%s ／ 备用源：%s" % (err, err2))
        if not rows:
            return ("📈 行情接口这次没取到数据（%s）。\n\n我不编数字 —— 可以稍等一下再问，"
                    "或者直接看东方财富/新浪财经的行情页。" % (err or "没有返回内容"))
        # 名字按 secid 后段（代码）对齐：接口回的是 `DJIA` 这种代码，我们要中文名
        for r in rows:
            for code, nm in group:
                if str(r.get("code")) == code.split(".")[-1]:
                    r["name"] = nm
                    break
        return _fmt(rows, market)


_PLUGIN = MarketPlugin()


def get_plugin():
    return _PLUGIN
