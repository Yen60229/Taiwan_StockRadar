"""
StockRadar - 資料初始化（第一次跑用）
1. 建立所有資料表
2. 灌入上市/上櫃公司基本資料
3. 抓近 3 個月歷史行情
4. 抓最近 4 週集保資料

執行：python -m pipeline.init_data
"""
import asyncio
import logging

from models.database import init_db
from pipeline.data_pipeline import run_full_pipeline

logger = logging.getLogger(__name__)


async def init_all():
    logger.info("🔧 Step 1/2: 建立資料表")
    await init_db()

    logger.info("🚀 Step 2/2: 執行第一次完整 Pipeline")
    result = await run_full_pipeline()

    logger.info("=" * 60)
    logger.info(f"✅ 初始化完成！篩選結果：{result.get('total', 0)} 檔")
    logger.info("    後續可用：")
    logger.info("    - bash scripts/run_now.sh       # 即時更新")
    logger.info("    - docker-compose up scheduler  # 啟動排程")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(init_all())
