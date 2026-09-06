"""API 層：request/response 契約與 base64 解碼。"""

import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _png_base64(image: np.ndarray) -> str:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return base64.b64encode(buffer.tobytes()).decode()


def test_healthz_reports_model_status():
    body = client.get("/healthz").json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["models"]) == {"plate", "view"}


def test_undecodable_image_returns_image_invalid():
    response = client.post(
        "/api/photo-quality/check",
        json={"required_view": "左前", "image_base64": "bm90IGFuIGltYWdl"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is False
    assert [e["code"] for e in body["errors"]] == ["IMAGE_INVALID"]
    assert body["debug"]["elapsed_ms"] >= 0


def test_data_url_prefix_is_accepted():
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    response = client.post(
        "/api/photo-quality/check",
        json={
            "required_view": "左前",
            "image_base64": f"data:image/png;base64,{_png_base64(black)}",
        },
    )
    assert response.status_code == 200
    # 解得開就不會是 IMAGE_INVALID 以外的解碼錯誤路徑；全黑圖會被 Stage 0 擋下
    assert response.json()["debug"]["stages_run"] == ["stage0_readability"]


def test_required_view_is_optional():
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    response = client.post("/api/photo-quality/check", json={"image_base64": _png_base64(black)})
    assert response.status_code == 200
    assert response.json()["required_view"] is None


def test_invalid_required_view_is_rejected():
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    response = client.post(
        "/api/photo-quality/check",
        json={"required_view": "車頂", "image_base64": _png_base64(black)},
    )
    assert response.status_code == 422


def test_full_pipeline_on_real_photo(plate_models_available, view_model_available, sample_left_rear_photo):
    if not (plate_models_available and view_model_available):
        pytest.skip("模型檔不存在")

    image = cv2.imread(str(sample_left_rear_photo))
    response = client.post(
        "/api/photo-quality/check",
        json={"required_view": "左後", "image_base64": _png_base64(image)},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["detected_view"] == "左後"
    assert body["plate_text"]
    assert 0.0 <= body["view_confidence"] <= 1.0
    assert 0.0 <= body["quality_score"] <= 1.0
    assert "stage4_view_confidence" in body["debug"]["stages_run"]
    assert body["debug"]["plate_bbox"] is not None
    # debug 的機率分布也要是 iRent 命名，不能一半翻譯一半沒翻譯
    labels = {p["label"] for p in body["debug"]["view_probabilities"]}
    assert labels == {"左前", "右前", "左後", "右後"}
