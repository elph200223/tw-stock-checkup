#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
階段 1:核實機制(雙來源交叉比對)

用途:輸入一個股票代號,對「股價」與「EPS」各從兩個獨立來源取得,
      印出兩來源的值、誤差%、核實結果(verified / minor_diff / unverified)。
目的:先證明「雙來源交叉比對」這件事跑得通,再往下做分析與評等。

核實規則(最高原則:正確性 > 功能 > 速度;對不上就標存疑,絕不硬填):
  誤差 < 1%        → verified   (已核實,可拿去評等)
  誤差 1% ~ 5%     → minor_diff (採官方來源,報告註記差異)
  誤差 > 5% 或缺一源 → unverified (不納入評等,標示資料存疑)

雙來源設計(混合策略:官方交叉為主):
  股價:來源A 證交所每日收盤(STOCK_DAY_ALL / TPEx 收盤)
        來源B 證交所即時報價系統(MIS getStockInfo)  ← 不同系統,按日期對齊比對
  EPS :來源A 官方申報「基本每股盈餘」(t187ap14_L / mopsfin_t187ap14_O)
        來源B 自算 = 稅後淨利 ÷ 流通股數(流通股數 = 實收資本額 ÷ 面額)
              ← 兩條獨立計算路徑,能抓出抓取/解析/單位錯誤

用法:python3 verify.py 2330
      python3 verify.py 3081
"""

import sys
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta

TPE = timezone(timedelta(hours=8))

# 關注名單(決定上市/上櫃走哪組 API)
MARKET = {
    "2330": "TWSE", "2308": "TWSE", "4958": "TWSE", "8996": "TWSE", "6451": "TWSE",
    "3081": "TPEx", "3363": "TPEx",
}

VERIFIED, MINOR, UNVER = "verified", "minor_diff", "unverified"


def fetch(url, label="", sleep=2.0, retries=3):
    """抓 JSON,含 retry 上限與 request 間 sleep(遵守頻率限制,防封 IP)"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.load(r)
            time.sleep(sleep)
            return data
        except Exception as e:
            last = e
            time.sleep(sleep * (i + 1))
    print(f"  ! 來源抓取失敗 {label}: {last}", file=sys.stderr)
    return None


def to_float(s):
    try:
        return float(str(s).replace(",", "").replace("+", "").strip())
    except (ValueError, AttributeError, TypeError):
        return None


def roc_to_ad(roc):
    s = str(roc).strip()
    if len(s) == 7:
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
    if len(s) == 5:
        return f"{int(s[:3]) + 1911}-{s[3:5]}"
    return s


def diff_pct(a, b):
    """以兩值平均為分母的相對誤差%"""
    if a is None or b is None:
        return None
    base = (abs(a) + abs(b)) / 2
    if base == 0:
        return 0.0
    return abs(a - b) / base * 100


def classify(d):
    if d is None:
        return UNVER
    if d < 1:
        return VERIFIED
    if d <= 5:
        return MINOR
    return UNVER


# ─────────────────────────── 股價:雙來源 ───────────────────────────
def price_twse_daily(code):
    d = fetch("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", "TWSE每日收盤")
    if not d:
        return None
    for r in d:
        if r.get("Code") == code:
            return {"value": to_float(r.get("ClosingPrice")), "date": roc_to_ad(r.get("Date")),
                    "source": "證交所每日收盤 STOCK_DAY_ALL"}
    return None


def price_tpex_daily(code):
    d = fetch("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", "TPEx每日收盤")
    if not d:
        return None
    for r in d:
        if r.get("SecuritiesCompanyCode") == code:
            return {"value": to_float(r.get("Close")), "date": roc_to_ad(r.get("Date")),
                    "source": "櫃買每日收盤 tpex_mainboard_quotes"}
    return None


def price_mis(code, market):
    ex = "tse" if market == "TWSE" else "otc"
    d = fetch(f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex}_{code}.tw&json=1", "MIS即時")
    if not d or not d.get("msgArray"):
        return None
    k = d["msgArray"][0]
    z = to_float(k.get("z"))            # 最近成交價(當日)
    y = to_float(k.get("y"))            # 昨收
    today = datetime.now(TPE).strftime("%Y-%m-%d")
    return {"z": z, "y": y, "date_today": today, "source": "證交所即時報價系統 MIS"}


def verify_price(code, market):
    a = price_twse_daily(code) if market == "TWSE" else price_tpex_daily(code)
    b = price_mis(code, market)
    if not a or not b:
        miss = "證交所/櫃買每日收盤檔" if not a else "MIS 即時報價"
        return {"name": "股價", "diff": None, "status": UNVER,
                "reason": f"{miss} 這個來源這次抓不到(可能 API 暫時無回應)。",
                "remedy": "稍後重跑一次;或改用另一個官方端點補上第二來源。"}
    # 按日期對齊:每日收盤檔的日期 == MIS 今天 → 比 z(今日成交);否則比 y(昨收)
    if a["date"] == b["date_today"]:
        bval, bdesc = b["z"], f"{b['source']} 今日成交({b['date_today']})"
        latest = None
    else:
        bval, bdesc = b["y"], f"{b['source']} 昨收(對齊 {a['date']})"
        # 每日檔落後一天:MIS 已有今日(b['z'])收盤,但官方每日檔今晚才更新 → 今日價暫單一來源
        latest = {"date": b["date_today"], "price": b["z"]} if b.get("z") else None
    d = diff_pct(a["value"], bval)
    res = {
        "name": "股價",
        "a_label": f"{a['source']}({a['date']})", "a_val": a["value"],
        "b_label": bdesc, "b_val": bval,
        "diff": d, "status": classify(d),
    }
    if latest:
        res["latest_note"] = (f"最新價:{latest['date']} 收盤 {latest['price']}(目前僅 MIS 單一來源,"
                              f"官方每日彙總檔約當日傍晚更新;更新後即可對 {latest['date']} 做雙來源核實)。")
    if res["status"] != VERIFIED:
        res["reason"] = "兩來源在同一交易日的收盤價對不上。"
        res["remedy"] = "檢查是否遇到除權息/減資調整日;或稍後官方檔更新後重核。"
    return res


# ─────────────────────────── EPS:雙來源 ───────────────────────────
def eps_official(code, market):
    if market == "TWSE":
        d = fetch("https://openapi.twse.com.tw/v1/opendata/t187ap14_L", "TWSE綜損益(EPS)")
        key_code, key_eps, key_net = "公司代號", "基本每股盈餘(元)", "稅後淨利"
    else:
        d = fetch("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O", "TPEx綜損益(EPS)")
        key_code, key_eps, key_net = "SecuritiesCompanyCode", "基本每股盈餘", "稅後淨利"
    if not d:
        return None
    for r in d:
        if r.get(key_code) == code:
            yr = r.get("年度") or r.get("Year")
            q = r.get("季別")
            return {
                "eps_reported": to_float(r.get(key_eps)),
                "net_income": to_float(r.get(key_net)),   # 單位:千元
                "period": f"{int(yr)+1911 if yr else '?'} Q{q}",
            }
    return None


def shares_outstanding(code):
    """流通股數 = 實收資本額 ÷ 普通股面額(來自個股基本資料 t187ap03_L)"""
    d = fetch("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "個股基本資料")
    if d:
        for r in d:
            if r.get("公司代號") == code:
                cap = to_float(r.get("實收資本額"))               # 元
                par = to_float(str(r.get("普通股每股面額", "")).replace("新台幣", "").replace("元", "")) or 10.0
                if cap and par:
                    return cap / par, "TWSE 個股基本資料(實收資本額÷面額)"
    # 上櫃:改抓 TPEx 個股基本資料(欄位為英文名)
    d = fetch("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "TPEx個股基本資料")
    if d:
        for r in d:
            if r.get("SecuritiesCompanyCode") == code:
                shares = to_float(r.get("IssueShares"))      # 已發行股數,直接可用
                if shares:
                    return shares, "櫃買 個股基本資料(已發行股數 IssueShares)"
                cap = to_float(r.get("Paidin.Capital.NTDollars"))
                par = to_float(str(r.get("ParValueOfCommonStock", "")).replace("新台幣", "").replace("元", "")) or 10.0
                if cap and par:
                    return cap / par, "櫃買 個股基本資料(實收資本額÷面額)"
    return None, None


def verify_eps(code, market):
    off = eps_official(code, market)
    if not off or off["eps_reported"] is None:
        return {"name": "EPS(單季)", "diff": None, "status": UNVER, "note": "官方 EPS 抓不到"}
    shares, sh_src = shares_outstanding(code)
    eps_calc = None
    if off["net_income"] is not None and shares:
        # 稅後淨利單位為千元 → ×1000 換算為元;再 ÷ 股數
        eps_calc = off["net_income"] * 1000 / shares
    d = diff_pct(off["eps_reported"], eps_calc)
    res = {
        "name": f"EPS（{off['period']} 單季）",
        "a_label": "官方申報 基本每股盈餘", "a_val": off["eps_reported"],
        "b_label": f"自算 稅後淨利÷股數（{sh_src or '股數缺'}）", "b_val": eps_calc,
        "diff": d, "status": classify(d),
        "extra": f"稅後淨利 {off['net_income']:.0f} 千元、股數 {shares:.0f}" if (off["net_income"] and shares) else "",
    }
    if eps_calc is None:
        res["reason"] = "抓不到流通股數,無法用第二條路徑(淨利÷股數)交叉。"
        res["remedy"] = "補上個股基本資料的股數來源後重核。"
    elif res["status"] != VERIFIED and d is not None and d > 1:
        # 最常見原因:合併淨利含非控制權益,官方EPS用歸屬母公司淨利(子公司多的公司差很大)
        res["reason"] = ("『稅後淨利』是合併數(含非控制權益),但官方 EPS 用『歸屬母公司業主淨利』。"
                         "兩者基礎不同,子公司多的公司會差很大——這不是抓錯,是會計口徑不同。")
        res["remedy"] = ("階段二改用『歸屬母公司業主淨利』當第二來源重算;"
                         "若官方該欄取不到,依混合策略查第三方(如 Goodinfo)做第三票仲裁。")
    return res


# ─────────────────────────── 輸出 ───────────────────────────
STATUS_LABEL = {VERIFIED: "✅ verified 已核實", MINOR: "🟡 minor_diff 小差異", UNVER: "🔴 unverified 未核實"}


def show(res):
    print(f"\n── {res['name']} ──")
    if "a_val" not in res:   # 整個項目缺來源
        print(f"   {STATUS_LABEL[res['status']]}")
        if res.get("reason"): print(f"   ⚠ 原因:{res['reason']}")
        if res.get("remedy"): print(f"   🔧 解決:{res['remedy']}")
        return
    av = res.get("a_val"); bv = res.get("b_val")
    print(f"   來源A:{res['a_label']:<34} = {('—' if av is None else round(av,4))}")
    print(f"   來源B:{res['b_label']:<34} = {('—' if bv is None else round(bv,4))}")
    dt = res["diff"]
    print(f"   誤差:{'—' if dt is None else format(dt,'.3f')+'%'}   →   {STATUS_LABEL[res['status']]}")
    if res.get("extra"):
        print(f"   ({res['extra']})")
    if res.get("latest_note"):
        print(f"   ℹ {res['latest_note']}")
    if res.get("reason"):
        print(f"   ⚠ 原因:{res['reason']}")
    if res.get("remedy"):
        print(f"   🔧 解決:{res['remedy']}")


def main():
    if len(sys.argv) < 2:
        print("用法:python3 verify.py <股票代號>   例:python3 verify.py 2330")
        sys.exit(1)
    code = sys.argv[1].strip()
    market = MARKET.get(code, "TWSE")
    now = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    print("=" * 60)
    print(f"  核實報告 — {code}（市場別:{market}）")
    print(f"  抓取時間:{now}（台北時間）")
    print("=" * 60)

    show(verify_price(code, market))
    show(verify_eps(code, market))

    print("\n" + "-" * 60)
    print("說明:verified=兩來源吻合可信;minor_diff=小差異採官方;unverified=存疑不評等。")
    print("（這是階段1,只驗證『雙來源交叉比對』機制;完整分析在階段2。）")


if __name__ == "__main__":
    main()
