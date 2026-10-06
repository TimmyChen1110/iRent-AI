"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "@/lib/ops/api";
import type { Person } from "@/lib/ops/types";
import { useOps } from "@/store/OpsStore";
import { GlassPanel, SectionHeader } from "@/components/ui/GlassPanel";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { fadeUp, stagger } from "@/components/ui/motion";

const input = "rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[13px] text-white/90 placeholder:text-white/30 focus:outline-none";

export default function PeoplePage() {
  const { refresh, pushToast } = useOps();
  const [list, setList] = useState<Person[]>([]);
  const [group, setGroup] = useState("維修組");
  const [name, setName] = useState("");
  const [edit, setEdit] = useState<{ id: number; group_name: string; name: string } | null>(null);
  const load = () => api.people(true).then((r) => setList(r.people)).catch(() => {});
  useEffect(() => { load(); }, []);
  const add = async () => { if (!name.trim()) return; try { await api.addPerson(group, name.trim()); setName(""); load(); refresh(); pushToast({ tone: "success", title: "已新增" }); } catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } };
  const toggle = async (p: Person) => { try { await api.patchPerson(p.id, { active: !p.active }); load(); refresh(); } catch { pushToast({ tone: "warning", title: "更新失敗" }); } };
  const saveEdit = async () => { if (!edit) return; try { await api.patchPerson(edit.id, { group_name: edit.group_name.trim(), name: edit.name.trim() }); setEdit(null); load(); refresh(); pushToast({ tone: "success", title: "人員資料已更新" }); } catch (e) { pushToast({ tone: "warning", title: (e as Error).message }); } };
  const groups = Array.from(new Set(list.map((p) => p.group_name)));

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={fadeUp}><h2 className="text-[22px] font-semibold tracking-tight text-white">人員與組別</h2><p className="mt-1 text-[13px] text-muted">可指派的整備人員名單；停用者不再出現於指派選單。任務歸屬使用穩定人員 ID。</p></motion.div>
      <GlassPanel variants={fadeUp}>
        <SectionHeader title="新增人員" />
        <div className="flex flex-wrap gap-2">
          <input className={input} list="groups" value={group} onChange={(e) => setGroup(e.target.value)} placeholder="組別" />
          <datalist id="groups">{groups.map((g) => <option key={g} value={g} />)}</datalist>
          <input className={`${input} w-64`} value={name} onChange={(e) => setName(e.target.value)} placeholder="姓名或組別代號，如 維修組 C" onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
          <Button variant="primary" onClick={add} disabled={!name.trim()}>新增</Button>
        </div>
      </GlassPanel>
      <GlassPanel variants={fadeUp} padded={false}>
        <table className="w-full text-left text-[13px]">
          <thead><tr className="border-b border-white/[0.06] text-[10.5px] uppercase tracking-wider text-white/40"><th className="px-5 py-3 font-medium">組別</th><th className="px-4 py-3 font-medium">名稱</th><th className="px-4 py-3 font-medium">狀態</th><th className="px-4 py-3" /></tr></thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id} className="border-b border-white/[0.04]" style={{ opacity: p.active ? 1 : 0.55 }}>
                <td className="px-5 py-3">{edit?.id === p.id ? <input className={input} list="groups" value={edit.group_name} onChange={(e) => setEdit({ ...edit, group_name: e.target.value })} /> : p.group_name}</td>
                <td className="px-4 py-3 font-medium text-white/90">{edit?.id === p.id ? <input className={input} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); }} /> : p.name}</td>
                <td className="px-4 py-3"><Badge tone={p.active ? "success" : "neutral"}>{p.active ? "在班" : "停用"}</Badge></td>
                <td className="px-4 py-3 text-right"><div className="flex justify-end gap-2">
                  {edit?.id === p.id ? <><Button size="sm" variant="primary" onClick={saveEdit}>儲存</Button><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>取消</Button></> : <Button size="sm" onClick={() => setEdit({ id: p.id, group_name: p.group_name, name: p.name })}>編輯</Button>}
                  <Button size="sm" disabled={edit?.id === p.id} onClick={() => toggle(p)}>{p.active ? "停用" : "啟用"}</Button>
                </div></td>
              </tr>
            ))}
            {list.length === 0 && <tr><td colSpan={4} className="p-8 text-center text-muted">尚無人員</td></tr>}
          </tbody>
        </table>
      </GlassPanel>
    </motion.div>
  );
}
