import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def _in_project_root(monkeypatch):
    # 提示词模板按相对路径 data/prompts 读取
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr("time.sleep", lambda s: None)
