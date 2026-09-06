# 備份與還原

> 原則（藍圖 ADR-10）：**沒演練過的備份等於沒有備份**。
> 這份文件涵蓋 Phase 1 的最低標準：每日本機備份 + 可驗證的還原演練。
> 異地複本（Cloudflare R2）是 Phase 2，見文末。

---

## 現況

| 項目 | 值 |
|---|---|
| 備份方式 | `pg_dump -Fc`（自訂格式，已壓縮，支援選擇性還原）|
| 存放位置 | 主機 `/opt/backups/`（**與資料庫同一台**）|
| 頻率 | 每日 03:30（host crontab）|
| 保留 | 14 天 |
| RPO | 24 小時（資料週更，可接受）|
| RTO | 見下方演練記錄 |
| 異地複本 | ❌ 尚未（Phase 2）|

⚠️ 目前備份與資料庫在同一台機器，**只防誤刪誤改，防不了整台機器不見**
（Oracle Always Free 的 idle reclaim、磁碟故障）。異地複本是最優先的下一步。

---

## 安裝每日排程（在伺服器上做一次）

```bash
chmod +x /opt/stockradar/scripts/backup_db.sh /opt/stockradar/scripts/restore_drill.sh
sudo mkdir -p /opt/backups && sudo chown "$USER:$USER" /opt/backups

# 先手動跑一次，確認會產生 dump
bash /opt/stockradar/scripts/backup_db.sh

# 加進 host crontab：每天 03:30
( crontab -l 2>/dev/null | grep -v backup_db.sh
  echo "30 3 * * * bash /opt/stockradar/scripts/backup_db.sh >> /opt/backups/backup.log 2>&1"
) | crontab -
crontab -l
```

`backup_db.sh` 每次都會自己驗證產出的 dump（大小 + `pg_restore -l` 讀得動），
壞掉的檔案會直接刪除並以非零狀態結束，不會留下假的安全感。

---

## 還原演練（每季至少一次）

```bash
bash /opt/stockradar/scripts/restore_drill.sh
```

它會起一個**拋棄式**的 PostgreSQL 容器把備份還原進去，
逐表比對 row count 與最新日期，**完全不碰 production**，結束後自動清掉。

輸出範例：

```
TABLE                  PRODUCTION     RESTORED   STATUS
--------------------------------------------------------------------
chip_concentration            433          433   OK
daily_quotes                91524        91524   OK
...
✅ 演練通過 — 備份可還原
   實測 RTO：47 秒
```

### 演練記錄

| 日期 | 備份檔 | 結果 | RTO | 備註 |
|---|---|---|---|---|
| _待填_ | | | | 第一次演練 |

> 每次演練後把結果補進這張表。這張表本身就是「我真的驗證過」的證據，
> 面試被問到 RPO/RTO 時你有實測數字，而不是估的。

---

## 真的要還原到 production 時

```bash
cd /opt/stockradar

# 1. 停掉會寫入的服務（保留 postgres）
docker compose -f docker-compose.prod.yml stop api scheduler

# 2. 還原（--clean 會先砍掉既有物件）
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U stockradar -d stockradar --clean --if-exists --no-owner \
  < /opt/backups/stockradar_YYYYmmdd_HHMMSS.dump

# 3. 檢查
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U stockradar -d stockradar -c "SELECT MAX(trade_date), COUNT(*) FROM daily_quotes;"

# 4. 恢復服務
docker compose -f docker-compose.prod.yml start api scheduler
curl -s https://$DOMAIN/api/health; echo
```

---

## 下一步（Phase 2）

1. **異地複本**：`rclone` 上傳到 Cloudflare R2（10GB 免費、零 egress 費），
   保留策略：日備份 14 天、週備份 8 週。這是唯一能防「整台機器不見」的作法。
2. **告警**：備份失敗要主動通知（目前只會寫進 `backup.log`，沒人看就等於沒有）。
3. **自動化演練**：Phase 3 的 staging DB 每週從 prod 備份還原，順便就是自動演練。
