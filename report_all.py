#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
階段 3:全名單批次 + 評等排序 → 總報告(report_all.md)+ ratings.json(給前端)

對 AI 供應鏈關注名單每一檔跑 analyze + score,依綜合評分排序,
未核實者一票否決(標「資料不全,不評等」,排在最後)。

用法:python3 report_all.py
"""

import json
from common import now_tpe
from analyze import analyze, NAME, MARKET
from score import evaluate, WEIGHTS
from report import explain

# AI 供應鏈關注名單(角色標註;可擴充)
WATCHLIST = [
    ("2330", "上游·晶圓代工(溫度計)"),
    ("2308", "配套·電源"),
    ("4958", "零組件·載板"),
    ("8996", "配套·散熱"),
    ("6451", "配套·光通訊"),
    ("3081", "零組件·光通訊磊晶"),
    ("3363", "配套·光通訊"),
]

STAR = {"verified": "✅", "minor_diff": "🟡", "unverified": "🔴", "official_single": "🟦", "n/a": "⚪"}


def main():
    results = []
    for code, role in WATCHLIST:
        print(f"  分析 {code} {NAME.get(code,'')} …", flush=True)
        R = analyze(code)
        ev = evaluate(R)
        ev["role"] = role
        ev["period"] = R["period"]
        ev["price"] = R["price"].get("value")
        ev["price_date"] = R["price"].get("date")
        ev["gross_margin"] = R["gross_margin"]
        ev["op_margin"] = R["op_margin"]
        ev["net_margin"] = R["net_margin"]
        ev["debt_ratio"] = R["debt_ratio"]
        ev["pe"] = R["pe"].get("value")
        ev["pb"] = R["pb"].get("value")
        ev["rev_yoy"] = R.get("rev_yoy", {}).get("value")
        ev["rev_month"] = R.get("rev_month")
        ev["explain"] = explain(R)
        results.append(ev)

    rated = sorted([r for r in results if r["rated"]], key=lambda x: -x["total"])
    unrated = [r for r in results if not r["rated"]]

    # ── ratings.json + ratings.js(階段四前端用;.js 供 file:// 雙擊讀取)──
    payload = {"updated": now_tpe(), "weights": WEIGHTS,
               "rated": rated, "unrated": unrated, "results": results}
    with open("ratings.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open("ratings.js", "w", encoding="utf-8") as f:
        f.write("window.RATINGS = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n")

    # ── Markdown 總報告 ──
    L = []
    L.append("# AI 供應鏈 — 選股評等總報告")
    L.append(f"\n- 更新時間:**{now_tpe()}**(台北時間)")
    L.append(f"- 評分權重:體質 {int(WEIGHTS['體質']*100)}% / 估值 {int(WEIGHTS['估值']*100)}% / 動能 {int(WEIGHTS['動能']*100)}%")
    L.append("- 資料來源:證交所/櫃買 OpenAPI + MIS 即時報價,關鍵數字雙來源交叉核實")
    L.append("- **一票否決**:任何關鍵數字未核實 🔴 → 不評等(列於最後)")
    L.append("- ⚠️ 評分僅含「可自動核實」之指標;**現金流、業外一次性、附註、PEG** 屬需補項,未納入總分,請人工補查。")
    L.append("\n## 🏆 排序(已核實、可評等)\n")
    L.append("| 排名 | 代號 | 名稱 | 角色 | 綜合 | 體質 | 估值 | 動能 | 毛利率 | 負債比 | PE/PB | 月營收YoY |")
    L.append("|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for i, r in enumerate(rated, 1):
        h, v, m = r["subs"]["體質"][0], r["subs"]["估值"][0], r["subs"]["動能"][0]
        pepb = f"{r['pe']:.1f}" if (r.get('eps') or 1) and r['pe'] else (f"PB{r['pb']:.1f}" if r['pb'] else "—")
        pepb = f"{r['pe']:.1f}" if r['pe'] else (f"PB{r['pb']:.2f}" if r['pb'] else "—")
        L.append(f"| {i} | {r['code']} | {r['name']} | {r['role']} | **{r['total']}** | "
                 f"{fmt(h)} | {fmt(v)} | {fmt(m)} | {fmtp(r['gross_margin'])} | {fmtp(r['debt_ratio'])} | "
                 f"{pepb} | {fmtp(r['rev_yoy'])} |")

    if unrated:
        L.append("\n## 🔴 資料不全,不評等(一票否決)\n")
        for r in unrated:
            L.append(f"- **{r['code']} {r['name']}**({r['role']}):未核實項 → {', '.join(r['blockers']) or '指標缺漏'}")

    # 逐檔評分說明(透明)
    L.append("\n## 🔍 逐檔評分說明(為什麼是這個分數)\n")
    for r in rated + unrated:
        L.append(f"### {r['code']} {r['name']}　{'綜合 '+str(r['total']) if r['rated'] else '🔴 不評等'}")
        L.append(f"- 財報期別 {r['period']}　最新月 {r.get('rev_month') or '—'}")
        for blk in ("體質", "估值", "動能"):
            s, why = r["subs"][blk]
            L.append(f"- **{blk}分 {fmt(s)}**:{why}")
        ver = "　".join(f"{k}{STAR.get(v,'')}" for k, v in r["verify_summary"].items())
        L.append(f"- 關鍵數字核實:{ver}")
        if r["blockers"]:
            L.append(f"- ⚠️ 一票否決:{', '.join(r['blockers'])}")
        L.append("")

    L.append("---")
    L.append("*本報告為資料判讀輔助,非投資建議。半自動/需補項(現金流、業外明細、附註、PEG)請至公開資訊觀測站 MOPS 核對。*")
    out = "\n".join(L)
    with open("report_all.md", "w", encoding="utf-8") as f:
        f.write(out)
    print("\n已輸出 report_all.md 與 ratings.json")
    return out


def fmt(x):
    return "—" if x is None else f"{x:.0f}"


def fmtp(x):
    return "—" if x is None else f"{x:.1f}%"


if __name__ == "__main__":
    print("批次分析全名單(遵守 API 頻率限制,需約 1–2 分鐘)…")
    print(main())
