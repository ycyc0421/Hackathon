"""检查同源整站部署地址；HTTP 仅用于直接访问 IP。"""

from ipaddress import ip_address
from urllib.parse import urlsplit


def validate_target(api_base, frontend_origin):
    api = urlsplit(api_base)
    frontend = urlsplit(frontend_origin)
    for address in (api, frontend):
        if (address.scheme not in {"http", "https"} or not address.hostname
                or address.query or address.fragment or address.username or address.password):
            raise ValueError("部署地址必须是 HTTP(S) 地址，不带查询参数、片段或凭据")
        if address.scheme == "http":
            try:
                ip_address(address.hostname)
            except ValueError as exc:
                raise ValueError("HTTP 部署只允许直接访问 IP；域名部署需使用 HTTPS") from exc
    if api.path != "/api/v1" or frontend.path not in {"", "/"}:
        raise ValueError("API 地址须以 /api/v1 结尾，前端地址只能包含源地址")
    def origin(address):
        return address.scheme, address.hostname, address.port or (443 if address.scheme == "https" else 80)
    if origin(api) != origin(frontend):
        raise ValueError("前端与 API 必须同源，防止混合内容及错误部署目标")
