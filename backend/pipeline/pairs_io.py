"""pairs.json 的統一讀取點。

pairs.json 內的照片路徑一律以 **資料集資料夾** 為基準存相對路徑
（例如 `沒有進行索賠/RCG2235右前 借.jpg`），載入時 `load_pairs()` 依
`IRENT_DATASET_ROOT` 還原成絕對路徑。

  IRENT_DATASET_ROOT   原始照片資料集的根目錄。不設 → repo 根下的
                       「iRent - 運用 AI 打造…」資料夾（本機開發預設）。
                       Docker 把資料集掛在他處時用它覆寫（見 docker-compose.yml）。

舊版 pairs.json 存的是某台機器的絕對路徑——`_resolve()` 對絕對路徑原樣放行，
新舊格式都讀得起來；但相對路徑的基準已從 repo 根改為資料集資料夾，換基準後
需重跑 `build_pairs.py` 重新產生 pairs.json。
"""
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIRS_JSON = Path(__file__).resolve().parent / "pairs.json"

_DATASET_DIRNAME = "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率"

# 資料集根：env 覆寫優先，否則 repo 根下的原始資料夾
DATASET_ROOT = (
    Path(os.environ["IRENT_DATASET_ROOT"]).expanduser().resolve()
    if os.environ.get("IRENT_DATASET_ROOT")
    else REPO_ROOT / _DATASET_DIRNAME
)

_PATH_KEYS = ("pickup", "return", "return_alt")


def _resolve(p: str | None) -> str | None:
    if not p:
        return p
    q = Path(p)
    return str(q) if q.is_absolute() else str(DATASET_ROOT / q)


def to_rel(p: str | Path) -> str:
    """絕對路徑 → 相對資料集資料夾（build_pairs.py 寫檔時用）。"""
    q = Path(p).resolve()
    try:
        return str(q.relative_to(DATASET_ROOT))
    except ValueError:
        return str(q)          # 資料集不在預期位置時退回絕對路徑


def load_pairs(path: str | Path = PAIRS_JSON) -> list[dict]:
    """回傳 pairs list，pickup / return / return_alt 已還原為絕對路徑。"""
    pairs = json.loads(Path(path).read_text())["pairs"]
    for pr in pairs:
        for k in _PATH_KEYS:
            if k in pr:
                pr[k] = _resolve(pr[k])
    return pairs
