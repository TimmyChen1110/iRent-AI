"""Linux 缺少 macOS 字型時，標註圖片不得中斷 AI 判讀。"""
from types import SimpleNamespace

import pytest
from PIL import Image

import annotate_damage as annotations
import judge_photos as judge


@pytest.fixture
def without_system_fonts(monkeypatch):
    # 強制候選路徑不存在，重現乾淨 Linux 容器的字型環境。
    monkeypatch.setattr(annotations, "FONT_CANDIDATES", (("/missing/font.ttc", 0),))


@pytest.mark.parametrize("with_finding", [False, True])
def test_annotation_without_system_fonts(without_system_fonts, with_finding):
    findings = [annotations.Finding(
        box_2d=[200, 200, 400, 400], label="刮痕", severity="low",
        confidence=0.9, description="左後保桿新增刮痕",
    )] if with_finding else []
    result = annotations.draw_annotations(
        Image.new("RGB", (640, 480), "white"),
        annotations.AnnotatedResult(findings=findings, summary="車況判讀"),
    )
    assert result.mode == "RGB"
    assert result.size == (640, 480)
    assert result.getpixel((14, 479)) != (255, 255, 255)


def test_pair_keeps_ai_verdict_when_mac_font_is_missing(
        tmp_path, monkeypatch, without_system_fonts):
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (640, 480), "white").save(photo)
    monkeypatch.setattr(judge, "_run_gate", lambda photos, **kwargs: {
        name: {"pass": True, "reasons": []} for name in photos
    })
    assessment = judge.LiveAssessment(
        angle_match=True, new_damage_found=False, damages=[],
        no_damage_confidence=0.99, pre_existing_notes="",
    )
    monkeypatch.setattr(judge, "_call", lambda *args, **kwargs: ("mock", assessment))

    result, annotated = judge.judge_pair(photo, photo, client=SimpleNamespace())

    assert result["verdict"] == "clean"
    assert result["final"]["new_damage_found"] is False
    assert annotated.size == (640, 480)
