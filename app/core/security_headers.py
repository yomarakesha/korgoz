"""Adds defensive HTTP headers to every response.

A plain ASGI middleware (not BaseHTTPMiddleware) so the endless MJPEG live stream is
passed through untouched.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = (
    (b"x-content-type-options", b"nosniff"),  # no MIME sniffing of uploads/responses
    (b"x-frame-options", b"DENY"),  # the dashboard may not be framed (clickjacking)
    (b"referrer-policy", b"same-origin"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers.extend(h for h in HEADERS if h[0] not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
