"""
SECRET_KEY 啟動守門的測試（P0-3）。

原本 `SECRET_KEY` 有 "change-me-in-production" 的 fallback：
只要忘了設環境變數，服務仍會正常啟動，但用的是一把公開的金鑰——
任何人都能自己簽出合法 token 登入任意帳號。

因為檢查發生在 module import 當下，必須用子行程測試才能控制環境變數。
"""
import os
import pathlib
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _import_deps_with(secret: str | None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("SECRET_KEY", None)
    if secret is not None:
        env["SECRET_KEY"] = secret
    env["DATABASE_URL"] = "postgresql+asyncpg://u:p@127.0.0.1:5432/d"
    env["PYTHONPATH"] = str(BACKEND)
    # 明確指定 UTF-8：錯誤訊息是中文，Windows 預設會用 cp950 解碼而炸掉
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", "import api.deps"],
        cwd=BACKEND, env=env, capture_output=True,
        encoding="utf-8", errors="replace",
    )


def test_missing_secret_key_refuses_to_start():
    result = _import_deps_with(None)
    assert result.returncode != 0, "沒有 SECRET_KEY 時必須拒絕啟動"
    assert "SECRET_KEY" in result.stderr


@pytest.mark.parametrize("placeholder", [
    "change-me",
    "change-me-in-production",
    "change-me-use-a-long-random-string",
    "CHANGE-ME-IN-PRODUCTION",          # 大小寫不該成為繞過的方式
    "  change-me-in-production  ",      # 前後空白也不行
])
def test_placeholder_secret_key_refuses_to_start(placeholder):
    """直接照抄 .env.example 的樣板值，等於用一把公開金鑰"""
    result = _import_deps_with(placeholder)
    assert result.returncode != 0, f"樣板值 {placeholder!r} 必須被拒絕"
    assert "SECRET_KEY" in result.stderr


def test_real_secret_key_starts_normally():
    result = _import_deps_with("K7x9Qm2vLpR4tYw8ZnB6cF1dH3jS5aG0eU7iO9kM2pX4")
    assert result.returncode == 0, result.stderr
