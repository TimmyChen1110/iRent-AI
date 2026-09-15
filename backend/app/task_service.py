"""整備任務的純業務規則。

這個模組刻意不碰 FastAPI 或資料庫，讓監理台、整備中心與未來的 worker
共用同一份狀態轉換與完工條件。API 可以保留舊的 status 寫法，但合法性
一律由這裡判斷；新前端則只使用後端回傳的 allowed_actions。
"""
from __future__ import annotations


STATUSES = ("pending", "in_progress", "completed", "cancelled")

STATUS_TRANSITIONS = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"completed", "pending", "cancelled"},
    "completed": {"in_progress"},
    "cancelled": {"pending"},
}

_ACTION_TARGETS = {
    ("pending", "start"): "in_progress",
    ("pending", "cancel"): "cancelled",
    ("in_progress", "complete"): "completed",
    ("in_progress", "return_to_pending"): "pending",
    ("in_progress", "cancel"): "cancelled",
    ("completed", "reopen"): "in_progress",
    ("cancelled", "reopen"): "pending",
}


class TaskRuleError(ValueError):
    pass


def validate_transition(current: str, target: str) -> None:
    if target not in STATUSES:
        raise TaskRuleError("status 必須是 pending / in_progress / completed / cancelled")
    if target != current and target not in STATUS_TRANSITIONS.get(current, set()):
        raise TaskRuleError(f"狀態不可由 {current} 直接變更為 {target}")


def target_for_action(current: str, action: str) -> str:
    target = _ACTION_TARGETS.get((current, action))
    if target is None:
        raise TaskRuleError(f"任務在 {current} 狀態不可執行 {action}")
    return target


def completion_requirements(task_type: str, settings: dict, photo_count: int) -> dict:
    required = settings.get(f"require_photo_{task_type}", "0") == "1"
    satisfied = not required or photo_count > 0
    return {
        "photo_required": required,
        "photo_count": photo_count,
        "satisfied": satisfied,
        "message": None if satisfied else "完工前需至少一張完工照",
    }


def capabilities(task: dict, settings: dict, photo_count: int) -> dict:
    """回傳前端可直接使用的 action 與完工條件，不讓前端重寫狀態機。"""
    status = task.get("status")
    req = completion_requirements(task.get("task_type") or "", settings, photo_count)
    actions = []
    targets = {}
    for (source, action), target in _ACTION_TARGETS.items():
        if source != status:
            continue
        if action == "complete" and not req["satisfied"]:
            continue
        actions.append(action)
        targets[action] = target
    if status == "pending" and task.get("assignee_id") is None and not task.get("assignee"):
        actions.append("claim")
        targets["claim"] = status  # claim 不改狀態；提供 target 讓前端仍可只依 capability 呈現
    if status in ("pending", "in_progress"):
        actions.append("assign")
    if status == "in_progress":
        actions.append("upload_photo")
    return {
        "allowed_actions": actions,
        "action_targets": targets,
        "completion_requirements": req,
    }
