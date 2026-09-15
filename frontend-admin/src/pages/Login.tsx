import { useEffect, useState } from 'react'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import type { DemoCredential } from '../lib/types'

export function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [demoCredentials, setDemoCredentials] = useState<DemoCredential[]>([])
  useEffect(() => {
    api.health().then(health => setDemoCredentials(health.demo_credentials || [])).catch(() => {})
  }, [])
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try { await login(username.trim(), password) }
    catch (err) { setError((err as Error).message || '登入失敗') }
    finally { setBusy(false) }
  }
  return <main className="login-page">
    <form className="login-card" onSubmit={submit}>
      <div className="brand"><div className="mark"><span /></div><div><b>iRent 整備中心</b><small>環節三 · 營運通知與整備</small></div></div>
      <div><h1>登入</h1><p className="muted">管理者進入營運後台；站點人員只會看到自己的整備任務。</p></div>
      {demoCredentials.length > 0 && <div className="demo-logins" aria-label="Demo 快速登入">
        <span className="micro">Demo 快速登入</span>
        <div className="row wrap">{demoCredentials.map(credential =>
          <button type="button" className="btn sm" key={credential.username}
            onClick={() => { setUsername(credential.username); setPassword(credential.password); setError('') }}>
            {credential.label} · {credential.username}
          </button>
        )}</div>
        <div className="small faint">點選角色會填入本機 Demo 帳密，再按登入。</div>
      </div>}
      <label><span className="micro">帳號</span><input className="input" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required /></label>
      <label><span className="micro">密碼</span><input className="input" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></label>
      {error && <div className="notice warn" role="alert">{error}</div>}
      <button className="btn primary" disabled={busy}>{busy ? '登入中…' : '登入'}</button>
      <div className="small faint">非 Demo 環境不會顯示或啟用預設帳密。</div>
    </form>
  </main>
}
