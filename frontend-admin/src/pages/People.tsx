import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Person } from '../lib/types'
import { useStore } from '../lib/store-context'
import { useToast } from '../components/toast-context'

export function People() {
  const { refresh } = useStore()
  const [list, setList] = useState<Person[]>([])
  const [group, setGroup] = useState('維修組')
  const [name, setName] = useState('')
  const [edit, setEdit] = useState<{ id: number; group_name: string; name: string } | null>(null)
  const [saving, setSaving] = useState(false)
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
  const saveEdit = async () => {
    if (!edit?.group_name.trim() || !edit.name.trim()) return
    setSaving(true)
    try {
      await api.patchPerson(edit.id, { group_name: edit.group_name.trim(), name: edit.name.trim() })
      setEdit(null); load(); refresh(); toast('人員資料已更新')
    } catch (e) { toast((e as Error).message, 'warn') } finally { setSaving(false) }
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
                  <td>{edit?.id === p.id
                    ? <input className="input" list="groups" value={edit.group_name} onChange={e => setEdit({ ...edit, group_name: e.target.value })} />
                    : p.group_name}</td>
                  <td style={{ fontWeight: 700 }}>{edit?.id === p.id
                    ? <input className="input" value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} onKeyDown={e => { if (e.key === 'Enter') saveEdit() }} />
                    : p.name}</td>
                  <td><span className={`badge ${p.active ? 'ok' : 'soft'}`}>{p.active ? '在班' : '停用'}</span></td>
                  <td style={{ textAlign: 'right' }}><div className="row" style={{ justifyContent: 'flex-end' }}>
                    {edit?.id === p.id
                      ? <><button className="btn xs primary" disabled={saving || !edit.name.trim() || !edit.group_name.trim()} onClick={saveEdit}>儲存</button><button className="btn xs ghost" onClick={() => setEdit(null)}>取消</button></>
                      : <button className="btn xs" onClick={() => setEdit({ id: p.id, group_name: p.group_name, name: p.name })}>編輯</button>}
                    <button className="btn xs" disabled={edit?.id === p.id} onClick={() => toggle(p)}>{p.active ? '停用' : '啟用'}</button>
                  </div></td>
                </tr>
              ))}
              {list.length === 0 && <tr><td colSpan={4} className="empty">尚無人員</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="notice">任務歸屬使用穩定人員 ID；人員改名不會失去既有任務權限。帳號登入與 Admin／Station 權限由後端驗證。</div>
      </div>
    </>
  )
}
