#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
階段 3:評等(透明、可解釋、不黑箱)

三塊各自給分 → 加權總分:
  體質分(財報健檢)40%  估值分 30%  動能分(月營收)30%   ← 權重可調 WEIGHTS
一票否決:任何「關鍵數字」未核實(unverified)→ 不評等,標「資料不全」。
每一項都附「為什麼是這個分數」,不只給數字。

判讀用語:描述「反映什麼/風險在哪」,不講買賣。
"""

from report import KEY_DATUMS, gm_light, om_light, nm_light, dr_light, cr_light

WEIGHTS = {"體質": 0.40, "估值": 0.30, "動能": 0.30}
LIGHT_PT = {"green": 100, "amber": 60, "red": 20, "gray": None}


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def score_health(R):
    """體質分:三率 + 負債比 + 流動比 的燈號平均(現金流/速動屬需補,不計入也不扣分)。"""
    pts, why = [], []
    for label, light_fn, val in [
        ("毛利率", gm_light, R["gross_margin"]),
        ("營益率", om_light, R["op_margin"]),
        ("淨利率", nm_light, R["net_margin"]),
        ("負債比", dr_light, R["debt_ratio"]),
        ("流動比", cr_light, R["current_ratio"]),
    ]:
        lt = light_fn(val)
        p = LIGHT_PT.get(lt)
        if p is not None:
            pts.append(p)
            why.append(f"{label} {'🟢' if lt=='green' else '🟡' if lt=='amber' else '🔴'}({p})")
    s = _avg(pts)
    note = "、".join(why) + "(未含現金流/速動比,屬需補項)" if why else "資料不足"
    return s, note


def score_valuation(R):
    """估值分:估值合理性(越貴、風險越高 → 分越低)。有獲利看 PE,虧損看 PB。"""
    eps = (R["eps"].get("value") or 0)
    pe = R["pe"].get("value")
    pb = R["pb"].get("value")
    if eps > 0 and pe is not None:
        if pe < 15: s, d = 100, "PE<15 估值相對便宜"
        elif pe < 25: s, d = 85, "PE 15–25 合理"
        elif pe < 40: s, d = 65, "PE 25–40 中高,已反映成長預期"
        else: s, d = 40, "PE>40 偏高,成長不如預期回檔風險大"
        return s, f"{d}(PE {pe:.1f});此為估值面,非買賣建議。"
    if pb is not None:
        if pb < 1: s, d = 90, "PB<1 股價低於帳面淨值"
        elif pb < 3: s, d = 70, "PB 1–3"
        elif pb < 6: s, d = 50, "PB 3–6 偏高"
        else: s, d = 35, "PB>6 很高,多為未來預期"
        return s, f"虧損/獲利不穩,改看 PB:{d}(PB {pb:.2f})。"
    return None, "估值資料不足"


def score_momentum(R):
    """動能分:最新月營收 YoY(趨勢需≥3個月,此處先用最新月水準,並提醒雜訊)。"""
    ry = R.get("rev_yoy", {}).get("value")
    if ry is None:
        return None, "月營收 YoY 缺"
    if ry > 40: s = 100
    elif ry > 20: s = 85
    elif ry > 10: s = 70
    elif ry >= 0: s = 55
    else: s = 25
    return s, f"最新月 YoY {ry:.1f}%(單月為雜訊,連 3 月才算趨勢;趨勢需累積)。"


def evaluate(R):
    # 一票否決:關鍵數字未核實
    blockers = []
    for k in KEY_DATUMS:
        dm = R.get(k, {})
        if dm.get("verify") == "unverified":
            blockers.append(f"{k}({dm.get('note','')[:40]})")

    h, h_why = score_health(R)
    v, v_why = score_valuation(R)
    m, m_why = score_momentum(R)
    subs = {"體質": (h, h_why), "估值": (v, v_why), "動能": (m, m_why)}

    rated = (len(blockers) == 0) and all(x is not None for x, _ in subs.values())
    total = None
    if rated:
        total = round(h * WEIGHTS["體質"] + v * WEIGHTS["估值"] + m * WEIGHTS["動能"], 1)

    return {
        "code": R["code"], "name": R["name"], "rated": rated, "total": total,
        "subs": subs, "blockers": blockers,
        "verify_summary": {k: R.get(k, {}).get("verify") for k in KEY_DATUMS},
    }
