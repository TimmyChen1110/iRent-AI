import { Navigate, NavLink, Route, Routes, useLocation, type Location } from 'react-router-dom'
import { StoreProvider } from './lib/store'
import { useStore } from './lib/store-context'
import { ToastProvider } from './components/Toast'
import { Inbox } from './pages/Inbox'
import { Board } from './pages/Board'
import { TaskDetail } from './pages/TaskDetail'
import { People } from './pages/People'
import { Settings } from './pages/Settings'
import { Fleet } from './pages/Fleet'
import { Insights } from './pages/Insights'
import { Mobile } from './pages/Mobile'
import { useEffect } from 'react'
import { useToast } from './components/toast-context'
import { EVENT_TXT } from './lib/labels'
import { AuthProvider, useAuth } from './lib/auth'
import { Login } from './pages/Login'

function Sidebar() {
  const { summary, health } = useStore()
  const unread = summary?.unread || 0
  const open = (summary?.pending || 0) + (summary?.in_progress || 0)
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="mark"><span /></div>
        <div><b>iRent 整備中心</b><small>環節三 · 營運通知與整備</small></div>
      </div>
      <NavLink to="/inbox" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">🔔</span>通知中心{unread > 0 && <span className="cnt hot">{unread}</span>}
      </NavLink>
      <NavLink to="/board" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">▦</span>整備看板{open > 0 && <span className="cnt">{open}</span>}
      </NavLink>
      <NavLink to="/fleet" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">🚗</span>車輛派單狀態
      </NavLink>
      <NavLink to="/insights" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">📈</span>營運洞察
      </NavLink>
      <NavLink to="/people" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">👥</span>人員與組別
      </NavLink>
      <NavLink to="/settings" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">⚙</span>通知設定
      </NavLink>
      <div className="side-foot">
        {health?.demo_mode && <span>DEMO 模式（只影響排序與示範入口）</span>}
        <a href="/" target="_blank" rel="noreferrer">↗ 開啟車況監理台</a>
        <NavLink to="/m">📱 站點人員手機版</NavLink>
      </div>
    </aside>
  )
}

/** SSE 新事件 → 底部提示（只提示，不打斷） */
function LiveToasts() {
  const { lastEvent } = useStore()
  const toast = useToast()
  useEffect(() => {
    if (!lastEvent) return
    const kind = lastEvent.type === 'notify_failed' || lastEvent.type === 'sla_overdue' ? 'warn' : 'ok'
    toast(`${EVENT_TXT[lastEvent.type] || lastEvent.type} · ${lastEvent.car || ''} ${lastEvent.title || ''}`, kind)
  }, [lastEvent, toast])
  return null
}

function Topbar() {
  const { conn } = useStore()
  const { user, logout } = useAuth()
  const label = conn === 'offline' ? '離線' : conn === 'live' ? '即時連線' : '輪詢中（每 5 秒）'
  return (
    <div className="topbar">
      <span className="spacer" />
      <span className={`conn ${conn}`} title="任務與事件存於後端資料庫，全隊共享"><i />{label}</span>
      <span className="who"><span className="faint">已登入</span><b>{user?.name}</b><span className="badge soft">Admin</span></span>
      <button className="btn xs" onClick={logout}>登出</button>
    </div>
  )
}

function AdminApp() {
  const location = useLocation()
  const bg = (location.state as { background?: Location } | null)?.background
  if (location.pathname === '/m' || location.pathname.startsWith('/m/')) {
    return <StoreProvider><ToastProvider><Mobile /></ToastProvider></StoreProvider>
  }
  return (
    <StoreProvider>
      <ToastProvider>
        <div className="shell">
          <Sidebar />
          <LiveToasts />
          <div className="main">
            <Topbar />
            <Routes location={bg || location}>
              <Route path="/" element={<Navigate to="/inbox" replace />} />
              <Route path="/inbox" element={<Inbox />} />
              <Route path="/board" element={<Board />} />
              <Route path="/tasks/:id" element={<TaskDetail mode="page" />} />
              <Route path="/fleet" element={<Fleet />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/people" element={<People />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/inbox" replace />} />
            </Routes>
            {bg && (
              <Routes>
                <Route path="/tasks/:id" element={<TaskDetail mode="sheet" />} />
              </Routes>
            )}
          </div>
        </div>
      </ToastProvider>
    </StoreProvider>
  )
}

function RoleApp() {
  const { user, loading } = useAuth()
  if (loading) return <div className="login-page"><div className="card">確認登入狀態…</div></div>
  if (!user) return <Login />
  if (user.role === 'station') {
    return <StoreProvider station><ToastProvider><Routes>
      <Route path="/m" element={<Mobile />} />
      <Route path="*" element={<Navigate to="/m" replace />} />
    </Routes></ToastProvider></StoreProvider>
  }
  return <AdminApp />
}

export default function App() {
  return <AuthProvider><RoleApp /></AuthProvider>
}
