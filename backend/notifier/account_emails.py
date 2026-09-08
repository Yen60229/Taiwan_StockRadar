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
    admin_emails: list[str], applicant_email: str, applicant_name: str | None
) -> None:
    """有人申請帳號 → 通知管理員去審核"""
    targets = [e for e in admin_emails if e] or ([EMAIL_ADMIN] if EMAIL_ADMIN else [])
    if not targets:
        logger.warning("[Notify] 找不到任何管理員信箱，略過新申請通知")
        return

    who = f"{applicant_name}（{applicant_email}）" if applicant_name else applicant_email
    html = f"""
    <h3>StockRadar 有新的帳號申請</h3>
    <p><b>申請人：</b>{who}</p>
    <p>到管理後台審核：<a href="{_site_url()}/admin">{_site_url()}/admin</a></p>
    <p style="color:#888;font-size:12px">在你核准之前，這個帳號無法登入或讀取任何資料。</p>
    """
    for email in targets:
        await _send(email, "[StockRadar] 有新的帳號申請待審核", html)


async def notify_user_approved(user_email: str, user_name: str | None) -> None:
    """管理員核准 → 通知申請人可以登入了"""
    hello = f"{user_name} 你好" if user_name else "你好"
    html = f"""
    <h3>你的 StockRadar 帳號已開通</h3>
    <p>{hello}，你的帳號申請已通過審核，現在可以登入使用了。</p>
    <p><a href="{_site_url()}/login">{_site_url()}/login</a></p>
    """
    await _send(user_email, "[StockRadar] 帳號已開通", html)
