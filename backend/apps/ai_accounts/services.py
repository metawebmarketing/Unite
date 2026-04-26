from apps.ai_accounts.models import AiActionAudit


def log_ai_action(
    *,
    user,
    action_name: str,
    endpoint: str,
    method: str,
    status_code: int | None = None,
    payload: dict | None = None,
) -> None:
    if not hasattr(user, "ai_account"):
        return
    AiActionAudit.objects.create(
        user=user,
        action_name=action_name[:80],
        endpoint=endpoint[:160],
        method=method[:16],
        status_code=status_code,
        payload=payload or {},
    )
