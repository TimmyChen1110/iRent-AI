#!/usr/bin/env python3
"""Prompt 凍結的程式化維持（服務化規格 §6）。

凍結清單原本靠紀律維持；上線後由這支在服務啟動時比對 sha256，
不符即拒絕啟動並輸出差異。搭配 tests/test_service.py 的雙向凍結測試
（檔案內容 == 程式內 template 常數），把「改 prompt 要先驗證」
從自律變成機器檢查。

改 prompt 的正規流程：
  1. 新增版本檔（如 P7_blind_enumeration.v1.1.txt），舊檔不動
  2. 更新 MANIFEST.json
  3. 對 30 筆候選重跑驗證，結果附在 PR 描述
"""
import hashlib
import json
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

PROMPT_VERSIONS = {
    "P7": "P7-v1.0",
    "P9": "P9-v1.0",
    "threshold": "th-v6-4.62-3",
}


def verify_manifest() -> list:
    """回傳不符清單（空＝通過）。服務啟動時呼叫，不符即 raise。"""
    manifest = json.loads((PROMPTS_DIR / "MANIFEST.json").read_text())
    problems = []
    for name, expected in manifest.items():
        p = PROMPTS_DIR / name
        if not p.exists():
            problems.append(f"missing: {name}")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"hash mismatch: {name} expected {expected[:12]}… got {actual[:12]}…")
    return problems


def assert_frozen():
    problems = verify_manifest()
    if problems:
        raise RuntimeError("Prompt 凍結檢查失敗，拒絕啟動：\n" + "\n".join(problems))
