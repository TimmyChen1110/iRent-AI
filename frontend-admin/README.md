# frontend-admin — 舊版整備中心前端（已由 fleet-ops-center 取代）

> **2026-10-06 起不再維護。** 正式的環節三管理者介面改為 `fleet-ops-center/`（Next.js + 3D Digital Twin），
> 同樣接 `backend/app/ops_api.py`（`/api/ops/*`），build 後由 FastAPI 於 `http://localhost:8000/ops` 提供。
> 此目錄保留作為參考（Vite + React 版），Docker 與 `backend/app/static/ops` 已改為使用 fleet-ops-center 的靜態匯出。

# frontend-admin — iRent 整備中心（環節三管理者介面）

React + TypeScript + Vite + motion。設計與 API 規劃見 `環節三_營運通知與整備/UI_規劃.md`。

```bash
npm install
npm run dev        # http://localhost:5173/ops/ ，/api 與 /photos 代理到 localhost:8000
npm run build      # 輸出到 backend/app/static/ops/ → 由 FastAPI 於 http://localhost:8000/ops 提供
```

後端需先啟動（`make up` 或 `cd backend/app && uvicorn server:app`）。API 皆在 `/api/ops/*`（`backend/app/ops_api.py`）。

路由：`/ops/inbox` 通知中心、`/ops/board` 看板、`/ops/tasks/:id` 任務詳情、`/ops/fleet` 派單狀態、`/ops/insights` 營運洞察、`/ops/people`、`/ops/settings`、**`/ops/m` 站點人員手機版**（無側欄）。

Docker：`docker compose build` 會在第一階段用 node 建置前端並複製進 image，不需要先在本機 build。
