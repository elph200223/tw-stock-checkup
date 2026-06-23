#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 analyze() 的結果 render 成 Markdown 報告(含白話判讀、燈號、核實摘要、黃金配對)。"""

from common import VERIFIED, MINOR, UNVER, OFFICIAL1, NA, STATUS_LABEL

KEY_DATUMS = ["price", "eps", "bvps", "pb", "gross", "rev_yoy"]  # 需雙來源核實的關鍵數字


def fnum(v, d=2, suffix=""):
    return "—" if v is None else f"{v:,.{d}f}{suffix}"


def light(level):
    return {"green": "🟢", "amber": "🟡", "red": "🔴", "gray": "⚪"}[level]


def vstat(dm):
    if not dm:
        return STATUS_LABEL[NA]
    s = STATUS_LABEL.get(dm.get("verify"), "")
    d = dm.get("diff_pct")
    return f"{s}（誤差 {d:.2f}%）" if d is not None else s


def render(R):
    L = []
    code, name = R["code"], R["name"]
    L.append(f"# {code} {name} — 財報健檢 + 估值 + 月營收 報告")
    L.append("")

    # ── 核實摘要 ──
    L.append("## 📋 資料來源與核實摘要")
    L.append(f"- 抓取時間:**{R['time']}**(台北時間)")
    L.append(f"- 市場別:{'上市(TWSE)' if R['market']=='TWSE' else '上櫃(TPEx)'}　|　財報期別:**{R['period']}**(單季)")
    L.append("- 來源:證交所/櫃買 OpenAPI(每日收盤、PE/PB、綜合損益表、資產負債表、月營收)+ 證交所 MIS 即時報價")
    cnt = {VERIFIED: 0, MINOR: 0, UNVER: 0, OFFICIAL1: 0, NA: 0}
    for k in KEY_DATUMS:
        v = R.get(k, {}).get("verify", NA)
        cnt[v] = cnt.get(v, 0) + 1
    L.append(f"- 關鍵數字核實:✅ 已核實 {cnt[VERIFIED]}　🟡 小差異 {cnt[MINOR]}　🔴 未核實 {cnt[UNVER]}　🟦 官方單一 {cnt.get(OFFICIAL1,0)}")
    if cnt[UNVER] > 0:
        L.append(f"- ⚠️ **有 {cnt[UNVER]} 個關鍵數字未核實,相關判讀標『存疑』,不納入評等(一票否決)。**")
    L.append("")
    L.append("> 半自動項目(官方 API 無乾淨來源,需人工查 MOPS 或手動補):**營業現金流、存貨(速動比用)、業外一次性明細、附註(客戶集中度/訴訟/期後事項)**。")
    L.append("")

    # ── 五問題健檢 ──
    L.append("## 🩺 財報健檢(五問題)")
    L.append("")

    # ① 賺不賺
    L.append("### ① 賺不賺?(三率)")
    gm, om, nm = R["gross_margin"], R["op_margin"], R["net_margin"]
    L.append(f"| 指標 | 數值 | 燈號 | 白話 |")
    L.append(f"|---|--:|:--:|---|")
    L.append(f"| 毛利率 | {fnum(gm,1,'%')} | {light(gm_light(gm))} | {gm_say(gm)} |")
    L.append(f"| 營益率 | {fnum(om,1,'%')} | {light(om_light(om))} | 扣掉營業費用後、靠本業真正賺的比率,是『會不會做生意』的核心。 |")
    L.append(f"| 淨利率 | {fnum(nm,1,'%')} | {light(nm_light(nm))} | 最後落袋(含業外、稅後)。每 100 元營收股東約實拿 {fnum(nm,1)} 元。 |")
    L.append(f"- 毛利核實:{R['gross']['value'] and fnum(R['gross']['value'],0)} 千元　{vstat(R['gross'])}（{R['gross'].get('note','')}）")
    if nm is not None and om is not None and nm >= om:
        L.append(f"- 🔴 **業外雷達**:淨利率({fnum(nm,1,'%')})≥ 營益率({fnum(om,1,'%')}),獲利有一大塊來自本業以外 → 需查是否一次性(見第②問)。")
    L.append("")

    # ② 乾不乾淨
    L.append("### ② 乾不乾淨?(業外)")
    nr = R.get("nonop_ratio")
    L.append(f"- 業外損益:{fnum(R['nonop']['value'],0)} 千元;占稅前淨利 **{fnum(nr,1,'%')}**。")
    if nr is not None:
        if abs(nr) < 15:
            L.append(f"- {light('green')} 業外占比 < 15%,本業為主,結構單純。")
        else:
            L.append(f"- {light('amber')} 業外占比偏高,需拆「一次性(處分利益等)vs 常態(利息/轉投資)」。")
    L.append("- ⚠️ 一次性/常態的拆分需財報附註明細,官方 API 取不到 → **需人工查 MOPS**,本報告不臆測。")
    L.append("")

    # ③ 是不是真錢
    L.append("### ③ 是不是真錢?(現金流)")
    L.append(f"- {light('gray')} **需補資料**:{R['cash_note']}")
    L.append("- 補上『營業活動現金流』後,規則:淨利為正但營業現金流為負 → 🔴,要查存貨/應收。")
    L.append("")

    # ④ 撐不撐得住
    L.append("### ④ 撐不撐得住?(資產負債)")
    dr, cr = R["debt_ratio"], R["current_ratio"]
    L.append(f"| 指標 | 數值 | 燈號 | 白話 |")
    L.append(f"|---|--:|:--:|---|")
    L.append(f"| 負債比 | {fnum(dr,1,'%')} | {light(dr_light(dr))} | {dr_say(dr)} |")
    L.append(f"| 流動比 | {fnum(cr,2,' 倍')} | {light(cr_light(cr))} | {cr_say(cr)} |")
    L.append(f"| 速動比 | — | ⚪ | {R['quick_note']} |")
    L.append("")

    # ⑤ 有沒有暗箭
    L.append("### ⑤ 有沒有暗箭?(附註)")
    L.append("- ⚪ **需人工查 MOPS**:客戶/供應商集中度、重大訴訟、期後事項、關係人交易、背書保證。純文字,官方 API 取不到,不臆測。")
    L.append("")

    # ── 估值 ──
    L.append("## 💰 估值")
    pe, pb = R["pe"], R["pb"]
    eps, bvps = R["eps"], R["bvps"]
    profitable = (eps.get("value") or 0) > 0
    L.append(f"- 股價:**{fnum(R['price']['value'],2)}**　{vstat(R['price'])}")
    if R.get("latest_price"):
        lp = R["latest_price"]
        L.append(f"  - ℹ️ 最新價 {lp['date']} 收盤 {lp['price']}(目前僅 MIS 單一來源,官方每日檔傍晚更新後可雙核)。")
    L.append(f"- EPS(單季 {R['period']}):**{fnum(eps['value'],2)}**　{vstat(eps)}")
    L.append(f"- 每股淨值:**{fnum(bvps['value'],2)}**　{vstat(bvps)}")
    L.append("")
    if profitable:
        L.append(f"**主看 PE(有獲利)**　本益比 = **{fnum(pe['value'],2)} 倍**　{vstat(pe)}")
        L.append(f"- {pe_say(pe['value'])}")
        L.append(f"- ⚠️ {pe['note']}")
        L.append(f"- PEG(本益成長比):**需補**——需 EPS 年成長率(待累積四季/去年同季 EPS)才能算,本報告不硬給。")
        L.append(f"- 輔看 PB = **{fnum(pb['value'],2)} 倍**　{vstat(pb)};{pb_say(pb['value'])}")
    else:
        L.append(f"**主看 PB(獲利為負/不穩)**　股價淨值比 = **{fnum(pb['value'],2)} 倍**　{vstat(pb)}")
        L.append(f"- {pb_say(pb['value'])}")
        if pb.get("value") and bvps.get("value"):
            prem = (R['price']['value'] - bvps['value'])
            L.append(f"- 拆解:股價 {fnum(R['price']['value'],2)} 中,『身家(每股淨值)』{fnum(bvps['value'],2)}、"
                     f"『市場為未來多付/少付』{fnum(prem,2)}。")
    L.append("")

    # ── 月營收 ──
    L.append("## 📈 月營收(領先指標)")
    if R.get("rev_month"):
        ry = R["rev_yoy"]
        L.append(f"- 最新月:**{R['rev_month']}**　營收 {fnum(R['rev_value'],0)} 百萬　YoY **{fnum(ry['value'],2,'%')}**　MoM {fnum(R['rev_mom'],2,'%')}")
        L.append(f"- YoY 核實:{vstat(ry)}（{ry.get('note','')}）")
        L.append("- ⚠️ 趨勢判讀(加速🟢/退燒🟡/衰退🔴)需連續 ≥3 個月——**一個月是雜訊**。每日自動排程會逐月累積,夠 3 個月才下趨勢結論。")
    else:
        L.append("- ⚪ 此檔月營收抓不到。")
    L.append("")

    # ── 黃金配對 ──
    L.append("## 🔗 黃金配對(搭配判讀,拆穿單一指標假象)")
    L.append(f"1. **淨利 × 現金流**:⚪ 需補營業現金流,才能判斷帳上淨利是否變成真金。")
    pair2 = "🟢 量價俱佳(營收成長且毛利高)" if (R.get('rev_yoy',{}).get('value',0) or 0) > 0 and (gm or 0) > 40 else "需看毛利率趨勢"
    L.append(f"2. **營收 × 毛利率**:最新月營收 YoY {fnum(R.get('rev_yoy',{}).get('value'),1,'%')}、毛利率 {fnum(gm,1,'%')} → {pair2}(完整需毛利率逐季趨勢)。")
    L.append(f"3. **三率一起**:毛利率 {fnum(gm,1,'%')} / 營益率 {fnum(om,1,'%')} / 淨利率 {fnum(nm,1,'%')}。"
             f"{three_say(gm,om,nm)}（哪一層惡化需逐季趨勢,待累積)。")
    L.append(f"4. **成長率 × 估值(PEG)**:⚪ 需 EPS 年成長率,待累積後才能判斷『貴不貴的真相』。")
    L.append(f"5. **負債比 × 現金流 × 現金**:負債比 {fnum(dr,1,'%')}、流動比 {fnum(cr,2,'倍')};⚪ 現金流與手上現金需補,才能完整判斷撐不撐得住。")
    L.append("")

    L.append("---")
    L.append("*本報告為資料判讀輔助,非投資建議。判讀只描述「數字反映什麼、風險在哪、要觀察什麼」,不給買賣指令。半自動/需補項請至公開資訊觀測站(MOPS)核對。*")
    return "\n".join(L)


# ── 白話規則 ──
def gm_light(v): return "gray" if v is None else ("green" if v > 40 else ("amber" if v >= 10 else "red"))
def gm_say(v):
    if v is None: return "資料不足。"
    if v > 40: return "高毛利(>40%),有定價權、不易被殺價,通常具技術或品牌護城河。"
    if v >= 10: return "中等毛利(10–40%),有競爭但仍賺加工/設計財,看能否守住。"
    return "低毛利(<10%),走量型,賺辛苦的規模財,景氣或殺價最先受傷。"
def om_light(v): return "gray" if v is None else ("green" if v > 15 else ("amber" if v >= 5 else "red"))
def nm_light(v): return "gray" if v is None else ("green" if v > 10 else ("amber" if v >= 3 else "red"))
def dr_light(v): return "gray" if v is None else ("red" if v > 70 else ("amber" if v > 60 else "green"))
def dr_say(v):
    if v is None: return "資料不足。"
    if v > 70: return "家當七成以上靠借(>70%),槓桿偏高,升息/景氣反轉壓力大。"
    if v > 60: return "家當六成靠借(>60%),偏高要留意趨勢是升是降。"
    return "負債比在 60% 內,財務結構相對穩健。"
def cr_light(v): return "gray" if v is None else ("green" if v > 1.5 else ("amber" if v >= 1 else "red"))
def cr_say(v):
    if v is None: return "資料不足。"
    if v > 1.5: return f"流動資產是短期負債的 {v:.2f} 倍(>1.5),短期償債充足。"
    if v >= 1: return "流動比 1–1.5,過得去但緩衝不大。"
    return "流動比 <1,短期償債吃緊。"
def pe_say(v):
    if v is None: return "PE 無法取得。"
    if v < 0: return "EPS 為負、PE 無意義:股價靠『未來預期』撐,非靠目前獲利,風險高。"
    if v > 40: return f"PE {v:.1f} 偏高(>40),市場給很高成長期待;成長不如預期回檔會兇。"
    if v > 25: return f"PE {v:.1f} 中高(25–40),已反映不少成長預期,進場挑時機。"
    return f"PE {v:.1f},約 {v:.0f} 年回本,估值相對不貴。"
def pb_say(v):
    if v is None: return "PB 無法取得。"
    if v > 1: return f"PB {v:.2f} >1,市場願為它的未來多付錢(高於帳面淨值),成長股常見,別追過頭。"
    return f"PB {v:.2f} <1,股價低於帳面淨值,市場看法保守甚至看衰,可能低估也可能有隱憂,要查原因。"
def three_say(gm, om, nm):
    if None in (gm, om, nm): return "三率資料不足。"
    drop1 = 100 - gm  # 營收→毛利 被成本吃掉
    drop2 = gm - om   # 毛利→營益 被營業費用吃掉
    return f"成本吃掉約 {drop1:.0f} 個百分點、營業費用再吃約 {drop2:.0f} 個百分點。"


def om_say(v):
    if v is None: return "資料不足。"
    if v > 15: return f"營益率 {v:.1f}%:本業很會賺,扣掉人事、行銷等營業費用後還留下不少,是真功夫。"
    if v >= 5: return f"營益率 {v:.1f}%:本業有賺,但營業費用吃掉不少,獲利空間中等。"
    return f"營益率 {v:.1f}%:本業幾乎沒利潤,費用幾乎把毛利吃光,要小心。"


def nm_say(v):
    if v is None: return "資料不足。"
    if v > 10: return f"淨利率 {v:.1f}%:每賣 100 元,最後股東實拿約 {v:.0f} 元,落袋能力強。"
    if v >= 3: return f"淨利率 {v:.1f}%:每賣 100 元最後留下約 {v:.0f} 元,普通水準。"
    return f"淨利率 {v:.1f}%:每 100 元營收最後只剩 {v:.1f} 元,很薄,易受波動影響。"


# ── 評等分頁用:像老師講解的整段白話 ──
def explain(R):
    """產生白話教學內容:一句話總結 + 各指標解釋 + 要觀察什麼。"""
    gm, om, nm = R["gross_margin"], R["op_margin"], R["net_margin"]
    dr, cr = R["debt_ratio"], R["current_ratio"]
    pe, pb = R["pe"].get("value"), R["pb"].get("value")
    eps = R["eps"].get("value") or 0
    yoy = R.get("rev_yoy", {}).get("value")
    name = R["name"]

    # 體質一句
    if None not in (gm, om, nm, dr, cr):
        strong = (gm > 40 and nm > 10 and (dr or 0) < 60)
        if strong: body = "很會賺錢(毛利、淨利都高)、負債也低,財務體質很健康"
        elif nm and nm > 3: body = "本業有賺、財務還算穩,但有一兩個指標普通"
        else: body = "賺錢能力或財務結構有明顯弱點"
    else:
        body = "部分體質指標資料不足"

    # 動能一句
    if yoy is None: mom = "月營收資料不足"
    elif yoy > 20: mom = f"月營收還在高速成長(最新月年增 {yoy:.0f}%)"
    elif yoy >= 0: mom = f"月營收溫和成長(年增 {yoy:.0f}%)"
    else: mom = f"月營收在衰退(年增 {yoy:.0f}%),動能踩煞車"

    # 估值一句
    if eps > 0 and pe is not None:
        if pe > 40: val = f"但目前股價偏貴(本益比 {pe:.0f} 倍),等於先付了很多未來的成長;一旦成長不如預期,容易回檔"
        elif pe > 25: val = f"股價不算便宜(本益比 {pe:.0f} 倍),已反映不少成長期待"
        else: val = f"而且現在股價不算貴(本益比 {pe:.0f} 倍)"
    elif pb is not None:
        val = f"由於獲利不穩,改用股價淨值比看:目前 {pb:.1f} 倍" + ("(高,多在反映未來預期)" if pb > 3 else "")
    else:
        val = "估值資料不足"

    summary = f"{name}:{body},{mom},{val}。"

    health = []
    if gm is not None: health.append({"name": "毛利率", "val": f"{gm:.1f}%", "light": gm_light(gm), "say": gm_say(gm)})
    if om is not None: health.append({"name": "營益率", "val": f"{om:.1f}%", "light": om_light(om), "say": om_say(om)})
    if nm is not None: health.append({"name": "淨利率", "val": f"{nm:.1f}%", "light": nm_light(nm), "say": nm_say(nm)})
    if dr is not None: health.append({"name": "負債比", "val": f"{dr:.1f}%", "light": dr_light(dr), "say": dr_say(dr)})
    if cr is not None: health.append({"name": "流動比", "val": f"{cr:.2f} 倍", "light": cr_light(cr), "say": cr_say(cr)})

    valuation = (pe_say(pe) if eps > 0 else pb_say(pb))
    if eps > 0 and yoy is not None and pe is not None and pe > 40 and yoy > 30:
        valuation += f" 不過它月營收年增 {yoy:.0f}%、成長很快——高成長配高本益比未必真的貴,這要靠 PEG(本益成長比)判斷,目前資料還不夠算,先別只看 PE 就說太貴。"

    watch = ("要觀察的重點:① 高成長能不能延續(看月營收是否連續 3 個月維持)。"
             "② 賺的是不是真錢(需補『營業現金流』,到公開資訊觀測站查)。"
             "③ 有沒有暗箭(客戶集中度、訴訟等,需查附註)。")

    return {"summary": summary, "health": health, "valuation": valuation,
            "momentum_say": mom + "。單月可能只是雜訊,要連 3 個月同方向才算真趨勢。", "watch": watch,
            "score_scale": "綜合分滿分 100:越高代表「體質好 + 成長強 + 估值不貴」三者兼具;但這是排序參考,不是買賣訊號。"}
