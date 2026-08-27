"""讓 tests/ 直接 import pipeline/ 與 dashboard/ 的模組。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "dashboard"))
