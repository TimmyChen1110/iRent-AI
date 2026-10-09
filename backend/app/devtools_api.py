"""內部開發工具（/api/ops/devtools，**僅限 admin 登入**；ops_auth 中介層以路徑前綴強制，不靠前端隱藏）。

一般使用者 App 介面不含這些功能；展示者／開發者在 /ops 登入後開 /api/ops/devtools 操作：
  GET  /api/ops/devtools                                 工具頁（HTML）
  GET  /api/ops/devtools/vehicles                        全部車輛（含 internal、資料來源、AI 來源、Registry）
  POST /api/ops/devtools/vehicles/{id}/reset             重設測試車輛（封存 Session、車輛回 AVAILABLE）
  POST /api/ops/devtools/reset-all                       清空所有模擬 Session
  GET  /api/ops/devtools/vehicles/{id}/photos            Registry 完整照片集（OCR、品質、配對驗證、人工重標）
  GET  /api/ops/devtools/sessions                        全部 Session
  POST /api/ops/devtools/sessions/{sid}/preload/{stage}  把登記的借車前／還車後照片灌進 Session（走同一條 AI pipeline）
  GET  /api/ops/devtools/sessions/{sid}/pipeline         AI pipeline 詳細輸出（inspection_detail + App 端結果）
  GET  /api/ops/devtools/audit                           照片盤點摘要（DEMO_IMAGE_MANIFEST 統計）
  POST   /api/ops/devtools/demo-vehicles                 建立 Demo 測試車輛（車牌＋地圖座標，寫入 demo_vehicles，立即可租）
  PATCH  /api/ops/devtools/demo-vehicles/{id}            修改 Demo 車輛車牌／車型（租用中不可改車牌）
  DELETE /api/ops/devtools/demo-vehicles/{id}            刪除未租用的 Demo 車輛（歷史租約紀錄保留）
  PATCH  /api/ops/devtools/vehicles/{id}/location        修改任一可租車輛座標（App 地圖與管理者網站共用）
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import demo_vehicle_registry as registry
import rental_inspections as ri
import rental_sessions as rs

router = APIRouter(prefix="/api/ops/devtools", tags=["devtools"])


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except rs.SessionError as e:
        raise HTTPException(e.status, e.detail) from e


@router.get("/vehicles")
def vehicles():
    return {"vehicles": rs.list_vehicles(internal=True)}


class DemoVehicleIn(BaseModel):
    plate: str
    lat: float
    lng: float
    model: str | None = Field(None, max_length=60)
    location_name: str | None = Field(None, max_length=80)


class DemoVehiclePatch(BaseModel):
    plate: str | None = None
    model: str | None = Field(None, max_length=60)


class LocationIn(BaseModel):
    lat: float
    lng: float
    location_name: str | None = Field(None, max_length=80)


@router.post("/demo-vehicles", status_code=201)
def demo_vehicle_create(body: DemoVehicleIn):
    return _wrap(rs.create_demo_vehicle, body.plate, body.lat, body.lng, body.model, body.location_name)


@router.patch("/demo-vehicles/{vehicle_id}")
def demo_vehicle_update(vehicle_id: str, body: DemoVehiclePatch):
    return _wrap(rs.update_demo_vehicle, vehicle_id, body.plate, body.model)


@router.delete("/demo-vehicles/{vehicle_id}")
def demo_vehicle_delete(vehicle_id: str):
    return _wrap(rs.delete_demo_vehicle, vehicle_id)


@router.patch("/vehicles/{vehicle_id}/location")
def vehicle_location(vehicle_id: str, body: LocationIn):
    return _wrap(rs.set_vehicle_location, vehicle_id, body.lat, body.lng, body.location_name)


@router.post("/vehicles/{vehicle_id}/reset")
def vehicle_reset(vehicle_id: str):
    return _wrap(rs.reset_vehicle, vehicle_id)


@router.post("/reset-all")
def reset_all():
    return rs.reset_all()


@router.get("/vehicles/{vehicle_id}/photos")
def vehicle_photos(vehicle_id: str):
    v = rs.get_vehicle(vehicle_id, internal=True)
    if v is None:
        raise HTTPException(404, "unknown vehicle_id")
    plate = (v.get("details") or {}).get("registry_plate")
    photos = registry.vehicle_photos(plate) if plate else None
    if photos is None:
        raise HTTPException(404, "此車輛沒有登記的照片（只能即時拍攝）")
    return {"vehicle_id": vehicle_id, **photos}


@router.get("/sessions")
def sessions():
    return {"sessions": rs.list_sessions()}


@router.post("/sessions/{session_id}/preload/{stage}")
def preload(session_id: str, stage: str):
    return _wrap(rs.preload_photos, session_id, stage)


@router.get("/sessions/{session_id}/pipeline")
def pipeline(session_id: str):
    s = _wrap(rs.get_session, session_id)
    detail = ri.inspection_detail(s["rental_id"])
    return {"session": s, "inspection_detail": detail, "app_result": _wrap(rs.inspection_result, session_id)}


@router.get("/audit")
def audit():
    m = registry.manifest()
    return {"generated_at": m.get("generated_at"), "sources": m.get("sources"), "weights": m.get("weights"),
            "registered_plates": registry.registered_plates(),
            "top": [{"plate": v["plate"], "total_score": v["total_score"], "complete_pair": v["complete_pair"],
                     "verified_pair_angles": v["verified_pair_angles"], "damage_angles": v["damage_angles"]}
                    for v in (m.get("vehicles") or [])[:10]]}


PAGE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>iRent 內部開發工具</title>
<style>
body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
header{padding:14px 20px;background:#1e293b;border-bottom:1px solid #334155;display:flex;gap:12px;align-items:center}
header h1{font-size:16px;margin:0}header .warn{color:#fbbf24;font-size:12px}
main{padding:16px 20px;display:grid;gap:16px;grid-template-columns:1fr 1fr}
section{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:14px}
h2{font-size:14px;margin:0 0 10px;color:#93c5fd}
table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:5px 6px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
button{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:5px 9px;font-size:12px;cursor:pointer;margin:2px}
button.danger{background:#dc2626}button.ghost{background:#334155}
pre{background:#0b1220;border:1px solid #334155;border-radius:8px;padding:10px;max-height:360px;overflow:auto;font-size:11px}
.tag{display:inline-block;padding:1px 6px;border-radius:999px;font-size:11px;background:#334155}
.tag.i{background:#7c2d12}.tag.p{background:#14532d}
#log{grid-column:1/3}
</style></head><body>
<header><h1>iRent 內部開發工具</h1><span class="warn">僅限管理者；這裡的操作不會出現在一般使用者 App。</span>
<button class="ghost" onclick="loadAll()">重新整理</button><button class="danger" onclick="resetAll()">清空所有模擬 Session</button></header>
<main>
<section><h2>車輛（含內部）</h2><table id="veh"></table></section>
<section><h2>Session</h2><table id="ses"></table></section>
<section><h2>照片 Registry / 盤點</h2><div id="audit"></div><pre id="photos">點車輛列的「照片」查看 OCR／品質／配對驗證</pre></section>
<section><h2>AI pipeline 輸出</h2><pre id="pipe">點 Session 列的「pipeline」</pre></section>
<section id="log"><h2>操作記錄</h2><pre id="logp"></pre></section>
</main>
<script>
const B='/api/ops/devtools';const log=m=>{const p=document.getElementById('logp');p.textContent=new Date().toLocaleTimeString()+'  '+m+'\\n'+p.textContent};
async function api(path,method='GET'){const r=await fetch(B+path,{method,credentials:'same-origin'});const j=await r.json().catch(()=>({}));if(!r.ok){log(method+' '+path+' → '+r.status+' '+(j.detail||''));throw new Error(j.detail||r.status)}return j}
async function loadAll(){
 const v=await api('/vehicles');document.getElementById('veh').innerHTML='<tr><th>車牌</th><th>車型</th><th>狀態</th><th>類別/可見</th><th>AI 來源</th><th>操作</th></tr>'+v.vehicles.map(x=>`<tr><td><b>${x.plate}</b><br><small>${x.vehicle_id}</small></td><td>${x.model}<br><small>${x.image_note||''}</small></td><td>${x.status}${x.active_session_id?'<br><small>'+x.active_session_id+'</small>':''}</td><td>${x.category} <span class="tag ${x.visibility==='internal'?'i':'p'}">${x.visibility}</span></td><td><small>${x.ai_source_label}</small></td><td>${x.is_demo_vehicle?`<button class="danger" onclick="resetVehicle('${x.vehicle_id}','${x.plate}')">重設</button>`:''}${(x.details||{}).registry_plate?`<button class="ghost" onclick="photos('${x.vehicle_id}')">照片</button>`:''}</td></tr>`).join('');
 const s=await api('/sessions');document.getElementById('ses').innerHTML='<tr><th>Session</th><th>車</th><th>狀態</th><th>租約</th><th>操作</th></tr>'+s.sessions.map(x=>`<tr><td><small>${x.session_id}</small></td><td>${x.vehicle.plate}</td><td>${x.state}<br><small>${x.rental_status||''} / ${x.analysis}</small></td><td><small>${x.rental_id}</small></td><td>${x.state==='PICKUP_INSPECTION'?`<button onclick="preload('${x.session_id}','pickup')">預載取車照</button>`:''}${x.state==='PHOTO_INSPECTION'?`<button onclick="preload('${x.session_id}','return')">預載還車照</button>`:''}<button class="ghost" onclick="pipe('${x.session_id}')">pipeline</button></td></tr>`).join('');
 const a=await api('/audit');document.getElementById('audit').innerHTML=`<small>manifest ${a.generated_at||'—'} · 來源 ${JSON.stringify(a.sources)} · 登記車牌 ${a.registered_plates.join(', ')}</small>`;
}
async function resetVehicle(id,plate){if(!confirm('重設 '+plate+'？進行中的 Session 會封存、車輛回 AVAILABLE。'))return;const j=await api('/vehicles/'+id+'/reset','POST');log('重設 '+plate+' → 封存 '+j.archived_sessions.join(',')||'無');loadAll()}
async function resetAll(){if(!confirm('清空所有模擬 Session？'))return;const j=await api('/reset-all','POST');log('清空 '+j.cleared_sessions+' 個 Session');loadAll()}
async function preload(sid,stage){const j=await api('/sessions/'+sid+'/preload/'+stage,'POST');log('預載 '+stage+' → '+j.state+'；照片 '+j.preload.ingested.length+' 張（含車內佔位照）');loadAll()}
async function photos(id){const j=await api('/vehicles/'+id+'/photos');document.getElementById('photos').textContent=JSON.stringify(j,null,1)}
async function pipe(sid){const j=await api('/sessions/'+sid+'/pipeline');document.getElementById('pipe').textContent=JSON.stringify(j,null,1)}
loadAll().catch(e=>log(String(e)));
</script></body></html>"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def page():
    return HTMLResponse(PAGE)
