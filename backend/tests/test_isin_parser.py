"""
ISIN 網站 HTML 解析的回歸測試。

為什麼這是最高價值的測試：ISIN 頁面的結構變動過不只一次——
欄位數從 6 變成 7 那次，讓 TPEX 全部 894 檔的產業一夜之間變成「其他」，
而且沒有任何錯誤訊息，只有資料悄悄變爛。
"""
from scraper.isin import COLUMNS, parse_isin_html
from scraper.tpex_scraper import TPEX_CODE_PATTERN
from scraper.twse_scraper import TWSE_CODE_PATTERN


def test_twse_isin_parses_real_page(fx):
    df = parse_isin_html(fx.text("isin_twse.html"), TWSE_CODE_PATTERN)

    assert list(df.columns) == COLUMNS
    assert len(df) == 5, "樣本含 5 檔上市普通股"

    tsmc_cement = df[df["code"] == "1101"].iloc[0]
    assert tsmc_cement["name"] == "台泥"
    assert tsmc_cement["short_name"] == "台泥", "ISIN 的名稱本身就是市場簡稱"
    assert tsmc_cement["industry"] == "水泥工業"


def test_tpex_isin_parses_real_page(fx):
    df = parse_isin_html(fx.text("isin_tpex.html"), TPEX_CODE_PATTERN)

    assert list(df.columns) == COLUMNS
    assert len(df) == 5
    assert df["industry"].notna().all()


def test_header_row_is_not_parsed_as_data(fx):
    """標題列同樣有 7 個 <td>，但沒有「代號　名稱」格式，不能被當成一檔股票"""
    df = parse_isin_html(fx.text("isin_twse.html"), TWSE_CODE_PATTERN)
    assert "有價證券代號及名稱" not in df["code"].tolist()
    assert not df["code"].str.contains("國際證券", na=False).any()


def test_warrants_are_filtered_out(fx):
    """權證代號（03001T / 700019）不符合普通股格式，必須被排除"""
    twse = parse_isin_html(fx.text("isin_twse.html"), TWSE_CODE_PATTERN)
    tpex = parse_isin_html(fx.text("isin_tpex.html"), TPEX_CODE_PATTERN)

    assert "03001T" not in twse["code"].tolist()
    assert "700019" not in tpex["code"].tolist()
    assert twse["code"].str.fullmatch(r"\d{4}").all()
    assert tpex["code"].str.fullmatch(r"\d{4,5}").all()


def test_six_cell_row_is_ignored():
    """
    回歸測試：曾經把資料列判成 6 格，導致整批資料被略過、產業全變「其他」。
    格數不符時必須跳過該列，而不是硬取索引。
    """
    html = """<table>
      <tr><td>1101　台泥</td><td>TW0001101004</td><td>1962/02/09</td>
          <td>上市</td><td>水泥工業</td><td>ESVUFR</td></tr>
    </table>"""
    df = parse_isin_html(html, TWSE_CODE_PATTERN)
    assert df.empty
    assert list(df.columns) == COLUMNS


def test_blank_industry_falls_back_to_other():
    html = """<table>
      <tr><td>1101　台泥</td><td>TW0001101004</td><td>1962/02/09</td>
          <td>上市</td><td>   </td><td>ESVUFR</td><td></td></tr>
    </table>"""
    df = parse_isin_html(html, TWSE_CODE_PATTERN)
    assert df.iloc[0]["industry"] == "其他"


def test_garbage_html_returns_empty_frame_with_columns():
    """網站掛掉或改版時要回結構完整的空表，呼叫端才不會 KeyError"""
    for html in ["", "<html><body>維護中</body></html>", "not html at all"]:
        df = parse_isin_html(html, TWSE_CODE_PATTERN)
        assert df.empty
        assert list(df.columns) == COLUMNS


def test_code_and_name_split_on_fullwidth_space():
    """分隔符是全形空格 U+3000，不是半形空白——用半形切會切不開"""
    html = """<table>
      <tr><td>2330　台積電</td><td>TW0002330008</td><td>1994/09/05</td>
          <td>上市</td><td>半導體業</td><td>ESVUFR</td><td></td></tr>
    </table>"""
    row = parse_isin_html(html, TWSE_CODE_PATTERN).iloc[0]
    assert row["code"] == "2330"
    assert row["name"] == "台積電"
