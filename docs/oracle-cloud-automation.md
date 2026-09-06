# Oracle Cloud Ampere A1 自動化搶機腳本

> **場景**：Oracle Cloud Always Free 方案提供 Ampere A1 VM（4 OCPU / 24 GB RAM，永久免費），  
> 但熱門地區（東京）長期顯示「Out of host capacity」——無法透過 Console 直接建立。  
> 本文記錄如何用一台已成功建立的 E2.1.Micro VM + Shell 腳本，  
> 全自動輪詢 Resource Manager Stack，搶到 Ampere 後寄 Gmail 通知。

---

## 技術架構概覽

```
本地 Windows
    │ SSH
    ▼
E2.1.Micro VM (158.179.183.117) ← 已建立的免費 VM，做跳板
    │
    ├─ OCI CLI（已安裝）
    ├─ ociauto.sh（Shell 腳本）
    ├─ cron（每 2 分鐘觸發）
    └─ msmtp（Gmail 通知）
         │ Resource Manager Stack Apply Job
         ▼
    Oracle Cloud API → 嘗試建立 Ampere A1 VM
```

---

## 學到的技術與方法

### 1. OCI CLI 安裝與 API 金鑰設定

```bash
# 在 Ubuntu VM 上安裝 OCI CLI
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"

# 金鑰設定（~/.oci/config）
[DEFAULT]
user=ocid1.user.oc1..xxxxx
fingerprint=xx:xx:xx:...
tenancy=ocid1.tenancy.oc1..xxxxx
region=ap-tokyo-1
key_file=~/.oci/oci_api_key_nopass.pem
```

**重點**：自動化腳本不能用需要輸入 passphrase 的 RSA 金鑰。  
解法：用 `openssl` 轉出不含 passphrase 的版本：

```bash
openssl rsa -in ~/.oci/oci_api_key.pem -out ~/.oci/oci_api_key_nopass.pem
chmod 600 ~/.oci/oci_api_key_nopass.pem
```

---

### 2. Resource Manager Stack（Terraform 託管）

直接呼叫 Compute API 建 VM 時，Oracle 對高頻請求有嚴格限制（400 CannotParseRequest、429 Too Many Requests）。  
改用 **Resource Manager Stack**（Oracle 的 Terraform 封裝）更穩定：

```bash
# 對已存在的 Stack 發出 Apply Job（嘗試建立資源）
oci resource-manager job create-apply-job \
  --stack-id "ocid1.ormstack.oc1.ap-tokyo-1.xxxxx" \
  --execution-plan-strategy AUTO_APPROVED

# 查詢 Job 狀態
oci resource-manager job get --job-id "$JOB_ID" \
  --query 'data."lifecycle-state"' --raw-output
```

**Stack 的優勢**：
- Terraform state 由 Oracle 管理，冪等性好
- 失敗時自動 Rollback，不會留下殘留資源
- Apply Job 非同步，不會 timeout

---

### 3. Shell 腳本設計重點

```bash
#!/bin/bash
# ⚠️ cron 不會載入 .bashrc，PATH 必須手動設定
export PATH=$PATH:/home/ubuntu/bin

STACK_ID="ocid1.ormstack.oc1.ap-tokyo-1.xxxxx"
LOG="$HOME/ociauto.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$TIMESTAMP] $1" >> "$LOG"; }

# timeout 防止 OCI CLI 卡死（Oracle API 偶爾不回應）
JOB_JSON=$(timeout 60 oci resource-manager job create-apply-job \
  --stack-id "$STACK_ID" \
  --execution-plan-strategy AUTO_APPROVED 2>&1)

JOB_ID=$(echo "$JOB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])" 2>/dev/null)

# 輪詢直到 SUCCEEDED 或 FAILED
for i in $(seq 1 20); do
  sleep 30
  STATUS=$(timeout 60 oci resource-manager job get --job-id "$JOB_ID" \
    --query 'data."lifecycle-state"' --raw-output 2>/dev/null)
  log "Job $JOB_ID status: $STATUS"
  if [ "$STATUS" = "SUCCEEDED" ]; then
    # 成功 → 寄信 → 移除 cron
    echo "Subject: StockRadar Ampere VM 建立成功！" | msmtp jimmy880830@gmail.com
    crontab -r
    exit 0
  elif [ "$STATUS" = "FAILED" ]; then
    log "Out of capacity，下次再試"
    exit 1
  fi
done
```

**關鍵學習點**：

| 問題 | 原因 | 解法 |
|---|---|---|
| `oci: command not found`（在 cron 中） | cron 不載入 `.bashrc` | 腳本開頭加 `export PATH=$PATH:/home/ubuntu/bin` |
| OCI CLI 無限卡死 | Oracle API 偶爾不回應 | 每個 CLI 命令加 `timeout 60` |
| passphrase 被要求輸入 | RSA 金鑰有密碼 | `openssl rsa` 轉出無密碼版 |
| Too many requests (429) | 每分鐘觸發太頻繁 | 改為每 2 分鐘一次 |
| CRLF 換行錯誤 | Windows Notepad 存成 CRLF | `sed -i 's/\r//' ~/ociauto.sh` 轉 LF |

---

### 4. cron 排程設定

```bash
# 編輯 crontab
crontab -e

# 每 10 分鐘執行一次腳本，stderr 導入同一 log
# （間隔太短會觸發 429 TooManyRequests，10 分鐘為實測穩定值）
*/10 * * * * /bin/bash /home/ubuntu/ociauto.sh >> /home/ubuntu/ociauto.log 2>&1
```

確認排程已生效：
```bash
crontab -l          # 查看目前排程
tail -f ~/ociauto.log   # 即時監控執行記錄
```

**重要**：`crontab -r` 可一次移除所有排程。腳本在成功後自動呼叫，避免繼續消耗資源。

---

### 5. msmtp + Gmail 通知

```bash
# 安裝
sudo apt install msmtp msmtp-mta -y

# ~/.msmtprc 設定
account default
host smtp.gmail.com
port 587
tls on
tls_starttls on
auth on
user jimmy880830@gmail.com
password YOUR_16_CHAR_APP_PASSWORD    # Gmail App Password（非登入密碼）
from jimmy880830@gmail.com
logfile ~/.msmtp.log

# 發送測試信
echo "Subject: 測試" | msmtp jimmy880830@gmail.com
```

**Gmail App Password 說明**：需在 Google 帳戶 → 安全性 → 兩步驟驗證開啟後，才能建立「應用程式密碼」（16 碼），用於第三方 SMTP 工具。

---

### 6. SCP 跨機器傳輸 OCI 憑證

由於 OCI API 金鑰只在本機，需安全傳輸到 VM：

```bash
# Windows Git Bash（本機）→ Oracle VM
scp -i /d/User/Downloads/ssh-key-2026-05-09.key \
    ~/.oci/config \
    ~/.oci/oci_api_key.pem \
    ubuntu@158.179.183.117:~/.oci/
```

---

## 整體流程圖

```
[本機 Windows]
  └─ 建立 Oracle E2.1.Micro VM（Tokyo）
  └─ SCP 上傳 OCI 憑證
  └─ SSH 進 VM，安裝 OCI CLI + msmtp

[E2.1.Micro VM 持續運行]
  └─ cron 每 2 分鐘觸發 ociauto.sh
       └─ 呼叫 OCI Resource Manager Stack Apply Job
       └─ 輪詢 Job 狀態
            ├─ FAILED（Out of capacity）→ 等下次 cron
            └─ SUCCEEDED（搶到！）
                 └─ msmtp 寄 Gmail 通知
                 └─ crontab -r 自動停止排程
```

---

## 7. 2026-06 政策異動：Always Free 規格上限調降

2026 年 6 月，Oracle 調整 Always Free Resources 政策，  
Ampere A1 (ARM) 免費上限從 **4 OCPU + 24 GB** 降為 **2 OCPU + 12 GB**。

原本的 Stack Terraform 設定如果寫死 4/24，搶到也會因超過上限而失敗，  
必須把規格調整到新上限內（這裡直接升到滿配 2/12）。

### 透過 CLI 修改 Stack 的 Terraform 設定（免進 Console）

Stack 的 OCPU/記憶體是寫死在 `main.tf` 的 `shape_config`，**不是變數**，  
所以無法用 `--variables` 改，必須下載 → 改 `.tf` → 重新打包上傳。

```bash
# ① 下載 Stack 目前的 Terraform 設定
oci resource-manager stack get-stack-tf-config \
  --stack-id "$STACK_ID" --file ~/stack.zip

# ② 解開
mkdir -p ~/stack_tf && cd ~/stack_tf && unzip -o ~/stack.zip

# ③ 確認 shape_config 位置
grep -n "ocpus\|memory_in_gbs" ~/stack_tf/main.tf
#   main.tf:  memory_in_gbs = "6"
#   main.tf:  ocpus = "1"

# ④ 改成新上限 2 OCPU / 12 GB
sed -i 's/memory_in_gbs = "6"/memory_in_gbs = "12"/' ~/stack_tf/main.tf
sed -i 's/ocpus = "1"/ocpus = "2"/'                 ~/stack_tf/main.tf

# ⑤ 從資料夾「內部」重新打包（main.tf 必須在 zip 根目錄）
cd ~/stack_tf && zip -r ~/stack_new.zip .

# ⑥ 上傳更新 Stack（--config-source 只吃 .zip，不吃資料夾）
oci resource-manager stack update \
  --stack-id "$STACK_ID" \
  --config-source ~/stack_new.zip --force
```

**關鍵學習點**：

| 問題 | 原因 | 解法 |
|---|---|---|
| Stack 規格無法用 `--variables` 改 | OCPU/記憶體寫死在 `main.tf` | 下載 `.tf` → `sed` 改 → 重新上傳 |
| `Config source must be a .zip file` | `--config-source` 指向資料夾 | 先 `zip -r` 打包成 .zip |
| `main.tf` 跑到 zip 子資料夾裡 | 打包外層資料夾 | `cd` 進資料夾再 `zip -r out.zip .` |

### 如何分辨「設定錯」與「缺貨」

改完後手動跑一次，看 Job 的 Terraform log：

```bash
oci resource-manager job get-job-logs --job-id "$JOB_ID" \
  --query 'data[*].message' --raw-output | tail -25
```

| Log 訊息 | 意義 | 動作 |
|---|---|---|
| `CannotParseRequest (400)` | 請求格式錯（欄位、shape-config）| 必須修設定 |
| `Plan: 1 to add` + `Out of host capacity (500)` | **設定全對，只差有貨** | 繼續輪詢搶 |

看到 `Plan: 1 to add` 才代表 Terraform 驗證通過，  
`Out of host capacity` 是最理想的失敗——只要持續搶就會成功。

---

## 整體流程圖

```
[本機 Windows]
  └─ 建立 Oracle E2.1.Micro VM（Tokyo）
  └─ SCP 上傳 OCI 憑證
  └─ SSH 進 VM，安裝 OCI CLI + msmtp

[E2.1.Micro VM 持續運行（搶機伺服器）]
  └─ cron 每 10 分鐘觸發 ociauto.sh
       └─ 呼叫 OCI Resource Manager Stack Apply Job（建 2C/12G Ampere）
       └─ 輪詢 Job 狀態
            ├─ FAILED（Out of capacity）→ 等下次 cron
            └─ SUCCEEDED（搶到！）
                 └─ msmtp 寄 Gmail 通知
                 └─ crontab -r 自動停止排程
```

---

## 心得

- Oracle Always Free 的 Ampere A1 VM 在熱門地區長期缺貨，**輪詢搶機是目前社群最常見的合法解法**
- 全程使用免費資源（E2.1.Micro 跳板 VM + cron），搶到後整個 Always Free 方案仍維持 $0
- 這次實作深化了對 **Linux cron 環境限制**、**OCI CLI API 呼叫**、**Terraform 託管** 的理解
- 雲端供應商的免費方案規格會異動（2026-06 從 4/24 降到 2/12），  
  把規格寫在 IaC（Terraform）裡的好處是**改一個數字就能調整**，不必重建整個流程
- 未來 Ampere VM 到手後，將部署 StockRadar（FastAPI + PostgreSQL + React）作為正式對外服務

---

*最後更新：2026-06-26*
