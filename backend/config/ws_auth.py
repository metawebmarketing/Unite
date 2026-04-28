from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

User = get_user_model()


def get_user_for_token(token: str):
    try:
        payload = AccessToken(token)
        user_id = int(payload.get("user_id"))
    except (ValueError, TypeError, InvalidToken, TokenError):
        return AnonymousUser()
    if user_id <= 0:
        return AnonymousUser()
    # Avoid synchronous DB lookups in middleware to keep websocket startup reliable.
    return User(id=user_id)


class JWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope["user"] = AnonymousUser()
        token = self._extract_token(scope)
        if token:
            scope["user"] = get_user_for_token(token)
        return await self.app(scope, receive, send)

    @staticmethod
    def _extract_token(scope) -> str:
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        for key in ("token", "access_token"):
            values = query_params.get(key, [])
            if values and str(values[0]).strip():
                return str(values[0]).strip()

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return ""
