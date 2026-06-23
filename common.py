#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共用工具:抓取(含限流/retry/快取)、單位轉換、核實判定、帶 metadata 的數字。"""

import os
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta

TPE = timezone(timedelta(hours=8))
RAW_DIR = "raw"

VERIFIED, MINOR, UNVER, OFFICIAL1, NA = "verified", "minor_diff", "unverified", "official_single", "n/a"

STATUS_LABEL = {
    VERIFIED: "✅ 已核實",
    MINOR: "🟡 小差異(採官方)",
    UNVER: "🔴 未核實",
    OFFICIAL1: "🟦 官方單一來源",
    NA: "⚪ 無資料",
}


def now_tpe():
    return datetime.now(TPE).strftime("%Y-%m-%d %H:%M")


_MEM = {}  # 同一次執行的記憶體快取:同一個 URL 只打一次 API(批次防封關鍵)


def fetch(url, label="", sleep=2.0, retries=3, cache=True):
    """抓 JSON;含 request 間 sleep、retry 上限;成功後存 raw/ 快取(API 掛了可回退)。
    同一次執行中,相同 URL 直接回傳記憶體快取,不重複打 API。"""
    if url in _MEM:
        return _MEM[url]
    fname = None
    if cache:
        os.makedirs(RAW_DIR, exist_ok=True)
        safe = "".join(c if c.isalnum() else "_" for c in url)[-120:]
        fname = os.path.join(RAW_DIR, safe + ".json")
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.load(r)
            time.sleep(sleep)
            if fname:
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            _MEM[url] = data
            return data
        except Exception as e:
            last = e
            time.sleep(sleep * (i + 1))
    # 失敗 → 嘗試回退快取
    if fname and os.path.exists(fname):
        try:
            with open(fname, encoding="utf-8") as f:
                print(f"  ! {label} 抓取失敗,改用上次快取。", flush=True)
                return json.load(f)
        except Exception:
            pass
    print(f"  ! 來源抓取失敗 {label}: {last}", flush=True)
    return None


def to_float(s):
    try:
        v = str(s).replace(",", "").replace("+", "").strip()
        if v == "" or v is None:
            return None
        return float(v)
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
    if a is None or b is None:
        return None
    base = (abs(a) + abs(b)) / 2
    return 0.0 if base == 0 else abs(a - b) / base * 100


def classify(d):
    if d is None:
        return UNVER
    if d < 1:
        return VERIFIED
    if d <= 5:
        return MINOR
    return UNVER


def datum(value, source, verify=OFFICIAL1, note="", sources=None):
    """帶 metadata 的數字:不讓裸數字在系統裡流動。"""
    return {
        "value": value,
        "source": source,
        "sources": sources or [source],
        "verify": verify if value is not None else NA,
        "note": note,
        "fetch_time": now_tpe(),
    }


def cross(a_val, a_src, b_val, b_src, name=""):
    """雙來源交叉:回傳帶核實狀態的 datum。"""
    d = diff_pct(a_val, b_val)
    st = classify(d)
    # 採官方(來源A視為官方基準)
    chosen = a_val if a_val is not None else b_val
    note = ""
    if d is not None:
        note = f"來源A {a_src}={a_val} / 來源B {b_src}={b_val} / 誤差 {d:.2f}%"
    elif a_val is not None:
        note = f"僅 {a_src}={a_val}(缺第二來源)"
        st = UNVER
    else:
        st = UNVER
    return {
        "value": chosen, "source": a_src, "sources": [a_src, b_src],
        "verify": st, "diff_pct": d, "note": note, "fetch_time": now_tpe(),
    }
