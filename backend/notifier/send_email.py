"""
StockRadar - Email 通知（Resend + SMTP 備援）
寄送週報，含「新進榜 / 跌出榜外」對比分析
"""
import os
import re
import smtplib
import logging
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Optional

import resend
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import (
    AsyncSessionLocal, ChipConcentration, DailyQuote,
    InstitutionalFlow, Stock, User,
)

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "report@stockradar.tw")
EMAIL_ADMIN    = os.environ.get("EMAIL_ADMIN", "admin@stockradar.tw")

# SMTP 備援
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

MIN_AVG_VOL   = int(os.environ.get("MIN_AVG_VOL", "2000"))
MIN_CHIP_CONC = float(os.environ.get("MIN_CHIP_CONC", "40.0"))

TEMPLATE_DIR = Path(__file__).parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)


async def get_screened_stocks(db: AsyncSession, target_date: Optional[date] = None) -> list[dict]:
    """取得指定日期的篩選結果"""
    quote_date = target_date or await db.scalar(select(DailyQuote.trade_date).order_by(desc(DailyQuote.trade_date)).limit(1))
    chip_date  = await db.scalar(select(ChipConcentration.week_date).order_by(desc(ChipConcentration.week_date)).limit(1))
    if not quote_date or not chip_date:
        return []

    rows = (await db.execute(
        select(
            Stock.code, Stock.name, Stock.market, Stock.industry,
            DailyQuote.close, DailyQuote.avg_vol_20d,
            ChipConcentration.conc_ratio,
            InstitutionalFlow.total_net,
        )
        .join(DailyQuote, and_(
            DailyQuote.stock_code == Stock.code,
            DailyQuote.trade_date == quote_date,
        ))
        .join(ChipConcentration, and_(
            ChipConcentration.stock_code == Stock.code,
            ChipConcentration.week_date  == chip_date,
        ))
        .outerjoin(InstitutionalFlow, and_(
            InstitutionalFlow.stock_code == Stock.code,
            InstitutionalFlow.trade_date == quote_date,
        ))
        .where(
            DailyQuote.avg_vol_20d >= MIN_AVG_VOL,
            ChipConcentration.conc_ratio >= MIN_CHIP_CONC,
        )
        .order_by(ChipConcentration.conc_ratio.desc())
    )).all()

    return [
        {
            "code": r.code, "name": r.name, "market": r.market,
            "industry": r.industry or "其他",
            "close": float(r.close) if r.close else None,
            "avg_vol_20d": float(r.avg_vol_20d) if r.avg_vol_20d else 0,
            "conc_ratio": float(r.conc_ratio) if r.conc_ratio else 0,
            "total_net": int(r.total_net) if r.total_net else 0,
        }
        for r in rows
    ]


async def calc_diff(this_week: list[dict], last_week: list[dict]) -> dict:
    """新進榜 / 跌出榜外 / 持續上榜"""
    this_codes = {s["code"] for s in this_week}
    last_codes = {s["code"] for s in last_week}
    new_in   = [s for s in this_week if s["code"] not in last_codes]
    dropped  = [s for s in last_week if s["code"] not in this_codes]
    persist  = [s for s in this_week if s["code"] in last_codes]
    return {"new_in": new_in, "dropped": dropped, "persist": persist}


def render_email(this_week: list[dict], diff: dict, run_date: date) -> str:
    template = jinja_env.get_template("weekly_report.html")
    industry_dist = {}
    for s in this_week:
        ind = s["industry"]
        industry_dist[ind] = industry_dist.get(ind, 0) + 1
    top_industries = sorted(industry_dist.items(), key=lambda x: -x[1])[:6]

    return template.render(
        run_date=run_date.strftime("%Y/%m/%d"),
        total=len(this_week),
        top10=this_week[:10],
        new_in=diff["new_in"][:5],
        dropped=diff["dropped"][:5],
        persist_count=len(diff["persist"]),
        top_industries=top_industries,
        min_avg_vol=MIN_AVG_VOL,
        min_conc=MIN_CHIP_CONC,
    )


def send_via_resend(to_email: str, subject: str, html: str) -> bool:
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
        logger.info(f"[Email] Resend 發送成功 → {to_email}")
        return True
    except Exception as e:
        logger.error(f"[Email] Resend 失敗：{e}")
        return False


def _html_to_plain(html: str) -> str:
    """
    做一個粗略的純文字版本當 multipart/alternative 的備援。
    不追求完美排版——垃圾信過濾器在意的是「有沒有純文字版本」，
    不是這個版本好不好看。
    """
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def send_via_smtp(to_email: str, subject: str, html: str) -> bool:
    """
    Gmail SMTP 備援。

    只寄 HTML、缺 Date/Message-ID 標頭的信，很容易被 Gmail 判定成垃圾信——
    尤其是「用自己帳號寄給自己」這種模式（本專案帳號通知信剛好常常是
    這樣：管理員的 Gmail 帳號同時是 SMTP_USER 也是收件人）。這裡補上
    正常郵件該有的東西：純文字備援、Date、Message-ID。
    這不保證一定進收件匣，但能降低被攔的機率；第一次被攔進垃圾桶後，
    收件人手動點「非垃圾郵件」，Gmail 之後通常就會放行。
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=SMTP_USER.split("@")[-1] or None)
        # multipart/alternative 依規範要「較不豐富的格式在前」，純文字先於 HTML
        msg.attach(MIMEText(_html_to_plain(html), "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"[Email] SMTP 發送成功 → {to_email}")
        return True
    except Exception as e:
        logger.error(f"[Email] SMTP 失敗：{e}")
        return False


async def send_weekly_reports():
    """主流程：取資料 → 渲染 → 寄送給所有訂閱者"""
    today = date.today()
    last_week_date = today - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        this_week = await get_screened_stocks(db)
        last_week = await get_screened_stocks(db, target_date=last_week_date)
        diff = await calc_diff(this_week, last_week)

        users = (await db.execute(select(User).where(User.notify_email == True))).scalars().all()

    html = render_email(this_week, diff, today)
    subject = f"📊 StockRadar 週報 {today.strftime('%m/%d')} · {len(this_week)} 檔符合"

    for user in users:
        ok = False
        if RESEND_API_KEY:
            ok = send_via_resend(user.email, subject, html)
        if not ok and SMTP_USER:
            ok = send_via_smtp(user.email, subject, html)
        if not ok:
            logger.error(f"[Email] 全部管道失敗 → {user.email}")

    logger.info(f"✅ 週報寄送完成：{len(users)} 位訂閱者")


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(send_weekly_reports())
