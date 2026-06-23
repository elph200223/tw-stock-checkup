#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
階段 2:單檔完整分析 → Markdown 報告

對一檔股票跑:健檢五問題 + 估值 + 月營收趨勢 + 黃金配對,
每個關鍵數字都帶核實狀態(雙來源交叉),報告開頭有「資料來源/抓取時間/核實摘要」。

最高原則:抓不到/對不上 → 標「存疑、需補、未評等」,絕不硬填、不瞎猜。
判讀用語:講「反映什麼/風險在哪/觀察什麼」,不講買賣。

用法:python3 analyze.py 2330        # 印出報告
      python3 analyze.py 2330 > 2330.md
"""

import sys
from common import (fetch, to_float, roc_to_ad, cross, datum, now_tpe,
                    VERIFIED, MINOR, UNVER, OFFICIAL1, NA, STATUS_LABEL)

MARKET = {"2330": "TWSE", "2308": "TWSE", "4958": "TWSE", "8996": "TWSE",
          "6451": "TWSE", "3081": "TPEx", "3363": "TPEx"}
NAME = {"2330": "台積電", "2308": "台達電", "4958": "臻鼎", "8996": "高力",
        "6451": "訊芯", "3081": "聯亞", "3363": "上詮"}

Q = "千元 → 換算需 ×1000"  # 財報數字單位:千元


# ───────────────── 抓資料(上市;上櫃於階段三補) ─────────────────
def load(code, market):
    raw = {}
    if market == "TWSE":
        raw["income"] = pick(fetch("https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci", "綜合損益表"), "公司代號", code)
        raw["balance"] = pick(fetch("https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci", "資產負債表"), "公司代號", code)
        raw["bwibbu"] = pick(fetch("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL", "PE/PB"), "Code", code)
        raw["basic"] = pick(fetch("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "個股基本"), "公司代號", code)
        raw["price_daily"] = pick(fetch("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", "每日收盤"), "Code", code)
        raw["rev"] = pick(fetch("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", "月營收"), "公司代號", code)
    else:
        raw["income"] = pick(fetch("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O", "綜合損益表"), "SecuritiesCompanyCode", code)
        raw["balance"] = pick(fetch("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O", "資產負債表"), "SecuritiesCompanyCode", code)
        raw["bwibbu"] = pick(fetch("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", "PE/PB"), "SecuritiesCompanyCode", code)
        raw["basic"] = pick(fetch("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "個股基本"), "SecuritiesCompanyCode", code)
        raw["price_daily"] = pick(fetch("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", "每日收盤"), "SecuritiesCompanyCode", code)
        raw["rev"] = pick(fetch("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", "月營收"), "公司代號", code)
    ex = "tse" if market == "TWSE" else "otc"
    raw["mis"] = fetch(f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex}_{code}.tw&json=1", "MIS即時")
    return raw


def pick(data, key, code):
    if not data:
        return None
    for r in data:
        if r.get(key) == code:
            return r
    return None


def g(rec, *keys):
    """從一筆資料取第一個有值的欄位(容忍欄位名差異)。"""
    if not rec:
        return None
    for k in keys:
        if k in rec:
            v = to_float(rec[k])
            if v is not None:
                return v
    return None


# ───────────────── 計算核心 ─────────────────
def analyze(code):
    market = MARKET.get(code, "TWSE")
    raw = load(code, market)
    inc, bal, bw, basic = raw["income"], raw["balance"], raw["bwibbu"], raw["basic"]
    R = {"code": code, "name": NAME.get(code, code), "market": market, "time": now_tpe()}

    # 期別
    yr = (inc or {}).get("年度") or (inc or {}).get("Year")
    qq = (inc or {}).get("季別")
    R["period"] = f"{int(yr)+1911} Q{qq}" if yr else "—"

    # 股數(實收資本額 ÷ 面額,或上櫃 IssueShares)
    shares = None
    if market == "TWSE":
        cap = g(basic, "實收資本額")
        par = to_float(str((basic or {}).get("普通股每股面額", "")).replace("新台幣", "").replace("元", "")) or 10.0
        shares = cap / par if cap else None
    else:
        shares = g(basic, "IssueShares")
        if not shares:
            cap = g(basic, "Paidin.Capital.NTDollars")
            par = to_float(str((basic or {}).get("ParValueOfCommonStock", "")).replace("新台幣", "").replace("元", "")) or 10.0
            shares = cap / par if cap else None
    R["shares"] = shares

    # ── 股價:STOCK_DAY/TPEx ↔ MIS,並取最新價 ──
    pd_close = g(raw["price_daily"], "ClosingPrice", "Close")
    pd_date = roc_to_ad((raw["price_daily"] or {}).get("Date"))
    mis = (raw["mis"] or {}).get("msgArray", [{}])
    mis = mis[0] if mis else {}
    mis_z, mis_y = to_float(mis.get("z")), to_float(mis.get("y"))
    import datetime as _dt
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    if pd_date == today:
        R["price"] = cross(pd_close, f"每日收盤檔({pd_date})", mis_z, "MIS今日", "股價")
        R["latest_price"] = None
    else:
        R["price"] = cross(pd_close, f"每日收盤檔({pd_date})", mis_y, f"MIS昨收(對齊{pd_date})", "股價")
        R["latest_price"] = {"date": today, "price": mis_z} if mis_z else None
    price = R["price"]["value"]

    # ── 三率(官方損益表;以「毛利=營收−成本」內部交叉)──
    rev = g(inc, "營業收入")
    cogs = g(inc, "營業成本")
    gross = g(inc, "營業毛利（毛損）", "營業毛利（毛損）淨額", "營業毛利")
    op = g(inc, "營業利益（損失）", "營業利益")
    net = g(inc, "本期淨利（淨損）", "本期淨利")
    net_parent = g(inc, "淨利（淨損）歸屬於母公司業主")
    nonop = g(inc, "營業外收入及支出")
    pretax = g(inc, "稅前淨利（淨損）", "稅前淨利")
    eps_rep = g(inc, "基本每股盈餘（元）", "基本每股盈餘")

    gross_chk = (rev - cogs) if (rev is not None and cogs is not None) else None
    R["gross"] = cross(gross, "損益表 營業毛利", gross_chk, "營收−成本", "毛利")
    R["gross_margin"] = pctval(gross, rev)
    R["op_margin"] = pctval(op, rev)
    R["net_margin"] = pctval(net, rev)
    R["rev_q"] = datum(rev, "損益表 營業收入(單季)")
    R["nonop"] = datum(nonop, "損益表 營業外收入及支出")
    R["pretax"] = datum(pretax, "損益表 稅前淨利")
    R["nonop_ratio"] = (nonop / pretax * 100) if (nonop is not None and pretax) else None

    # ── EPS:申報 ↔ 歸屬母公司淨利÷股數 ──
    eps_calc = (net_parent * 1000 / shares) if (net_parent is not None and shares) else None
    R["eps"] = cross(eps_rep, "官方申報基本EPS", eps_calc, "歸屬母公司淨利÷股數", "EPS")

    # ── 每股淨值:官方每股參考淨值 ↔ 歸屬母公司權益÷股數;PB:官方 ↔ price/淨值 ──
    bvps_off = g(bal, "每股參考淨值")
    eq_parent = g(bal, "歸屬於母公司業主之權益合計")
    bvps_calc = (eq_parent * 1000 / shares) if (eq_parent is not None and shares) else None
    R["bvps"] = cross(bvps_off, "官方每股參考淨值", bvps_calc, "歸屬母公司權益÷股數", "每股淨值")
    bvps = R["bvps"]["value"]

    pb_off = g(bw, "PBratio", "PriceBookRatio")
    pb_calc = (price / bvps) if (price and bvps) else None
    R["pb"] = cross(pb_off, "官方PB(BWIBBU)", pb_calc, "股價÷每股淨值", "PB")

    # ── PE:官方 BWIBBU(TTM)為主;自我交叉需累積四季 ──
    pe_off = g(bw, "PEratio", "PriceEarningRatio")
    R["pe"] = datum(pe_off, "官方PE(BWIBBU,近四季TTM)", OFFICIAL1,
                    "第二來源(自算PE=股價÷近四季EPS)需累積四季EPS後才能交叉;目前先採官方值。")
    R["pe_implied_ttm_eps"] = (price / pe_off) if (price and pe_off) else None

    # ── 負債比/流動比(官方資負表;速動比需存貨,彙總表無)──
    asset = g(bal, "資產總額")
    liab = g(bal, "負債總額")
    ca = g(bal, "流動資產")
    cl = g(bal, "流動負債")
    R["debt_ratio"] = pctval(liab, asset)
    R["current_ratio"] = (ca / cl) if (ca and cl) else None
    R["quick_note"] = "速動比需『存貨』,官方彙總財報未拆出 → 需人工查 MOPS 或手動補(半自動)。"
    R["cash_note"] = "營業活動現金流:官方 OpenAPI 無乾淨端點 → 需人工查 MOPS 或手動補(半自動)。"

    # ── 月營收(最新月 + YoY 自我交叉)──
    rv = raw["rev"]
    if rv:
        m_rev = to_float(rv.get("營業收入-當月營收"))
        m_ly = to_float(rv.get("營業收入-去年當月營收"))
        yoy_api = to_float(rv.get("營業收入-去年同月增減(%)"))
        yoy_calc = ((m_rev / m_ly - 1) * 100) if (m_rev and m_ly) else None
        R["rev_month"] = roc_to_ad(rv.get("資料年月"))
        R["rev_value"] = m_rev / 1000 if m_rev else None  # 百萬
        R["rev_yoy"] = cross(yoy_api, "官方YoY", yoy_calc, "自算(當月÷去年同月−1)", "月營收YoY")
        R["rev_mom"] = to_float(rv.get("營業收入-上月比較增減(%)"))
    else:
        R["rev_month"] = None

    return R


def pctval(num, den):
    return (num / den * 100) if (num is not None and den) else None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:python3 analyze.py <股票代號>   例:python3 analyze.py 2330")
        sys.exit(1)
    from report import render
    code = sys.argv[1].strip()
    print(f"分析 {code}(抓取官方資料中,遵守頻率限制)…", file=sys.stderr)
    R = analyze(code)
    print(render(R))
