"""Small, bounded HTTP client. Provider bodies and credentials never enter error logs."""

import ipaddress
import socket
from urllib.parse import urlsplit

import requests


class ConnectorError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def public_url(raw: str) -> str:
    url = urlsplit(raw.strip())
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.port not in (None, 443)
    ):
        raise ConnectorError(
            "Укажите HTTPS-адрес без логина, параметров и нестандартного порта."
        )
    try:
        addresses = socket.getaddrinfo(url.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(a[4][0]).is_global for a in addresses
        ):
            raise ConnectorError("Укажите публичный адрес сервиса.")
    except OSError:
        raise ConnectorError("Не удалось найти сервер. Проверьте адрес.") from None
    return raw.strip().rstrip("/")


def request_json(method: str, url: str, **kwargs):
    try:
        with requests.request(
            method, url, timeout=(8, 45), allow_redirects=False, stream=True, **kwargs
        ) as response:
            status = response.status_code
            if status in (401, 403):
                raise ConnectorError(
                    "Нет доступа. Проверьте ключ и права на проект.", status
                )
            if status == 429:
                raise ConnectorError(
                    "Лимит запросов сервиса. Подождите немного и повторите.", 429
                )
            if status >= 500:
                raise ConnectorError("Сервис аналитики временно недоступен.", 502)
            if not 200 <= status < 300:
                raise ConnectorError(
                    "Сервис отклонил запрос. Проверьте параметры подключения и отчёта.",
                    400,
                )
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > 8 * 1024 * 1024:
                    raise ConnectorError(
                        "Слишком много данных. Выберите меньший период."
                    )
                chunks.append(chunk)
            import json

            return json.loads(b"".join(chunks))
    except requests.Timeout:
        raise ConnectorError(
            "Сервис не ответил вовремя. Повторите запрос.", 504
        ) from None
    except requests.RequestException:
        raise ConnectorError(
            "Не удалось подключиться к сервису. Проверьте интернет.", 502
        ) from None
    except (ValueError, UnicodeDecodeError) as error:
        if isinstance(error, ConnectorError):
            raise
        raise ConnectorError(
            "Сервис вернул ответ в неизвестном формате.", 502
        ) from None
