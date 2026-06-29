#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台股 財報健檢 + 月營收追蹤 — 自動抓資料腳本(階段二 A)

來源(皆為官方一手資料):
  上市月營收  TWSE  https://openapi.twse.com.tw/v1/opendata/t187ap05_L
  上市收盤價  TWSE  https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
  上櫃月營收  TPEx  https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O
  上櫃收盤價  TPEx  https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes

設計原則(對應「如何保證正確」四道防線):
  1. 官方一手來源,上市接 TWSE、上櫃接 TPEx。
  2. 交叉驗證:API 自帶 YoY 與本程式自算 YoY 比對,差距 > 0.5 個百分點 → 標記 flag。
  3. 合理性範圍檢查:營收非負、YoY 介於 -100%~999%、股價 > 0,超出 → 標記 flag。
  4. 來源 + 抓取時間戳記:每筆都記來源與抓取日;抓不到就留空,不用舊值亂填。

限制:一天只跑一次(TWSE 每 5 秒最多 3 request、密集查詢會被封)。
輸出:data.json(前端直接讀)。
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

TPE = timezone(timedelta(hours=8))  # 台北時間

# ── 關注名單(市場別決定要打哪個 API)──
WATCH = [
    {"code": "2330", "name": "台積電", "market": "TWSE", "tag": "溫度計"},
    {"code": "2308", "name": "台達電", "market": "TWSE"},
    {"code": "4958", "name": "臻鼎",   "market": "TWSE"},
    {"code": "8996", "name": "高力",   "market": "TWSE"},
    {"code": "6451", "name": "訊芯",   "market": "TWSE"},
    {"code": "3081", "name": "聯亞",   "market": "TPEx"},
    {"code": "3363", "name": "上詮",   "market": "TPEx"},
]

URLS = {
    "twse_rev":   "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "twse_price": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "tpex_rev":   "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
    "tpex_price": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def fetch_mis(code, market):
    """證交所即時報價系統 MIS:取最新成交價(收盤後即為當日收盤),比每日彙總檔即時。
    回傳 {close, date(YYYY-MM-DD), change};失敗回 None。"""
    import time
    ex = "tse" if market == "TWSE" else "otc"
    try:
        d = fetch(f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex}_{code}.tw&json=1")
        time.sleep(1.5)  # 限流,避免密集請求
        arr = d.get("msgArray") or []
        if not arr:
            return None
        k = arr[0]
        z = to_float(k.get("z"))   # 最近成交價
        y = to_float(k.get("y"))   # 昨收
        if z is None:
            return None
        return {"close": z, "date": roc_to_ad(k.get("d")),
                "change": (round(z - y, 4) if (z is not None and y is not None) else None)}
    except Exception:
        return None


def to_float(s):
    try:
        return float(str(s).replace(",", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        return None


def roc_to_ad(roc):
    """民國日期/年月 或 MIS 西元日期 轉 YYYY-MM-DD。
    1150618(民國)-> 2026-06-18;11505 -> 2026-05;20260629(西元8碼)-> 2026-06-29"""
    s = str(roc).strip()
    if len(s) == 8:      # 西元 YYYYMMDD(MIS)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 7:      # 民國 YYYMMDD
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
    if len(s) == 5:      # 民國 YYYMM
        return f"{int(s[:3]) + 1911}-{s[3:5]}"
    return s


def sanity_revenue(rec):
    """合理性 + 交叉驗證,回傳 flags 清單(空=乾淨)"""
    flags = []
    if rec["rev"] is None:
        flags.append("無當月營收")
        return flags
    if rec["rev"] < 0:
        flags.append("營收為負,異常")
    if rec["yoy"] is not None and not (-100 <= rec["yoy"] <= 999):
        flags.append(f"YoY {rec['yoy']:.1f}% 超出合理範圍")
    # 交叉驗證:自算 YoY vs API YoY
    if rec["rev_last_year"] and rec["rev_last_year"] > 0 and rec["yoy"] is not None:
        calc = (rec["rev"] / rec["rev_last_year"] - 1) * 100
        if abs(calc - rec["yoy"]) > 0.5:
            flags.append(f"YoY 交叉驗證不符(API {rec['yoy']:.2f}% vs 自算 {calc:.2f}%)")
    return flags


def main():
    now = datetime.now(TPE)
    fetched_at = now.strftime("%Y-%m-%d %H:%M")
    codes = {w["code"] for w in WATCH}

    raw = {}
    errors = []
    for key, url in URLS.items():
        try:
            raw[key] = fetch(url)
            print(f"  ✓ {key}: {len(raw[key])} 筆")
        except Exception as e:
            raw[key] = []
            errors.append(f"{key}: {e}")
            print(f"  ✗ {key}: {e}", file=sys.stderr)

    # 建索引:代號 -> 該檔資料
    rev_idx = {}
    for r in raw.get("twse_rev", []) + raw.get("tpex_rev", []):
        c = r.get("公司代號")
        if c in codes:
            rev_idx[c] = r

    price_idx = {}
    for r in raw.get("twse_price", []):
        if r.get("Code") in codes:
            price_idx[r["Code"]] = {"date": r.get("Date"), "close": r.get("ClosingPrice"), "change": r.get("Change")}
    for r in raw.get("tpex_price", []):
        c = r.get("SecuritiesCompanyCode")
        if c in codes:
            price_idx[c] = {"date": r.get("Date"), "close": r.get("Close"), "change": r.get("Change")}

    # 讀回上次的 data.json,保留歷史(每次抓取累積,才看得到「同一檔的變化」)
    prev = {}
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            prev = json.load(f).get("stocks", {})
    except (FileNotFoundError, json.JSONDecodeError):
        prev = {}

    out = {
        "meta": {
            "fetched_at": fetched_at,
            "sources": {
                "上市": "TWSE OpenAPI (openapi.twse.com.tw)",
                "上櫃": "櫃買中心 TPEx OpenAPI (tpex.org.tw)",
            },
            "errors": errors,
            "note": "資料為官方一手來源,經合理性與交叉驗證;有 flags 者請人工確認。",
        },
        "stocks": {},
    }

    for w in WATCH:
        c = w["code"]
        rev = rev_idx.get(c, {})
        px = price_idx.get(c, {})

        # 每日彙總檔的收盤(會落後一個交易日,留作雙來源核實基準)
        daily_close = to_float(px.get("close")) if px else None
        daily_date = roc_to_ad(px.get("date")) if px.get("date") else None
        # MIS 即時收盤(最新,顯示用)
        mis = fetch_mis(c, w["market"])

        if mis:
            price = mis["close"]; price_date = mis["date"]; price_change = mis["change"]
            price_source = "證交所即時 MIS"
        else:
            price = daily_close; price_date = daily_date; price_change = px.get("change")
            price_source = ("上市 TWSE" if w["market"] == "TWSE" else "上櫃 TPEx") + " 每日收盤"
        # 同一交易日才做雙來源核實
        price_verify = None
        if mis and daily_close is not None and daily_date == mis["date"]:
            diff = abs(mis["close"] - daily_close) / max(1e-9, (abs(mis["close"]) + abs(daily_close)) / 2) * 100
            price_verify = "verified" if diff < 1 else ("minor_diff" if diff <= 5 else "unverified")

        rec = {
            "code": c,
            "name": w["name"],
            "market": w["market"],
            "tag": w.get("tag", ""),
            # 月營收(原始單位:千元 → 換算百萬,與前端一致)
            "month": roc_to_ad(rev.get("資料年月")) if rev else None,
            "rev": (to_float(rev.get("營業收入-當月營收")) / 1000) if rev.get("營業收入-當月營收") else None,
            "rev_last_year": (to_float(rev.get("營業收入-去年當月營收")) / 1000) if rev.get("營業收入-去年當月營收") else None,
            "yoy": to_float(rev.get("營業收入-去年同月增減(%)")) if rev else None,
            "mom": to_float(rev.get("營業收入-上月比較增減(%)")) if rev else None,
            "rev_source": ("上市 TWSE" if w["market"] == "TWSE" else "上櫃 TPEx") if rev else None,
            # 股價(顯示用 MIS 最新收盤;daily_* 留作核實參考)
            "price": price,
            "price_date": price_date,
            "price_change": price_change,
            "price_source": price_source,
            "daily_close": daily_close,
            "daily_date": daily_date,
            "price_verify": price_verify,
        }
        rec["flags"] = sanity_revenue(rec)
        if rec["price"] is None:
            rec["flags"].append("無收盤價")

        # ── 累積歷史(看同一檔每次變化的關鍵)──
        old = prev.get(c, {})
        # 股價歷史:逐「交易日」一筆,同一天覆蓋
        price_hist = {p["date"]: p for p in old.get("price_history", []) if p.get("date")}
        if rec["price"] is not None and rec["price_date"]:
            price_hist[rec["price_date"]] = {
                "date": rec["price_date"], "price": rec["price"], "change": rec["price_change"],
            }
        rec["price_history"] = sorted(price_hist.values(), key=lambda x: x["date"])[-60:]  # 最多留 60 筆
        # 月營收歷史:逐「資料月」一筆,同月覆蓋
        rev_hist = {r["month"]: r for r in old.get("rev_history", []) if r.get("month")}
        if rec["rev"] is not None and rec["month"]:
            rev_hist[rec["month"]] = {
                "month": rec["month"], "rev": rec["rev"], "yoy": rec["yoy"], "mom": rec["mom"],
            }
        rec["rev_history"] = sorted(rev_hist.values(), key=lambda x: x["month"])[-36:]  # 最多留 36 個月

        out["stocks"][c] = rec

        status = "⚠️ " + "；".join(rec["flags"]) if rec["flags"] else "✓ 乾淨"
        rv = f"{rec['rev']:.0f}百萬" if rec["rev"] is not None else "—"
        pr = f"{rec['price']}" if rec["price"] is not None else "—"
        print(f"  {c} {w['name']:<4} 營收 {rv:>12}  YoY {rec['yoy']}  收盤 {pr:>7}  {status}")

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 另存 data.js:讓前端用 file:// 雙擊開啟也能讀(免開本機伺服器)
    with open("data.js", "w", encoding="utf-8") as f:
        f.write("window.STOCK_DATA = " + json.dumps(out, ensure_ascii=False, indent=2) + ";\n")
    print(f"\n已寫入 data.json 與 data.js（抓取時間 {fetched_at}）")
    if errors:
        print("注意:有來源抓取失敗,相關欄位留空。", file=sys.stderr)


if __name__ == "__main__":
    print("開始抓取(官方 TWSE + TPEx,一天請只跑一次)…")
    main()
