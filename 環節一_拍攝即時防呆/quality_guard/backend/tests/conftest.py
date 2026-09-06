"""測試共用 fixture。

模型檔（best.pt / *.onnx / view_classifier.pt）與真實照片都是二進位/大檔，
路徑一律從 repo 相對位置推出來，不寫死本機絕對路徑；拿不到的時候 skip 而不是
fail，這樣沒有下載模型的機器（或 CI）也能跑得動純邏輯的測試。
"""

from pathlib import Path

import pytest

from app.config import (
    PLATE_DETECT_MODEL_PATH,
    PLATE_OCR_CONFIG_PATH,
    PLATE_OCR_ONNX_PATH,
    VIEW_CLASSIFIER_PATH,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[2]
SAMPLE_PHOTO_DIR = (
    REPO_ROOT
    / "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率"
    / "沒有進行索賠"
)


def _first_photo_named(*, contains: str) -> Path | None:
    if not SAMPLE_PHOTO_DIR.is_dir():
        return None
    for path in sorted(SAMPLE_PHOTO_DIR.iterdir()):
        if path.is_file() and contains in path.name and path.suffix.lower() in {".jpg", ".jpeg"}:
            return path
    return None


@pytest.fixture(scope="session")
def plate_models_available() -> bool:
    return all(
        path.exists()
        for path in (PLATE_DETECT_MODEL_PATH, PLATE_OCR_ONNX_PATH, PLATE_OCR_CONFIG_PATH)
    )


@pytest.fixture(scope="session")
def view_model_available() -> bool:
    return VIEW_CLASSIFIER_PATH.exists()


@pytest.fixture(scope="session")
def sample_left_rear_photo() -> Path:
    """一張已知角度是「左後」、車牌清楚的真實照片（檔名即真值）。"""
    path = _first_photo_named(contains="左後 借")
    if path is None:
        pytest.skip(f"找不到真實照片樣本目錄：{SAMPLE_PHOTO_DIR}")
    return path
