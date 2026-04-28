from apps.install.models import InstallState
from apps.notifications.services import push_realtime_event


def build_install_payload(state: InstallState) -> dict:
    return {
        "installed": bool(state.installed),
        "installed_at": state.installed_at.isoformat() if state.installed_at else None,
        "seed_requested": bool(state.seed_requested),
        "seed_status": str(state.seed_status or ""),
        "seed_task_id": str(state.seed_task_id or ""),
        "seed_total_users": int(state.seed_total_users or 0),
        "seed_total_posts": int(state.seed_total_posts or 0),
        "seed_created_users": int(state.seed_created_users or 0),
        "seed_created_posts": int(state.seed_created_posts or 0),
        "seed_last_message": str(state.seed_last_message or ""),
    }


def broadcast_install_state(install_state_id: int) -> None:
    state = InstallState.objects.filter(id=install_state_id).first()
    if not state:
        return
    payload = build_install_payload(state)
    target_user_ids = {
        int(state.master_admin_user_id or 0),
        int(state.seed_requested_by_user_id or 0),
    }
    for user_id in target_user_ids:
        if user_id <= 0:
            continue
        push_realtime_event(
            user_id=user_id,
            event_type="install.seed_status",
            payload=payload,
        )
