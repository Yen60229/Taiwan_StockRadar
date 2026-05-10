# StockRadar — 部署到 Hetzner VPS（完整步驟）

> 從開機到 HTTPS 上線，約 20-30 分鐘。

---

## 一、開機前準備（本機操作）

### 1. 建 GitHub Repo（如果還沒有）

```bash
# 在本機專案目錄
cd D:\Javascript-training\stockradar_From_Claude
git init
git add .
git commit -m "init: StockRadar v1"
git remote add origin https://github.com/YOUR_USERNAME/stockradar.git
git push -u origin main
```

> 注意：確認 `.gitignore` 有排除 `.env`（不要把密碼推上去）

`.gitignore` 至少要有：
```
.env
__pycache__/
*.pyc
logs/
```

### 2. 準備網域（選填，但強烈建議）

- Cloudflare、Namecheap、GoDaddy 買一個 domain（例如 `stockradar.tw`）
- 稍後拿到 VPS IP 後回來設 DNS A record

---

## 二、開 Hetzner 主機

### 推薦規格

| 方案 | CPU | RAM | 月費 | 適合場景 |
|------|-----|-----|------|---------|
| **CX22**（推薦） | 2 vCPU | 4 GB | ~€3.8 | 日常運作，夠用 |
| CX32 | 4 vCPU | 8 GB | ~€7.5 | 流量較大或多人使用 |

### 開機設定

1. 登入 [Hetzner Cloud Console](https://console.hetzner.cloud/)
2. 點 **Create Server**
3. 選擇：
   - **Location**：Falkenstein（EU-West，延遲低）或 Singapore（亞洲較近）
   - **Image**：Ubuntu **22.04** LTS
   - **Type**：CX22
   - **SSH Key**：貼上本機的 `~/.ssh/id_rsa.pub`（沒有就新增）
4. 建立後記下 **Public IP**（例如 `1.2.3.4`）

### 設定 DNS

到你的 domain 管理介面，加一筆 A record：

| Name | Type | Value |
|------|------|-------|
| `@` 或 `stockradar` | A | `1.2.3.4`（你的 VPS IP） |

> DNS 傳播約 5-30 分鐘，之後再啟動 Caddy 申請憑證。

---

## 三、VPS 初始設定（SSH 進去操作）

```bash
ssh root@1.2.3.4
```

### 1. 更新系統 + 防火牆

```bash
apt update && apt upgrade -y

# UFW 防火牆
ufw allow ssh      # 22/tcp
ufw allow 80/tcp   # HTTP（Caddy 用）
ufw allow 443/tcp  # HTTPS（Caddy 用）
ufw allow 443/udp  # HTTP/3 QUIC（Caddy 用）
ufw --force enable
ufw status
```

### 2. 建立非 root 使用者（安全性）

```bash
adduser jimmy                    # 設密碼
usermod -aG sudo jimmy
# 把 SSH key 複製過去
rsync --archive --chown=jimmy:jimmy ~/.ssh /home/jimmy

# 切換到 jimmy（之後全用這個帳號）
su - jimmy
```

### 3. 安裝 Docker

```bash
# 上傳腳本或直接貼內容
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/stockradar/main/scripts/install_docker.sh | bash

# 重新登入讓 docker group 生效
exit
ssh jimmy@1.2.3.4
docker version   # 確認無 sudo 可執行
```

---

## 四、部署程式

### 1. Clone repo

```bash
git clone https://github.com/YOUR_USERNAME/stockradar.git /opt/stockradar
cd /opt/stockradar
```

### 2. 建立 `.env`

```bash
cp /dev/null .env
nano .env
```

貼入以下內容（**替換全部 `...` 部分**）：

```bash
# === 必填 ===
DOMAIN=stockradar.tw              # 你的 domain（不含 https://）
DB_PASSWORD=...                   # 強密碼，例如：openssl rand -base64 32
SECRET_KEY=...                    # 更長的密碼，例如：openssl rand -base64 48

# === Email 週報（有 Resend 帳號才填）===
RESEND_API_KEY=re_...
EMAIL_FROM=report@stockradar.tw
TLS_EMAIL=your@gmail.com          # Let's Encrypt 通知信箱

# === 生產環境 ===
APP_ENV=production
```

快速生成密碼：
```bash
openssl rand -base64 32   # DB_PASSWORD 用
openssl rand -base64 48   # SECRET_KEY 用
```

### 3. 啟動服務

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

第一次 build 約 3-5 分鐘（下載 node/python image + 編譯前端）。

確認狀態：

```bash
docker compose -f docker-compose.prod.yml ps
```

應該看到 5 個服務都是 `Up`：
```
NAME          STATUS
postgres      Up (healthy)
api           Up
scheduler     Up
frontend      Up
caddy         Up
```

### 4. 回補 2 個月歷史均量資料（第一次部署必做）

```bash
# 安裝 yfinance（回補腳本需要）
docker compose -f docker-compose.prod.yml exec api pip install yfinance -q

# 執行回補（約 20-30 分鐘，TWSE+TPEX 各約 1000 支）
docker compose -f docker-compose.prod.yml exec api \
    python scripts/backfill_history.py
```

輸出最後看到 `✅ 回補完成` 即成功。

---

## 五、驗收

```bash
# HTTPS API 健康檢查
curl https://stockradar.tw/api/health

# 預期回應
{"status": "ok", "timestamp": "2026-05-09T12:00:00"}
```

打開瀏覽器：`https://stockradar.tw` → 看到選股雷達介面

---

## 六、日常維運

### 手動跑選股（不等排程）

```bash
cd /opt/stockradar
docker compose -f docker-compose.prod.yml exec scheduler sh /app/scripts/run_now.sh
```

### 更新程式碼

```bash
cd /opt/stockradar
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

### 查看 log

```bash
# 即時 log（所有服務）
docker compose -f docker-compose.prod.yml logs -f

# 只看 API
docker compose -f docker-compose.prod.yml logs -f api

# 排程執行紀錄
ls -la logs/
tail -100 logs/scheduled_20260509.log
```

### 資料庫備份

```bash
# 備份到本機
docker compose -f docker-compose.prod.yml exec postgres \
    pg_dump -U stockradar stockradar \
    | gzip > backup_$(date +%Y%m%d).sql.gz

# 下載到本機
scp jimmy@1.2.3.4:/opt/stockradar/backup_*.sql.gz ./
```

### 排程確認

```bash
# 確認 cron 已設定
docker compose -f docker-compose.prod.yml exec scheduler crontab -l
```

---

## 七、常見問題

**Q: Caddy 申請憑證失敗（`TLS handshake error`）**

確認 DNS 已傳播完成：
```bash
nslookup stockradar.tw
# 應該看到 VPS IP
```
確認防火牆 80/443 已開放：
```bash
ufw status
```

**Q: API 回傳 502 Bad Gateway**

```bash
docker compose -f docker-compose.prod.yml logs api | tail -30
```

**Q: 回補失敗（yfinance rate limit）**

批次大小調小後重試：
```bash
BATCH_SIZE=5 docker compose -f docker-compose.prod.yml exec api \
    python scripts/backfill_history.py
```

**Q: 前端頁面有但資料是空的**

手動跑一次 pipeline：
```bash
docker compose -f docker-compose.prod.yml exec scheduler sh /app/scripts/run_now.sh
```

---

## 附錄：本機測試生產版（選做）

```bash
# 模擬生產環境（不含真實 domain/HTTPS）
DOMAIN=localhost docker compose -f docker-compose.prod.yml up -d

# Caddy 會嘗試申請憑證（會失敗，但 frontend 還是跑在 80）
curl http://localhost/api/health
```
