# JEV Telegram 條件過濾器

![介面](image/capture1.png)

![介面](image/capture2.png)

![執行](image/execute.gif)

本機的 Telegram 條件過濾器。FastAPI 與 SQLite 聽在 `127.0.0.1:18721`。一個 Telegram 帳號（Telethon `StringSession`），訊息存在本機。任務把訊息分批送給 Jev（TypeSafe）或本機 Laya；新任務的預設批次大小是 50。畫面只留命中；圖片在命中之後才下載。

介面語系是 `zh-Hant`、`zh-Hans`、`en`。內建任務範本跟著目前語系。

## 開發

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node.js 20+。Telegram 的 `api_id` / `api_hash` 向 [my.telegram.org](https://my.telegram.org) 申請。TypeSafe API key 在設定頁寫入後端。

在專案根目錄啟動後端：

```powershell
uv sync
uv run python -m server
```

另開一個終端啟動前端。開發時瀏覽器開 `http://localhost:5173`（Vite 綁定 `[::1]`）。`/api`（含 SSE `/api/events`）會代理到 FastAPI。

```powershell
cd web
npm install
npm run dev
```

資料目錄預設是專案裡的 `data/`。要用別的路徑時設定 `JEV_TG_DATA_DIR`。設定頁還沒寫入金鑰時，後端會讀環境變數 `TYPESAFE_API_KEY`。

Laya 是選用本機模型，權重不在這個 repo。需要時再裝，第一次判斷才會下載：

```powershell
uv sync --extra laya
```

## 系統匣

系統匣開的仍是同一個網頁介面。選單會開 `http://127.0.0.1:18721/`，也可以結束程式。

本機先建好前端，再啟動系統匣：

```powershell
cd web
npm run build
cd ..
uv run --extra tray python -m server.tray
```

打包後的資料目錄：Windows 是 `%APPDATA%\jev_tg`，macOS 是 `~/Library/Application Support/jev_tg`。開發時資料仍在 `data/`，一樣可用 `JEV_TG_DATA_DIR` 覆寫。

## 自動發布

`.github/workflows/package.yml` 在 push 到 `main` 或 `master` 時，建出 Windows `jev-tg.exe` 與 macOS `JEV-Telegram-Filter.dmg`。兩個檔案都在時，會打 tag `vYYYYMMDD.HHMMSS` 並發布 GitHub Release。也可以手動跑 `workflow_dispatch`。commit 訊息含 `[skip release]` 會略過這次發布。

## 不要提交

這些已在 `.gitignore`，不要上傳：

- `data/`（SQLite 裡有 API key，還有工作階段與設定）
- `.env` 與 `.env.*`
- Telegram session 檔（`*.session`、`*.session.txt`）
