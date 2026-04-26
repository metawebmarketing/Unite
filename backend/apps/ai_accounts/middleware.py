from apps.ai_accounts.services import log_ai_action


class AiActionAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return response
        if not hasattr(user, "ai_account"):
            return response
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return response
        if not request.path.startswith("/api/v1/"):
            return response
        endpoint_key = request.path.removeprefix("/api/v1/").strip("/").replace("/", "_").replace("-", "_")
        action_name = f"{request.method.lower()}_{endpoint_key or 'root'}"
        log_ai_action(
            user=user,
            action_name=action_name,
            endpoint=request.path,
            method=request.method,
            status_code=getattr(response, "status_code", None),
            payload={},
        )
        return response
