"""
把一個既有帳號升級成管理員（並確保它是 active）。

為什麼只有 CLI、沒有 API：管理員是這個系統的最高權限，任何「透過網路
就能取得管理員」的路徑都是攻擊面。要動這件事，你必須能 SSH 進機器、
能執行容器內的指令——那本身就是一道遠比密碼強的門。

這也順帶避免了「第一個註冊的人自動變成管理員」這個經典漏洞：搶先註冊
沒有任何好處，因為升級只能從機器內部發動。

用法：
    docker compose -f docker-compose.prod.yml exec api \
        python -m scripts.make_admin you@example.com

    # 只看目前有誰是管理員，不做任何修改
    docker compose -f docker-compose.prod.yml exec api \
        python -m scripts.make_admin --list
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from models.database import ROLE_ADMIN, STATUS_ACTIVE, AsyncSessionLocal, User


async def list_admins() -> int:
    async with AsyncSessionLocal() as session:
        admins = (await session.execute(
            select(User).where(User.role == ROLE_ADMIN).order_by(User.email)
        )).scalars().all()

    if not admins:
        print("目前沒有任何管理員。")
        print("用法：python -m scripts.make_admin <email>")
        return 0

    print(f"目前的管理員（{len(admins)} 位）：")
    for a in admins:
        print(f"  {a.email:<40} status={a.status:<9} 最後登入={a.last_login_at or '從未'}")
    return 0


async def promote(email: str) -> int:
    async with AsyncSessionLocal() as session:
        user = (await session.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()

        if not user:
            print(f"❌ 找不到帳號：{email}")
            print("   這個腳本只能升級「已經註冊過」的帳號——請先在網站上註冊，再跑一次。")
            return 1

        was_role, was_status = user.role, user.status

        user.role = ROLE_ADMIN
        # 管理員一定要能登入，否則升級完卻進不去
        if user.status != STATUS_ACTIVE:
            user.status = STATUS_ACTIVE
            if user.approved_at is None:
                user.approved_at = datetime.utcnow()

        await session.commit()

    print(f"✅ {email} 已設為管理員")
    print(f"   role:   {was_role} → {ROLE_ADMIN}")
    if was_status != STATUS_ACTIVE:
        print(f"   status: {was_status} → {STATUS_ACTIVE}")
    else:
        print(f"   status: {was_status}（不變）")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--list":
        return asyncio.run(list_admins())
    return asyncio.run(promote(args[0]))


if __name__ == "__main__":
    sys.exit(main())
