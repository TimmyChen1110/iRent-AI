import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Person } from '../lib/types'
import { useStore } from '../lib/store'
import { useToast } from '../components/Toast'

export function People() {
  const { refresh } = useStore()
  const [list, setList] = useState<Person[]>([])
  const [group, setGroup] = useState('維修組')
  const [name, setName] = useState('')
  const toast = useToast()
  const load = () => api.people(true).then(r => setList(r.people)).catch(() => {})
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!name.trim()) return
    try { await api.addPerson(group, name.trim()); setName(''); load(); refresh(); toast('已新增') }
    catch (e) { toast((e as Error).message, 'warn') }
  }
  const toggle = async (p: Person) => {
    setList(l => l.map(x => x.id === p.id ? { ...x, active: p.active ? 0 : 1 } : x))
    try { await api.patchPerson(p.id, { active: !p.active }); refresh() } catch { load(); toast('更新失敗', 'warn') }
  }
  const groups = Array.from(new Set(list.map(p => p.group_name)))

  return (
    <>
      <div className="topbar" style={{ position: 'static', background: 'transparent', backdropFilter: 'none', borderBottom: 0, paddingBottom: 0 }}>
        <div><h1>人員與組別</h1><div className="sub">可指派的整備人員名單；停用者不再出現於指派選單</div></div>
      </div>
      <div className="content">
        <div className="card">
          <h2>新增人員</h2>
          <div className="row wrap">
            <input className="input" style={{ width: 160 }} list="groups" value={group} onChange={e => setGroup(e.target.value)} placeholder="組別" />
            <datalist id="groups">{groups.map(g => <option key={g} value={g} />)}</datalist>
            <input className="input" style={{ width: 220 }} value={name} onChange={e => setName(e.target.value)} placeholder="姓名或組別代號，如 維修組 C" onKeyDown={e => { if (e.key === 'Enter') add() }} />
            <button className="btn primary" onClick={add} disabled={!name.trim()}>新增</button>
          </div>
        </div>
        <div className="card">
          <h2>名單</h2>
          <table className="table">
            <thead><tr><th>組別</th><th>名稱</th><th>狀態</th><th /></tr></thead>
            <tbody>
              {list.map(p => (
                <tr key={p.id} style={{ opacity: p.active ? 1 : .55 }}>
                  <td>{p.group_name}</td>
                  <td style={{ fontWeight: 700 }}>{p.name}</td>
                  <td><span className={`badge ${p.active ? 'ok' : 'soft'}`}>{p.active ? '在班' : '停用'}</span></td>
                  <td style={{ textAlign: 'right' }}><button className="btn xs" onClick={() => toggle(p)}>{p.active ? '停用' : '啟用'}</button></td>
                </tr>
              ))}
              {list.length === 0 && <tr><td colSpan={4} className="empty">尚無人員</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="notice">身分為前端自選、未驗證；名單值與監理台既有指派選單相容。</div>
      </div>
    </>
  )
}
