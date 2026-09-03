"""pairs.json 的統一讀取點。

pairs.json 內的照片路徑一律以 **repo 根** 為基準存相對路徑（可跨機器、git diff
看得懂）；載入時 `load_pairs()` 會還原成絕對路徑再交給下游。

舊版 pairs.json 存的是某台機器的絕對路徑——`_resolve()` 對絕對路徑原樣放行，
因此新舊格式都讀得起來，換檔不需要一次到位。
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIRS_JSON = Path(__file__).resolve().parent / "pairs.json"

_PATH_KEYS = ("pickup", "return", "return_alt")


def _resolve(p: str | None) -> str | None:
    if not p:
        return p
    q = Path(p)
    return str(q) if q.is_absolute() else str(REPO_ROOT / q)


def to_rel(p: str | Path) -> str:
    """絕對路徑 → repo 根相對路徑（build_pairs.py 寫檔時用）。"""
    q = Path(p).resolve()
    try:
        return str(q.relative_to(REPO_ROOT))
    except ValueError:
        return str(q)          # 資料集不在 repo 底下時退回絕對路徑


def load_pairs(path: str | Path = PAIRS_JSON) -> list[dict]:
    """回傳 pairs list，pickup / return / return_alt 已還原為絕對路徑。"""
    pairs = json.loads(Path(path).read_text())["pairs"]
    for pr in pairs:
        for k in _PATH_KEYS:
            if k in pr:
                pr[k] = _resolve(pr[k])
    return pairs
