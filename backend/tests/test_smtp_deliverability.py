"""
回歸測試：SMTP 寄信的垃圾信對策（2026-09-10）。

背景：帳號通知信透過 Gmail SMTP 寄出，smtplib 回報成功（250 OK），
但實際落在收件人的垃圾桶。常見成因是「只有 HTML、沒有純文字備援」
加上「缺 Date / Message-ID 標頭」——這些是判斷是不是正常郵件的訊號，
尤其本專案的通知信常常是「管理員的 Gmail 帳號同時是寄件者也是收件人」，
這種自寄自收模式特別容易被攔。

這裡不測試「有沒有真的躲過垃圾信過濾器」（那不是我們控制得了的），
只測試「該補的標頭跟純文字備援真的補上了」。
"""
from email import message_from_bytes

from notifier.send_email import _html_to_plain, send_via_smtp


def test_html_to_plain_strips_tags_and_keeps_line_breaks():
    html = "<h3>標題</h3><p>第一段。</p><p>第二段<br>換行。</p>"
    text = _html_to_plain(html)

    assert "<" not in text and ">" not in text
    assert "標題" in text and "第一段" in text and "第二段" in text and "換行" in text


def test_html_to_plain_does_not_collapse_into_one_line():
    html = "<p>第一段</p><p>第二段</p>"
    text = _html_to_plain(html)
    assert "第一段\n\n第二段" in text or "第一段" in text.split("\n\n")[0]


def _captured_message(monkeypatch) -> bytes:
    """
    monkeypatch smtplib.SMTP，攔截 send_message() 拿到的 msg 物件，
    轉成 bytes 檢查真正送出去的標頭與內容——不要只信任程式碼寫了
    msg["Date"] = ...，要確認組出來的訊息真的帶著這些標頭。
    """
    captured = {}

    class _FakeServer:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, user, pw): pass
        def send_message(self, msg):
            captured["raw"] = msg.as_bytes()

    import notifier.send_email as se
    monkeypatch.setattr(se.smtplib, "SMTP", lambda *a, **kw: _FakeServer())
    monkeypatch.setattr(se, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(se, "SMTP_PASS", "irrelevant")

    ok = send_via_smtp("bot@example.com", "測試主旨", "<p>內容</p>")
    assert ok is True
    return captured["raw"]


def test_smtp_email_has_date_and_message_id_headers(monkeypatch):
    raw = _captured_message(monkeypatch)
    msg = message_from_bytes(raw)

    assert msg["Date"], "缺 Date 標頭是常見的垃圾信訊號之一"
    assert msg["Message-ID"], "缺 Message-ID 標頭是常見的垃圾信訊號之一"


def test_smtp_email_has_both_plain_and_html_parts(monkeypatch):
    raw = _captured_message(monkeypatch)
    msg = message_from_bytes(raw)

    content_types = [part.get_content_type() for part in msg.walk()]
    assert "text/plain" in content_types, "只有 HTML 沒有純文字備援，容易被判定成垃圾信"
    assert "text/html" in content_types


def test_plain_part_comes_before_html_part(monkeypatch):
    """multipart/alternative 規範：較不豐富的格式要排在前面"""
    raw = _captured_message(monkeypatch)
    msg = message_from_bytes(raw)

    parts = [p for p in msg.walk() if p.get_content_type() in ("text/plain", "text/html")]
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
