"""
TDCC 集保爬蟲診斷腳本 v2（帶 SYNCHRONIZER_TOKEN）
用法：docker compose exec scheduler python scripts/debug_tdcc.py
"""
import asyncio
import re
import httpx
from bs4 import BeautifulSoup

TDCC_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock",
    "Origin": "https://www.tdcc.com.tw",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
TEST_STOCK = "2330"


async def diagnose():
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # Step 1: GET 首頁取 token
        print("[Step 1] GET 集保首頁 ...")
        r_get = await client.get(TDCC_URL, headers=HEADERS)
        print(f"  狀態碼：{r_get.status_code}")
        soup_get = BeautifulSoup(r_get.text, "html.parser")

        def _val(name):
            inp = soup_get.find("input", {"name": name})
            return inp.get("value", "") if inp else ""

        token    = _val("SYNCHRONIZER_TOKEN")
        syn_uri  = _val("SYNCHRONIZER_URI")
        fir_date = _val("firDate")
        method   = _val("method")

        print(f"  SYNCHRONIZER_TOKEN：{'✅ ' + token[:20] + '...' if token else '❌ 未找到'}")
        print(f"  SYNCHRONIZER_URI：{syn_uri}")
        print(f"  firDate：{fir_date}")
        print(f"  method：{method}")

        if not fir_date:
            print("  ❌ 無法取得 firDate，中止")
            return

        # Step 2: POST 帶 token
        print(f"\n[Step 2] POST 查詢 {TEST_STOCK}，日期 {fir_date} ...")
        payload = {
            "SYNCHRONIZER_TOKEN": token,
            "SYNCHRONIZER_URI":   syn_uri,
            "method":             "submit",
            "firDate":            fir_date,
            "scaDates":           fir_date,
            "scaDate":            fir_date,
            "SqlMethod":          "StockNo",
            "StockNo":            TEST_STOCK,
            "REQ_TYPE":           "",
            "clkStockNo":         "",
            "clkStockName":       "",
        }
        r_post = await client.post(TDCC_URL, data=payload, headers=HEADERS)
        print(f"  狀態碼：{r_post.status_code}")
        print(f"  Body 長度：{len(r_post.text)} chars")

        html = r_post.text
        soup = BeautifulSoup(html, "html.parser")

        # 確認 response 裡是否有新 token
        new_token_inp = soup.find("input", {"name": "SYNCHRONIZER_TOKEN"})
        if new_token_inp:
            new_token = new_token_inp.get("value", "")
            print(f"  Response 含新 token：{'同一個' if new_token == token else '❗ 不同 → request-scoped'} ({new_token[:20]}...)")
        else:
            print("  Response 無 SYNCHRONIZER_TOKEN → 已進入結果頁")

        # 用第一次 POST 回傳的 token 查第二檔（2317鴻海）
        print(f"\n[Step 2b] POST 查詢 2317（用原 token / 不重新 GET）...")
        next_token = new_token_inp.get("value", token) if new_token_inp else token
        payload2 = dict(payload, StockNo="2317", clkStockNo="2317", SYNCHRONIZER_TOKEN=next_token)
        r_post2 = await client.post(TDCC_URL, data=payload2, headers=HEADERS)
        print(f"  狀態碼：{r_post2.status_code}, Body 長度：{len(r_post2.text)} chars")
        soup2 = BeautifulSoup(r_post2.text, "html.parser")
        tables2 = soup2.find_all("table")
        print(f"  找到 {len(tables2)} 個 table")
        for i, t in enumerate(tables2[:3]):
            rows = t.find_all("tr")
            header = [c.get_text(strip=True)[:15] for c in rows[0].find_all(["td","th"])[:5]] if rows else []
            print(f"  table[{i}] rows={len(rows)}, header={header}")

        # 重新 GET 後再查第三檔（2454）
        print(f"\n[Step 2c] 重新 GET 後查詢 2454（聯發科）...")
        r_get2 = await client.get(TDCC_URL, headers=HEADERS)
        soup_get2 = BeautifulSoup(r_get2.text, "html.parser")
        fresh_token = soup_get2.find("input", {"name": "SYNCHRONIZER_TOKEN"})
        fresh_token_val = fresh_token.get("value", "") if fresh_token else ""
        fir_date2 = (soup_get2.find("input", {"name": "firDate"}) or {}).get("value", fir_date)
        print(f"  Fresh token：{fresh_token_val[:20]}...")
        payload3 = dict(payload, StockNo="2454", clkStockNo="2454",
                        SYNCHRONIZER_TOKEN=fresh_token_val, firDate=fir_date2,
                        scaDates=fir_date2, scaDate=fir_date2)
        r_post3 = await client.post(TDCC_URL, data=payload3, headers=HEADERS)
        print(f"  狀態碼：{r_post3.status_code}, Body 長度：{len(r_post3.text)} chars")
        tables3 = BeautifulSoup(r_post3.text, "html.parser").find_all("table")
        print(f"  找到 {len(tables3)} 個 table")
        for i, t in enumerate(tables3[:3]):
            rows = t.find_all("tr")
            header = [c.get_text(strip=True)[:15] for c in rows[0].find_all(["td","th"])[:5]] if rows else []
            print(f"  table[{i}] rows={len(rows)}, header={header}")
            if len(rows) > 1:
                data = [c.get_text(strip=True)[:15] for c in rows[1].find_all(["td","th"])[:5]]
                print(f"    data[0]={data}")

        # Step 3: 分析 table 結構
        print("\n[Step 3] Table 結構分析 ...")
        all_tables = soup.find_all("table")
        print(f"  找到 {len(all_tables)} 個 <table>")
        for i, t in enumerate(all_tables[:10]):
            cls = t.get("class", [])
            rows = t.find_all("tr")
            print(f"  table[{i}] class={cls}, rows={len(rows)}")
            if rows:
                cells = rows[0].find_all(["th", "td"])
                first_row = [c.get_text(strip=True)[:20] for c in cells[:5]]
                print(f"    第1行：{first_row}")
            if len(rows) > 1:
                cells = rows[1].find_all(["th", "td"])
                second_row = [c.get_text(strip=True)[:20] for c in cells[:5]]
                print(f"    第2行：{second_row}")

        # Step 4: 找到數字 table，嘗試解析
        print("\n[Step 4] 找包含持股數字的 table ...")
        for i, t in enumerate(all_tables):
            rows = t.find_all("tr")
            if len(rows) < 5:
                continue
            data_rows = 0
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 3:
                    txt = cells[1].get_text(strip=True).replace(",", "")
                    if txt.isdigit():
                        data_rows += 1
            if data_rows >= 3:
                print(f"  ✅ table[{i}] 有 {data_rows} 列數字資料（共 {len(rows)} rows）")
                print("  前5列資料：")
                for row in rows[:5]:
                    cells = row.find_all(["td", "th"])
                    row_data = [c.get_text(strip=True)[:20] for c in cells[:5]]
                    print(f"    {row_data}")

        # Step 5: 試跑 parse 邏輯
        print("\n[Step 5] 試跑 parse_holding_table ...")
        threshold = 400 * 1000  # 400,000 股
        holders_400up = holders_total = 0
        target_table = None
        for t in all_tables:
            rows = t.find_all("tr")
            if len(rows) < 10:
                continue
            data_rows = sum(
                1 for row in rows
                if len(row.find_all(["td", "th"])) >= 3
                and row.find_all(["td", "th"])[1].get_text(strip=True).replace(",", "").isdigit()
            )
            if data_rows >= 5:
                target_table = t
                break

        if target_table:
            for row in target_table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 3:
                    continue
                level = cells[0].get_text(strip=True)
                h_txt = cells[1].get_text(strip=True).replace(",", "")
                s_txt = cells[2].get_text(strip=True).replace(",", "")
                if not h_txt.isdigit():
                    continue
                h = int(h_txt)
                s = int(s_txt) if s_txt.isdigit() else 0
                holders_total += h
                nums = re.findall(r"[\d,]+", level)
                if nums:
                    try:
                        min_val = int(nums[0].replace(",", ""))
                        if min_val >= threshold:
                            holders_400up += h
                    except ValueError:
                        pass
            if holders_total:
                ratio = round(holders_400up / holders_total * 100, 2)
                print(f"  ✅ 解析成功：400張以上 {holders_400up} 人 / 總計 {holders_total} 人 = {ratio}%")
            else:
                print("  ❌ holders_total=0，解析失敗")
        else:
            print("  ❌ 找不到有效 table")
            print("\n  HTML 片段（前3000字）：")
            print(html[:3000])


if __name__ == "__main__":
    asyncio.run(diagnose())
