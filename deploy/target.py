"""检查整站部署源地址；HTTP 仅用于直接访问 IP。"""

from ipaddress import ip_address
from urllib.parse import urlsplit


def validate_target(site_origin):
    address = urlsplit(site_origin)
    if (address.scheme not in {"http", "https"} or not address.hostname
            or address.path not in {"", "/"} or address.query or address.fragment
            or address.username or address.password):
        raise ValueError("整站地址必须是 HTTP(S) 源地址，不带路径、查询参数或凭据")
    # 读取端口以提前拒绝格式错误或越界值。
    address.port
    if address.scheme == "http":
        try:
            ip_address(address.hostname)
        except ValueError as exc:
            raise ValueError("HTTP 部署只允许直接访问 IP；域名部署需使用 HTTPS") from exc
