#!/usr/bin/env python3
"""判定結果檔的單一事實來源。

Dashboard、標註、護照、KPI 統計必須全部讀同一份結果，否則後台顯示的判定
會與標註框、護照、簡報數字對不起來（曾發生：build_dashboard 讀未級聯的
v2_exif，而標註/護照讀 v3_cascaded，5 組案件判定相反、3 組「判無損卻有
標註框」）。換版本只改這裡。

用法：
    from results_config import SCREEN_RESULTS, FINAL_RESULTS
    data = json.loads(FINAL_RESULTS.read_text())["results"]
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 快篩（未級聯）結果——只有 analyze_autopass 需要，用來算「升級複核比例」
SCREEN_RESULTS = HERE / "eval_results_gemini_37_flash_v3.json"

# ★ 最終判定結果（Flash 快篩 + Pro 級聯複核）——所有對外呈現一律以此為準
#   Recall 85.7% / FPR 3.3%（141 組）
FINAL_RESULTS = HERE / "eval_results_gemini_37_flash_v3_cascaded.json"

# 車內整潔判定結果（Flash 快篩 + Pro 複核）
INTERIOR_RESULTS = HERE / "interior_results.json"
