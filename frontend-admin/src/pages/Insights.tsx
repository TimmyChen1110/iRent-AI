import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Insights as InsightsT } from '../lib/types'
import { useStore } from '../lib/store'
import { Columns, HBars } from '../components/Bars'

const TYPE_COLOR: Record<string, string> = { repair: 'var(--brand)', cleaning: '#1B7F6E', claims: 'var(--brand-deep)' }

export function Insights() {
  const { tick } = useStore()
  const [d, setD] = useState<InsightsT | null>(null)
  const [showTable, setShowTable] = useState(false)
  useEffect(() => { api.insights().then(setD).catch(() => {}) }, [tick])

  const hours = useMemo(() => {
    if (!d?.uploads) return []
    const bh = d.uploads.by_hour
    const sorted = [...bh].map((v, h) => ({ v, h })).sort((a, b) => b.v - a.v)
    const top = new Set(sorted.slice(0, 6).map(x => x.h))
    return bh.map((v, h) => ({ label: `${h}`, value: v, emphasis: top.has(h), hint: `${h}:00–${h}:59 還車 ${v} 單` }))
  }, [d])

  if (!d) return <div className="content"><div className="empty card">載入中…</div></div>
  const up = d.uploads
  const peak = hours.filter(h => h.emphasis).map(h => Number(h.label)).sort((a, b) => a - b)
  const peakShare = up ? Math.round(hours.filter(h => h.emphasis).reduce((s, h) => s + h.value, 0) / up.orders * 100) : 0
  const low = up ? [...hours].sort((a, b) => a.value - b.value).slice(0, 5).map(h => Number(h.label)).sort((a, b) => a - b) : []
  const dateStr = up ? Object.keys(up.dates).join('、') : ''

  return (
    <>
      <div className="topbar" style={{ position: 'static', background: 'transparent', backdropFilter: 'none', borderBottom: 0, paddingBottom: 0 }}>
        <div><h1>營運洞察</h1><div className="sub">從真實上傳 log 與整備資料算出來的排班依據；每張圖標明口徑與 n</div></div>
        <span className="spacer" />
        <label className="small muted row"><input type="checkbox" checked={showTable} onChange={e => setShowTable(e.target.checked)} /> 顯示數值表</label>
      </div>
      <div className="content">
        {up ? (
          <div className="card">
            <h2>還車時段分布 — 清潔／整備人力該排在哪</h2>
            <div className="small muted" style={{ marginBottom: 10 }}>
              以訂單去重的還車上傳時間，n = {up.orders.toLocaleString()} 單（{up.photos.toLocaleString()} 張照片、{up.vehicles.toLocaleString()} 台車），資料日期 {dateStr}。單日資料，不做星期分布。
            </div>
            <Columns data={hours} height={200} />
            <div className="row wrap" style={{ marginTop: 10, gap: 12 }}>
              <span className="badge accent">尖峰 {peak.map(h => `${h}時`).join('、')} 佔 {peakShare}%</span>
              <span className="badge soft">離峰 {low[0]}–{low[low.length - 1]} 時 → 適合排維修與深度清潔</span>
            </div>
            <div className="small faint" style={{ marginTop: 6 }}>建議：清潔組上班時段對齊 15–23 時；P2 維修派在凌晨 3–7 時車輛閒置窗口。</div>
            {showTable && (
              <table className="table" style={{ marginTop: 10 }}><thead><tr><th>時</th>{hours.map(h => <th key={h.label}>{h.label}</th>)}</tr></thead>
                <tbody><tr><td>單數</td>{hours.map(h => <td key={h.label} className="mono">{h.value}</td>)}</tr></tbody></table>
            )}
          </div>
        ) : <div className="notice">尚未產生上傳 log 彙整：執行 <span className="mono">python3 backend/pipeline/build_ops_insights.py</span></div>}

        <div className="kpis">
          <div className="kpi"><div className="micro">整備任務總數</div><div className="num">{d.tasks.total}</div><div className="sub">維修 {sum(d.tasks.by_type.repair)} · 清潔 {sum(d.tasks.by_type.cleaning)}（即時）</div></div>
          <div className="kpi"><div className="micro">中位開工時間</div><div className="num">{d.tasks.median_minutes_to_start == null ? '—' : fmtMin(d.tasks.median_minutes_to_start)}</div><div className="sub">建立 → 開始處理，n = {d.tasks.n_started}</div></div>
          <div className="kpi"><div className="micro">中位完工時間</div><div className="num">{d.tasks.median_minutes_to_complete == null ? '—' : fmtMin(d.tasks.median_minutes_to_complete)}</div><div className="sub">建立 → 完成，n = {d.tasks.n_completed}</div></div>
          <div className="kpi"><div className="micro">車內整潔（離線分類）</div><div className="num">{d.interior.n ? `${Math.round(d.interior.髒汙 / d.interior.n * 100)}%` : '—'}</div><div className="sub">髒汙比例；乾淨 {d.interior.乾淨}／普通 {d.interior.普通}／髒汙 {d.interior.髒汙}，n = {d.interior.n}（排除模型註明無法判讀的 {d.interior.excluded_unreadable} 張）</div></div>
        </div>

        <div className="card">
          <h2>車輛事件排行 — 哪些車該優先巡檢</h2>
          <div className="small muted" style={{ marginBottom: 10 }}>人工確認的維修／清潔任務（即時）＋ 資料集索賠正樣本（離線，n = 21）。取前 10。</div>
          {d.car_ranking.length === 0 ? <div className="empty">尚無資料</div> : (
            <>
              <HBars data={d.car_ranking.map(c => ({ label: c.car, value: c.repair + c.cleaning + c.claims, parts: [{ key: 'repair', value: c.repair }, { key: 'cleaning', value: c.cleaning }, { key: 'claims', value: c.claims }], hint: `維修 ${c.repair}、清潔 ${c.cleaning}、索賠 ${c.claims}` }))} colorOf={k => TYPE_COLOR[k]} />
              <div className="row wrap small muted" style={{ marginTop: 10, gap: 14 }}>
                {[['repair', '維修任務'], ['cleaning', '清潔任務'], ['claims', '索賠紀錄']].map(([k, l]) => <span key={k} className="row" style={{ gap: 5 }}><i style={{ width: 10, height: 10, borderRadius: 2, background: TYPE_COLOR[k] }} />{l}</span>)}
              </div>
              {showTable && (
                <table className="table" style={{ marginTop: 10 }}><thead><tr><th>車牌</th><th>維修</th><th>清潔</th><th>索賠</th></tr></thead>
                  <tbody>{d.car_ranking.map(c => <tr key={c.car}><td className="plate">{c.car}</td><td className="mono">{c.repair}</td><td className="mono">{c.cleaning}</td><td className="mono">{c.claims}</td></tr>)}</tbody></table>
              )}
            </>
          )}
        </div>
        <div className="notice">口徑說明：上傳 log 為一次性離線彙整（<span className="mono">backend/app/ops_insights.json</span>）；任務數據由資料庫即時計算；車內整潔為固定資料集的離線分類結果，不代表全車隊比例。</div>
      </div>
    </>
  )
}

const sum = (o: Record<string, number> | undefined) => o ? Object.values(o).reduce((a, b) => a + b, 0) : 0
const fmtMin = (m: number) => m < 60 ? `${Math.round(m)} 分` : m < 1440 ? `${(m / 60).toFixed(1)} 時` : `${(m / 1440).toFixed(1)} 天`
