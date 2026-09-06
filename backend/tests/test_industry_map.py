"""TWSE 產業代碼對照的測試。"""
import pytest

from scraper.twse_scraper import map_industry


@pytest.mark.parametrize("code,expected", [
    ("01", "水泥工業"),
    ("24", "半導體業"),
    ("26", "光電業"),
    ("14", "航運業"),
    ("35", "建設業"),
    ("91", "第一上市"),   # 91xx 外國企業來台掛牌，原本沒有對應而直接顯示 "91"
])
def test_known_codes(code, expected):
    assert map_industry(code) == expected


def test_single_digit_code_is_zero_padded():
    assert map_industry("1") == "水泥工業"


def test_whitespace_is_trimmed():
    assert map_industry(" 24 ") == "半導體業"


@pytest.mark.parametrize("empty", ["", None])
def test_empty_falls_back_to_other(empty):
    assert map_industry(empty) == "其他"


def test_unknown_code_passes_through():
    """未知代碼原值回傳，資料才看得出是哪個代碼沒對應到（而不是全部變成「其他」）"""
    assert map_industry("99") == "99"


def test_chinese_input_passes_through():
    """ISIN 來源已經是中文，不該被再轉一次"""
    assert map_industry("半導體業") == "半導體業"
