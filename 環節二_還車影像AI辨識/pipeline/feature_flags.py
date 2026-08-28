#!/usr/bin/env python3
"""功能旗標（服務化規格 §1 紅線）。

v6 訊號層：shadow 第二期完成前一律 off——只寫入不派送。
開啟的唯一條件是 §7 三檔接入判準之一（或 §4 小樣本補充條款）被滿足，
且該判定由 shadow_mode --step report / review API progress 程式化產出，
不是人為判斷。改這個值的 PR 必須附上該報告輸出。
"""
V6_ENABLED = False   # 紅線：shadow 第二期完成前不得為 True


def should_run_v6(verdict_no_new_damage: bool, has_pre_existing_claim: bool,
                  enabled: bool = None) -> dict:
    """v6 層觸發判定（省 75% 成本的限縮，前提已驗證——見下）。

    只在「判無新損＋帶既有損主張」時跑 v6 列舉。
    限縮前提（2026-08-29 上線前檢查，服務化規格 §5）：
      89 筆無主張案＝88 clean＋1 not_comparable（拍錯側），
      零已知真新損——「零訊號＝本來就沒訊號」成立，非漏檢。

    回傳 {"run": 是否跑列舉（shadow 寫入）, "dispatch": 是否派送複核}。
    flag off 時 run 仍可為 True（shadow 只寫入），dispatch 恆 False。
    """
    if enabled is None:
        enabled = V6_ENABLED
    run = verdict_no_new_damage and has_pre_existing_claim
    return {"run": run, "dispatch": run and enabled}
