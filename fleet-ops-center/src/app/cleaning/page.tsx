import { TaskBoard } from "@/components/dashboard/TaskBoard";
export default function CleaningPage() { return <TaskBoard title="清潔" subtitle="由人工確認車內髒污後自動建立的清潔任務；完工前需完工照（依設定）。" types={["cleaning"]} />; }
