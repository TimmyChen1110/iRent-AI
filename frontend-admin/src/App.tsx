import { Navigate, NavLink, Route, Routes, useLocation, type Location } from 'react-router-dom'
import { StoreProvider, useStore } from './lib/store'
import { ToastProvider } from './components/Toast'
import { Inbox } from './pages/Inbox'
import { Board } from './pages/Board'
import { TaskDetail } from './pages/TaskDetail'
import { People } from './pages/People'
import { Settings } from './pages/Settings'

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
      <NavLink to="/people" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">👥</span>人員與組別
      </NavLink>
      <NavLink to="/settings" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
        <span className="ico">⚙</span>通知設定
      </NavLink>
      <div className="side-foot">
        {health?.demo_mode && <span>DEMO 模式（只影響排序與示範入口）</span>}
        <a href="/" target="_blank" rel="noreferrer">↗ 開啟車況監理台</a>
      </div>
    </aside>
  )
}

function Topbar() {
  const { conn, reader, setReader, people } = useStore()
  const label = conn === 'offline' ? '離線' : '每 5 秒同步'
  return (
    <div className="topbar">
      <span className="spacer" />
      <span className={`conn ${conn}`} title="任務與事件存於後端資料庫，全隊共享"><i />{label}</span>
      <label className="who" title="無登入：自選身分只用於已讀與歷程署名，未驗證">
        <span className="faint">我是</span>
        <select value={reader} onChange={e => setReader(e.target.value)}>
          <option value="">未選擇</option>
          <option value="客服">客服</option>
          <option value="營運主管">營運主管</option>
          {people.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}
        </select>
      </label>
    </div>
  )
}

export default function App() {
  const location = useLocation()
  const bg = (location.state as { background?: Location } | null)?.background
  return (
    <StoreProvider>
      <ToastProvider>
        <div className="shell">
          <Sidebar />
          <div className="main">
            <Topbar />
            <Routes location={bg || location}>
              <Route path="/" element={<Navigate to="/inbox" replace />} />
              <Route path="/inbox" element={<Inbox />} />
              <Route path="/board" element={<Board />} />
              <Route path="/tasks/:id" element={<TaskDetail mode="page" />} />
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
