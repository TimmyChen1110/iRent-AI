import { TaskBoard } from "@/components/dashboard/TaskBoard";
export default function MaintenancePage() { return <TaskBoard title="維修" subtitle="由人工確認車損後自動建立的維修任務；SLA 依 P1/P2/P3 倒數。" types={["maintenance", "inspection"]} />; }
