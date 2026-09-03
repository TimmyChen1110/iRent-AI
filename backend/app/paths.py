#!/usr/bin/env python3
"""集中管理「執行期可設定」的路徑與旗標。

只涵蓋『會被寫入』或『部署時要換位置』的東西——上傳暫存、生產訊號流、
API 金鑰檢查。判定核心的唯讀資源（pipeline/ 內部檔、prompts/、評測結果
JSON）仍走各模組自身的 __file__ 相對路徑：pipeline/ 整包搬移時目錄深度
不變，那些路徑無需集中化。

所有設定用環境變數覆寫；不設就用開發預設值。Docker 由 compose 注入 env。

  IRENT_UPLOAD_DIR    非同步判讀 API 的上傳暫存根目錄（掛 volume）
  IRENT_LIVE_SIGNALS  生產 shadow 訊號流檔路徑
  IRENT_SCRATCH_DIR   現場實測 / AI 重判的暫存根目錄
  GEMINI_API_KEY      Gemini 金鑰（亦接受 GOOGLE_API_KEY 或 pipeline/.gemini_key 檔）
"""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent        # backend/app
BACKEND_DIR = APP_DIR.parent                      # backend
PIPELINE_DIR = BACKEND_DIR / "pipeline"           # backend/pipeline


def _path(env: str, default: Path) -> Path:
    v = os.environ.get(env)
    return Path(v).expanduser().resolve() if v else default


# 非同步判讀 API 的上傳暫存（Docker 掛 volume 於此）
UPLOAD_DIR = _path("IRENT_UPLOAD_DIR", APP_DIR / "inspection_uploads")

# 生產 shadow 訊號流——與 pipeline/shadow_signals.jsonl（評測基準）分開
LIVE_SIGNALS_PATH = _path("IRENT_LIVE_SIGNALS", PIPELINE_DIR / "shadow_signals_live.jsonl")

# 現場實測 / AI 重判上傳的暫存根（tempfile 預設 /tmp，可改指向 volume）
SCRATCH_DIR = _path("IRENT_SCRATCH_DIR", Path(os.environ.get("TMPDIR", "/tmp")))

# 複核決策 SQLite（階段 4 將整體換 Postgres；在那之前用 volume 保存容器狀態）
DB_PATH = _path("IRENT_DB_PATH", APP_DIR / "decisions.sqlite3")


def gemini_key_available() -> bool:
    """AI 端點的前置檢查：環境變數或 pipeline/.gemini_key 檔任一存在即可。

    原本只認 .gemini_key 檔——Docker 只注入 GEMINI_API_KEY 時 AI 端點會誤回 503。
    get_client() 本來就支援環境變數，這裡補上一致的判斷。
    """
    return bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or (PIPELINE_DIR / ".gemini_key").exists()
    )
