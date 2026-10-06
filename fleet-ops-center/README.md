# iRent 整備中心 · AI 車隊營運中心（fleet-ops-center）

環節三的**正式管理者介面**：接真實後端（`backend/app/ops_api.py`、`/api/ops/*`），
把 AI 還車檢測案件、人工裁決、整備任務派工與通知，放進多尺度 3D Digital Twin（台灣 → 台北 → 車輛 → 損傷位置）。

## 執行

```bash
# 1) 後端（已在 DEMO 模式）
cd backend/app && uvicorn server:app --port 8000        # 或 repo 根目錄 make up

# 2) 前端開發：/api 與 /photos 代理到 8000（同源 cookie session）
cd fleet-ops-center && npm install && npm run dev        # http://localhost:3000/ops

# 3) 正式：靜態匯出到 backend/app/static/ops，由 FastAPI 於 http://localhost:8000/ops 提供
npm run build:ops
```

Docker：`docker compose build` 會在第一階段用 node 匯出前端並複製進 image（`backend/Dockerfile`）。

登入：Demo 帳密由 `/api/ops/health` 提供（admin / station）；站點人員登入後只看 `/ops/m` 手機版。

## 資料流（沒有另一套前端狀態）

- `src/lib/ops/api.ts`、`types.ts`：後端 API client（沿用舊 frontend-admin 介面，另加 cases / stations / location）。
- `src/store/OpsStore.tsx`：5 秒輪詢 + SSE，拉 summary / people / fleet / cases / tasks / events。
- `src/lib/ops/adapters.ts`：後端事實 → view model。車輛狀態只由「未完成任務／手動鎖定／未裁決 AI 案件」推導；
  AI 損傷位置文字由 `damageLocator.ts` 以關鍵字對應到 3D 車身 14 個區域（近似，標註卡保留 AI 原文）。
- 「執行 AI 建議方案」= 對該車所有未裁決 P1/P2 案件送 `POST /api/ops/cases/{id}/decision` confirm，
  由後端自動建單、依類型指派、發 webhook（與監理台 `/api/decision` 同一條路）。
- 車輛座標：後端 `stations.json` 站點表 + `car_locations`（可在車輛面板改派站點）；派單系統未串接前以車牌雜湊固定指派。

## 主題

右上角太陽／月亮按鈕切換深色／淺色；首次依系統偏好，選擇存於 `localStorage`（`irent-ops-theme`），首屏以 inline script 套用避免閃爍。3D 數位分身、台灣與台北地圖、證據照片區永遠維持深色（`.always-dark`）。

## 頁面

指揮中心（3D 多尺度）、總覽、通知中心、事件中心、車隊、車輛（`/vehicle?car=`）、清潔、維修、AI 洞察、人員與組別、通知設定、`/m` 站點手機版。
任務／案件抽屜含：裁決、負責人、動作（後端 `allowed_actions` 守門）、三對象通知文案、完工照上傳、處理歷程與備註。

---

## Visual notes (final polish)

- 車輛數位分身為**改良版程序式 hatchback**（`VehicleModel.tsx`）：擠出側面輪廓車身、獨立四片車門 mesh、
  車窗帶、輪拱／胎／鋁圈、頭尾燈、鍍鉻把手；右後車門受損時面板淡紅＋三條細刮痕＋ hotspot 脈衝。
  仍可用 `src/config/vehicleModel.ts` 換成 GLB。
- 台灣層為程式產生的高度場地形（`TAIWAN_PEAKS` in `fleetMapData.ts`），無任何外部圖資或資產。
- 城市層在進入車輛數位分身時**保持掛載**（隱藏不卸載），返回時相機平滑回到城市視角。

## Fleet Command Center (`/command`) — Multi-Scale Digital Twin

台灣 (R3F 擠出地形 + 城市光柱) → 台北 (MapLibre GL 3D 城市地圖) → 車輛數位分身 (既有元件) → 車損位置。

- **地圖技術**：MapLibre GL JS + OpenFreeMap 向量圖資（OpenMapTiles schema，ODbL），**不需要任何 API token**。
  樣式定義在 `src/config/map.ts`（只畫水域、公園、道路、3D 建築、邊界，不畫 POI）。
- **Worker**：MapLibre 的 worker 以靜態檔案提供（`public/maplibre/`），升級 maplibre-gl 後請重新複製
  `node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs` 與 `maplibre-gl-shared.mjs`。
- **地理資料**：全部集中在 `src/data/fleetMapData.ts`（城市、行政區、車輛座標、負載權重、標記顏色）。
- **狀態同步**：`useFleetMap()` 由 OpsStore 推導每個標記的狀態；ABC-1234 在執行方案 / 完成任務 / 恢復上線 /
  重置 Demo 後，台北地圖標記會即時變色。
- **Fallback**：WebGL 或樣式載入失敗時改為簡化的網格車隊視圖，其餘頁面不受影響。

Demo：指揮中心 → 檢視台北 → 調查 ABC-1234 → 開啟數位分身 → 執行 AI 建議方案 → 麵包屑回台北（標記變「暫停營運」）
→ 維修 / 清潔標記完成 → 回台北（標記「整備完成」）→ 開啟數位分身 → 車輛恢復上線 → 標記回到正常 → 重置 Demo。

## Demo story (Overview page) — AI detection → operational action

1. **LIVE INCIDENT**: `ABC-1234` (Toyota Yaris) returned 20:42, AI detected 2 issues.
2. Click **Damage** → the twin flies to the right rear door; region glow + annotation (Scratch · 92% · Medium).
3. **View Evidence** → scrolls to the Before / After comparison, linked to that hotspot, damage region boxed.
4. Click **Cleaning** → twin switches to **Interior** (X-ray shell + cabin) with 3 cabin hotspots.
5. **AI Recommendation** → *Temporarily suspend vehicle* → **Execute Recommended Plan** runs a
   step-by-step checklist: suspend, create `MNT-20261005-024` + `CLN-20261005-018`, assign teams.
6. Status crossfades to **Temporarily Unavailable** · Estimated Ready **Oct 6 · 10:30** · panel becomes *Recovery in progress*.
7. **Maintenance** page → Mark Complete. 8. **Cleaning** page → Mark Complete.
9. Vehicle becomes **Ready for Service** → **Return Vehicle to Fleet** → **Available**, timeline gets *Vehicle returned to service*.
10. **Reset Demo** (avatar menu, top-right) restores the initial state for the next run.

All of this flows through `OpsStore` (lifecycle: returned → suspended → ready → available); use the
sidebar to navigate, since a hard page reload resets the in-memory demo state.

## Structure

```
src/
  app/                 routes: / (overview), /fleet, /fleet/[id], /incidents, /cleaning, /maintenance, /insights
  data/mockData.ts     all demo data (vehicles, incidents, tasks, KPIs, teams, AI recommendation)
  store/OpsStore.tsx   client state (incident decisions, tasks, derived vehicle status, toasts, drawer)
  config/vehicleModel.ts   swap in a real GLB here
  config/map.ts        MapLibre style + camera presets (no token)
  data/fleetMapData.ts geospatial mock data for the command center
  components/
    map/         FleetCommandCenter (levels + transitions), TaiwanFleetMap/TaiwanScene (R3F),
                 TaipeiFleetMap (MapLibre), TaipeiFallback, FleetMapFilters, VehicleMapPopup,
                 MapOperationsPanel, AIMapInsight, CommandBreadcrumb, useFleetMap
    layout/      AppShell, Sidebar, Topbar, Toasts
    dashboard/   KPICard, LiveIncident, FleetStatus, IncidentQueue, TaskBoard
    vehicle/     VehicleDigitalTwin (2D overlays, Exterior/Interior tabs) → VehicleScene (R3F canvas)
                 VehicleModel (GLTF or procedural placeholder, X-ray mode), CabinInterior, DamageHotspot,
                 DamageRegion (panel decal), DigitalTwinAnnotation, CameraRig,
                 VehicleStatusPanel, InspectionPanel, VehicleTimeline
    evidence/    BeforeAfterComparison (slider / overlay / side-by-side, zoom, diff highlight)
    incident/    IncidentDrawer, IncidentCard, TaskAssignment, AIRecommendationPanel, ExecutionProgress
    workspace/   VehicleWorkspace (twin + status + inspection + evidence + timeline, reused by 3 pages)
    ui/          GlassPanel, Button, Badge, CountUp, ConfidenceBar, motion variants
```

## Replacing the placeholder 3D car

Put a licensed GLB under `public/models/` and set `VEHICLE_MODEL_URL` in
`src/config/vehicleModel.ts`. Hotspots are world-space coordinates
(`HOTSPOT_POSITIONS` in `mockData.ts`, car faces +X, right side = +Z, ~4.1 m long),
so they work with any model that is centered and oriented the same way. If the GLB
fails to load the placeholder is rendered automatically.

