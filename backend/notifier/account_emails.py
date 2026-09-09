"""
帳號相關的通知信（申請通知管理員、核准通知使用者）。

跟 send_email.py 的週報共用同一套寄送管道（Resend 優先、Gmail SMTP 備援），
但不走 Jinja 模板——這兩封信短到用模板反而更難讀。

兩個重要性質：
  1. **絕不 raise**。寄信失敗不該讓註冊或核准這種主要動作跟著失敗——
     使用者已經送出申請了，信寄不出去是通知問題，不是註冊問題。
  2. **不阻塞 event loop**。smtplib 是同步阻塞的，直接在 async 路由裡呼叫
     會卡住整個 API（跟先前 bcrypt 那個 P0 是同一類問題），所以一律用
     asyncio.to_thread 丟到執行緒去跑。
"""
import asyncio
import logging
import os
from html import escape
from urllib.parse import quote

from notifier.send_email import (
    EMAIL_ADMIN, RESEND_API_KEY, SMTP_PASS, SMTP_USER,
    send_via_resend, send_via_smtp,
)

logger = logging.getLogger(__name__)


def _site_url() -> str:
    domain = os.environ.get("DOMAIN", "").strip()
    return f"https://{domain}" if domain else "（尚未設定 DOMAIN）"


def _delivery_configured() -> bool:
    return bool(RESEND_API_KEY) or bool(SMTP_USER and SMTP_PASS)


def _send_sync(to_email: str, subject: str, html: str) -> bool:
    """Resend 優先、SMTP 備援。同步函式，呼叫端請用 to_thread 包起來。"""
    if RESEND_API_KEY and send_via_resend(to_email, subject, html):
        return True
    if SMTP_USER and SMTP_PASS:
        return send_via_smtp(to_email, subject, html)
    return False


async def _send(to_email: str, subject: str, html: str) -> bool:
    if not _delivery_configured():
        logger.warning(
            "[Notify] 未設定 RESEND_API_KEY 或 SMTP_USER/SMTP_PASS，"
            f"略過寄信：{subject} → {to_email}"
        )
        return False
    try:
        return await asyncio.to_thread(_send_sync, to_email, subject, html)
    except Exception as e:  # 通知失敗不能影響主要流程
        logger.error(f"[Notify] 寄信失敗（已忽略）：{subject} → {to_email}：{e}")
        return False


async def notify_admins_new_registration(
    admin_emails: list[str],
    applicant_email: str,
    applicant_name: str | None,
    applicant_id: str | None = None,
) -> None:
    """
    有人申請帳號 → 通知管理員去審核。

    信裡的連結帶上 `?user=<id>`，管理後台會把那一筆標示出來，
    不用在清單裡自己找。這個連結**不帶任何權限**——它只是「開到這一頁」，
    沒登入一樣會被擋在登入頁，核准的權限檢查仍然在後端的 require_admin。
    刻意不做成「點了就核准」的免登入連結：那等於把核准權限放進信箱，
    信件被轉寄或信箱被入侵就等於帳號審核形同虛設。
    """
    targets = [e for e in admin_emails if e] or ([EMAIL_ADMIN] if EMAIL_ADMIN else [])
    if not targets:
        logger.warning("[Notify] 找不到任何管理員信箱，略過新申請通知")
        return

    who = f"{applicant_name}（{applicant_email}）" if applicant_name else applicant_email
    link = f"{_site_url()}/admin"
    if applicant_id:
        link = f"{link}?user={quote(str(applicant_id))}"

    html = f"""
    <h3>StockRadar 有新的帳號申請</h3>
    <p><b>申請人：</b>{escape(who)}</p>
    <p><a href="{link}"
          style="display:inline-block;padding:10px 20px;background:#00a8d4;
                 color:#fff;border-radius:6px;text-decoration:none;font-weight:700">
       前往審核</a></p>
    <p style="color:#888;font-size:12px">
      需要先登入管理員帳號；登入後會直接標示出這一筆申請。<br>
      在你核准之前，這個帳號無法登入或讀取任何資料。
    </p>
    """
    for email in targets:
        await _send(email, "[StockRadar] 有新的帳號申請待審核", html)


async def notify_user_approved(user_email: str, user_name: str | None) -> None:
    """管理員核准 → 通知申請人可以登入了"""
    hello = f"{escape(user_name)} 你好" if user_name else "你好"
    login_url = f"{_site_url()}/login"
    html = f"""
    <h3>你的 StockRadar 帳號已開通</h3>
    <p>{hello}，你的帳號申請已通過審核，現在可以登入使用了。</p>
    <p><a href="{login_url}"
          style="display:inline-block;padding:10px 20px;background:#00a8d4;
                 color:#fff;border-radius:6px;text-decoration:none;font-weight:700">
       前往登入</a></p>
    <p style="color:#888;font-size:12px">
      按鈕打不開的話，直接複製這個網址：{login_url}
    </p>
    """
    await _send(user_email, "[StockRadar] 帳號已開通", html)
