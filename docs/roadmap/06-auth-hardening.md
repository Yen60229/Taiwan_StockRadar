# 帳號安全強化計畫：註冊核准制 + 管理員兩步驟驗證

> 起因：站台上線後，「知道網址的人就連得到」。
> 這份計畫把它變成：**只有你核准過的人能用，而你自己的管理員帳號需要密碼＋手機驗證碼才進得來。**
>
> 定位：這是藍圖 Phase 2「可靠性與開放註冊」裡 auth 工作的具體規格，
> 與 ADR-6（token 存放策略）、補強-3（email 驗證 / 忘記密碼 / 刪帳號）並行不衝突。

---

## 0. 現況：門其實沒關

| 面向 | 現況 | 風險 |
|---|---|---|
| 前端 | `/` 與 `/stock/:code` 有 `PrivateRoute`，沒 token 會被導去登入 | 看起來有門 |
| **API** | `/api/screen` 用 `get_current_user_optional`，`/api/stocks/*` 完全沒驗證 | **`curl` 直接打 API 就拿到全部資料**，前端的門是裝飾 |
| 註冊 | 任何人 `POST /api/auth/register` 立刻拿到 token（自動登入） | 陌生人 30 秒內就是正式使用者 |
| 角色 | 沒有 admin 概念 | 你跟任何註冊者權限相同 |
| 管理員登入 | 只有密碼 | 密碼外洩 = 全部外洩 |
| 暴力破解 | 沒有速率限制 | 2FA 沒有 rate limit 等於沒做 |
| Token | localStorage、7 天有效 | XSS 可竊取（ADR-6 已排定處理） |

「知道網址就連得到」其實是三層問題，這份計畫三層都處理：
1. **API 沒鎖** → 全部端點要求登入
2. **誰都能註冊** → 註冊後進入 `pending`，你核准才生效
3. **管理員只靠密碼** → TOTP 兩步驟驗證，管理員強制啟用

---

## 1. 範圍

### 做
- 使用者 **角色**（`admin` / `user`）與 **狀態**（`pending` / `active` / `rejected` / `disabled`）
- 註冊 → `pending`，不發 token；**管理員核准**後才能登入
- 管理員 **TOTP 兩步驟驗證**（Google Authenticator / Authy / 1Password 都可），附一次性 **備用碼**
- 所有資料 API 要求登入（依決策 D1）
- 登入 / 2FA 驗證端點 **速率限制**
- 前端：註冊送出後的「等待核准」畫面、登入時的驗證碼輸入、**管理後台**（核准 / 拒絕 / 停用）、**2FA 設定頁**（QR code + 備用碼）
- 通知：有人申請 → 寄信給你；核准 → 寄信給對方

### 不做（且為什麼）
| 項目 | 原因 |
|---|---|
| 簡訊 2FA | 要錢、SIM swap 風險、台灣號碼服務商麻煩；TOTP 免費且更安全 |
| WebAuthn / Passkey | 最強，但前端複雜度高；等 2FA 跑順、有真實用戶再升級 |
| Google / GitHub 登入 | 核准制下沒有優勢（還是要你按核准）；之後要做也能疊上去 |
| 一般使用者強制 2FA | 對「看選股表」的用戶太重；改為選用（決策 D2） |
| Email 驗證信 | 核准制本身就是人工驗證；Phase 2 既有項目，屆時再補 |

---

## 2. 三個要先決定的事

| # | 問題 | 選項 | 建議 |
|---|---|---|---|
| **D1** | 選股表要不要公開？ | (a) 全部私有，登入才看得到<br>(b) 維持現狀（前端有門、API 沒門）<br>(c) 公開部分（如前 20 筆），完整版要登入 | **(a)**，加一頁**公開的 landing page**（專案介紹＋截圖＋「申請帳號」）給作品集用；面試官要看 demo 就開一個你核准過的 demo 帳號給他 |
| **D2** | 一般使用者要不要 2FA？ | 強制 / 選用 / 不提供 | **管理員強制、使用者選用**。強制會嚇跑用戶，但不提供等於留後門 |
| **D3** | 註冊通知怎麼寄？ | Resend（要申請 API key）/ Gmail SMTP（你已有 App Password）/ 不寄，只看後台 | **先用 Gmail SMTP**：`notifier/send_email.py` 已有 SMTP 備援，`.env` 填 `SMTP_USER` / `SMTP_PASS` 就能用，零新增依賴 |

> 這三個決定不影響資料模型與 API 設計，只影響前端與設定，可以邊做邊定。

---

## 3. 設計

### 3.1 資料模型（需要 Alembic migration）

```sql
ALTER TABLE users
  ADD COLUMN role            text        NOT NULL DEFAULT 'user',     -- 'user' | 'admin'
  ADD COLUMN status          text        NOT NULL DEFAULT 'pending',  -- 'pending' | 'active' | 'rejected' | 'disabled'
  ADD COLUMN totp_secret_enc text,                                    -- Fernet 加密後的 TOTP secret
  ADD COLUMN totp_enabled    boolean     NOT NULL DEFAULT false,
  ADD COLUMN approved_at     timestamptz,
  ADD COLUMN approved_by     uuid REFERENCES users(id),
  ADD COLUMN last_login_at   timestamptz;

-- 既有使用者（目前只有你）一律視為已核准，不然 migration 一跑你就登不進去
UPDATE users SET status = 'active';

CREATE TABLE recovery_codes (
  id        bigserial PRIMARY KEY,
  user_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash text NOT NULL,        -- bcrypt；備用碼跟密碼一樣不能明文存
  used_at   timestamptz
);
CREATE INDEX ON recovery_codes(user_id) WHERE used_at IS NULL;
```

管理員的產生不走 UI（避免「第一個註冊的人自動變 admin」這種經典漏洞）：

```bash
docker compose -f docker-compose.prod.yml exec api python -m scripts.make_admin you@example.com
# → role='admin', status='active'；下次登入會被要求設定 2FA
```

### 3.2 狀態機

```
        註冊
         │
         ▼
     ┌─────────┐   管理員核准   ┌─────────┐   管理員停用   ┌──────────┐
     │ pending │ ────────────▶ │ active  │ ────────────▶ │ disabled │
     └─────────┘               └─────────┘               └──────────┘
         │                          ▲                          │
         │ 管理員拒絕                └──────── 重新啟用 ─────────┘
         ▼
     ┌──────────┐
     │ rejected │   （可再申請：視同新註冊，覆蓋舊列）
     └──────────┘
```

只有 `active` 能登入。其他狀態登入一律回 `403`，訊息區分「等待核准」與「帳號已停用」。

### 3.3 登入流程（含 2FA）

```
POST /api/auth/login  {email, password}
  │
  ├─ 密碼錯 / 帳號不存在 ──────────────▶ 401（訊息一致，不透露帳號是否存在）
  ├─ status != active ─────────────────▶ 403 {code: "pending_approval" | "disabled"}
  ├─ role=admin 且尚未啟用 2FA ─────────▶ 200 {requires_2fa_setup: true, setup_token}
  │                                        （前端導去 /settings/2fa；設好之前不能用管理功能）
  ├─ totp_enabled ─────────────────────▶ 200 {requires_2fa: true, challenge_token}
  │                                             │
  │                                             ▼
  │                              POST /api/auth/2fa/verify {challenge_token, code}
  │                                             │
  │                                             ├─ code 正確（TOTP 或未用過的備用碼）▶ 200 {access_token, user}
  │                                             └─ 錯 ──────────────────────────────▶ 401（計入 rate limit）
  │
  └─ 一般使用者、未啟用 2FA ──────────────▶ 200 {access_token, user}
```

`challenge_token` 是一個 **5 分鐘、scope=2fa** 的短命 JWT，只能拿來換 access token，不能打任何其他 API。

### 3.4 API 端點

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| POST | `/api/auth/register` | 公開 | 建立 `pending` 使用者，**回 201 但不回 token**；寄信通知管理員 |
| POST | `/api/auth/login` | 公開 | 見 3.3 |
| POST | `/api/auth/2fa/verify` | challenge_token | 驗 TOTP 或備用碼，換 access token |
| POST | `/api/auth/2fa/setup` | 登入 | 產生 secret，回 `otpauth://` URI（前端畫 QR）；**尚未啟用** |
| POST | `/api/auth/2fa/confirm` | 登入 | 用 App 產生的 code 確認一次 → 啟用，回 8 組備用碼（**只顯示這一次**） |
| POST | `/api/auth/2fa/disable` | 登入 + code | 一般使用者可關；**admin 不可關**（回 403） |
| POST | `/api/auth/2fa/recovery/regenerate` | 登入 + code | 重新產生備用碼，舊的全部作廢 |
| GET | `/api/admin/users?status=pending` | admin + 2FA | 待核准清單 |
| POST | `/api/admin/users/{id}/approve` | admin + 2FA | → active，寄信給對方 |
| POST | `/api/admin/users/{id}/reject` | admin + 2FA | → rejected |
| POST | `/api/admin/users/{id}/disable` | admin + 2FA | → disabled（不能對自己） |
| GET | `/api/screen`、`/api/stocks/*`、`/api/watchlist` | **登入**（D1=a） | 把 `get_current_user_optional` 換成 `get_current_user` |

「admin + 2FA」＝ `role == 'admin' AND totp_enabled`；沒設 2FA 的 admin 打管理端點回 403 `two_factor_required`。

### 3.5 前端

| 頁面 / 元件 | 內容 |
|---|---|
| `LoginPage` | 註冊成功 → 「已送出申請，管理員核准後會收到通知」；登入回 `pending_approval` → 同樣訊息；回 `requires_2fa` → 切換成 6 碼輸入框（含「用備用碼」連結）；回 `requires_2fa_setup` → 導去設定頁 |
| `TwoFactorSetupPage`（`/settings/2fa`） | 顯示 QR（`qrcode.react`，純前端產生）＋手動輸入用的 secret → 輸入 App 的 code 確認 → 顯示 8 組備用碼並要求「我已存好」才能離開 |
| `AdminPage`（`/admin`） | 待核准清單（email / 姓名 / 申請時間 / 核准 / 拒絕）、全部使用者清單（狀態 / 角色 / 最後登入 / 停用） |
| `AdminRoute` | `PrivateRoute` 的加強版：要 `user.role === 'admin'` |
| `LandingPage`（`/`，D1=a 時） | 公開：專案介紹、截圖、技術棧、「申請帳號」按鈕；登入後 `/` 才是 Dashboard |
| `api/client.ts` | `User` 型別加 `role` / `status` / `totp_enabled`；401 之外也處理 403 的 `code` |

### 3.6 安全細節（每一條都有對應的測試）

| 項目 | 做法 | 為什麼 |
|---|---|---|
| TOTP secret 存放 | Fernet 加密，金鑰用獨立的 `TOTP_ENC_KEY` 環境變數（不共用 `SECRET_KEY`） | DB 外洩時 secret 不是明文；輪換 JWT 金鑰不會弄壞大家的 2FA |
| TOTP 驗證 | `pyotp`，30 秒一格，`valid_window=1`（前後各容許一格） | 手機時間差幾秒不該被鎖在外面 |
| 重放防護 | 記住每個 user 最後一次成功的 TOTP 時間格，同一格不能用第二次 | 同一組 code 30 秒內被截走也不能重用 |
| 備用碼 | 8 組、每組 10 字元、bcrypt 雜湊、單次使用、用掉就標記 `used_at` | 手機掉了還進得來；DB 外洩看不到明文 |
| challenge_token | 5 分鐘、`scope: "2fa"`、只被 `/2fa/verify` 接受 | 密碼對了但 2FA 沒過，這個 token 不能做任何事 |
| 速率限制 | `slowapi`（in-memory，單實例夠用，符合 ADR-1）：`/login` 每 IP 5 次/分、`/2fa/verify` 每 challenge 5 次後作廢 | 6 碼 = 100 萬種，沒限制的話暴力破解幾小時就完 |
| 錯誤訊息 | 帳號不存在與密碼錯回**同一句**；`pending` 與 `disabled` 才區分 | 不讓人用登入頁探測誰有帳號 |
| 第一個 admin | 只能用 CLI 腳本設定，UI 不提供 | 避免「第一個註冊者自動成為 admin」 |
| admin 自我保護 | 不能停用自己、不能關掉自己的 2FA | 避免把自己鎖在外面或降級 |
| 審計 | 核准 / 拒絕 / 停用 / 2FA 啟用與關閉 → 寫 structured log（含 actor、target、時間） | 事後查得出「誰在什麼時候放誰進來」 |

---

## 4. 威脅模型：擋得住什麼、擋不住什麼

| 威脅 | 結果 |
|---|---|
| 陌生人知道網址 | ✅ 看到 landing page，註冊後卡在 pending，API 一律 401 |
| 你的密碼外洩 | ✅ 沒有你手機上的 App 進不來 |
| 對登入頁暴力破解 | ✅ 速率限制擋下 |
| 資料庫被拖走 | ✅ 密碼與備用碼是 bcrypt、TOTP secret 是加密的；⚠️ 但攻擊者拿到 `TOTP_ENC_KEY` 就能解 → 金鑰只放 `.env`，不進 git、不進 image |
| XSS 偷走瀏覽器裡的 token | ❌ 這份計畫不處理；**ADR-6（httpOnly cookie）才是解法**，排在本計畫之後 |
| 即時釣魚（假登入頁轉送你的 TOTP code） | ❌ TOTP 天生擋不住；要 WebAuthn / Passkey，列為後續 |
| 你的手機遺失 | ✅ 備用碼；兩者都丟 → 用 CLI 腳本 `python -m scripts.reset_2fa` 重設（需要 SSH 進機器，這本身就是一道門） |

---

## 5. 實作順序與工時

> 工時依 ADR-11 的校準原則（先前 P0 估 10h 實際 20–25h）估得保守。
> 每個 milestone 結束都是可部署、有價值的狀態，不必全部做完才上線。

### M0｜前置（~6h）—— 沒有這兩樣，後面每一步都在裸奔
- [ ] **Alembic baseline**：`alembic init` → 從現有 models autogenerate 第一版 → `deploy.sh` 改跑 `alembic upgrade head`。本計畫要改 `users` 表、加 `recovery_codes` 表，這就是藍圖一直說「該導入 Alembic」的那個時刻
- [ ] **DB 測試地基**：CI 加 `services: postgres:16`，`conftest.py` 加 async session fixture（每個測試在 transaction 內跑完 rollback）。目前 70 個測試全是離線的，auth / admin 流程一定要打真的 DB

### M1｜先把門關上（~10h）—— 做完這步「知道網址就連得到」就解決了
- [ ] migration：`role` / `status` / `approved_*` / `last_login_at`
- [ ] `register` 改為建立 `pending`、不回 token；`login` 檢查 `status`
- [ ] 所有資料 API 改 `get_current_user`（D1=a）
- [ ] `scripts/make_admin.py`
- [ ] `/api/admin/users` 三個端點 + `require_admin` dependency
- [ ] 前端：註冊後訊息、`pending` 訊息、`AdminPage`、`AdminRoute`、`LandingPage`（D1=a）
- [ ] 通知信：申請 → 管理員、核准 → 使用者（用 Gmail SMTP，D3）
- [ ] 測試：register 不回 token、pending 登入 403、非 admin 打 admin 端點 403、核准後可登入、admin 不能停用自己

### M2｜管理員 2FA（~12h）
- [ ] migration：`totp_secret_enc` / `totp_enabled` / `recovery_codes`
- [ ] `pyotp` + `cryptography.fernet`；`TOTP_ENC_KEY` 進 `.env.example` 與 `deps.py` 啟動檢查
- [ ] `/2fa/setup` `/confirm` `/verify` `/disable` `/recovery/regenerate`
- [ ] `login` 分流（3.3）；`require_admin` 加上 `totp_enabled` 檢查
- [ ] `scripts/reset_2fa.py`（救援用）
- [ ] 前端：`TwoFactorSetupPage`、登入頁的驗證碼 / 備用碼輸入
- [ ] 測試：正確 code 通過、錯誤 code 401、**同一格 code 重放被拒**、備用碼只能用一次、admin 未設 2FA 打管理端點 403、admin 不能 disable、challenge_token 不能打其他 API、過期 challenge 401

### M3｜收尾（~8h）
- [ ] `slowapi` 速率限制 + 測試（第 6 次被擋）
- [ ] 審計 log
- [ ] `docs/` 補使用者流程說明（申請 → 等核准 → 登入 → 管理員設 2FA）
- [ ] **銜接 ADR-6**：access token 改 30 分鐘 + refresh token 走 httpOnly cookie。本計畫刻意讓 2FA 的回傳格式與 token 存放方式無關，屆時只動 `deps.py` 與 `client.ts`，2FA 流程不用重寫

**合計約 36h，以每週 8–12h 計 ≈ 4 週。** M1 做完即可上線，M2 / M3 可以在已上線的狀態下逐步加。

---

## 6. 驗收標準

- [ ] 未登入 `curl https://<domain>/api/screen` → 401
- [ ] 陌生人註冊 → 收到「等待核准」；你的信箱收到申請通知；對方此時登入 → 403 `pending_approval`
- [ ] 你在 `/admin` 按核准 → 對方收到信，登入成功
- [ ] 你登入：密碼正確後跳出驗證碼框；App 的 6 碼通過；**同一組 6 碼第二次用被拒**；備用碼用一次後失效
- [ ] 沒設 2FA 的 admin（用 `make_admin` 新建一個測試）打 `/api/admin/*` → 403
- [ ] 對 `/api/auth/login` 連打 6 次錯密碼 → 第 6 次 429
- [ ] 以上每一條都有對應的 pytest，CI 綠燈
- [ ] 手機遺失演練：用備用碼登入 → `regenerate` 換新備用碼；全部遺失 → SSH 跑 `reset_2fa` 重設

---

## 7. 與既有藍圖的關係

| 既有項目 | 關係 |
|---|---|
| ADR-6 token 策略 | 本計畫的 M3 銜接它；2FA 回傳格式與 token 存放無關，不會重工 |
| ADR-1 不引入 Redis | 速率限制用 slowapi in-memory，單一 API 實例足夠 |
| 補強-3（email 驗證 / 忘記密碼 / 刪帳號） | 核准制先取代 email 驗證的角色；忘記密碼與刪帳號仍照 Phase 2 排程 |
| 補強-1（免責聲明 / 隱私政策） | `LandingPage` 與註冊頁是放這兩樣的自然位置，一併處理 |
| Phase 1 尚未完成的 Alembic | 被本計畫的 M0 強制推進 |
| `05-review` 的 DB 測試待補 | 同上，M0 一併補上 |

*建立：2026-09-07*
