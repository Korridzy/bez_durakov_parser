"""Connection forms and capabilities shared by the UI and analytics tools."""


def field(
    key, label, *, secret=False, placeholder="", help="", kind="text", options=None
):
    return dict(
        key=key,
        label=label,
        secret=secret,
        placeholder=placeholder,
        help=help,
        kind=kind,
        options=options,
    )


CATALOG = [
    dict(
        id="metrika",
        name="Яндекс Метрика",
        icon="metrika",
        color="#efb526",
        description="Посещаемость, источники и цели",
        docs="https://yandex.ru/dev/metrika/ru/intro/authorization",
        fields=[
            field("counter_id", "ID счётчика", placeholder="12345678"),
            field(
                "token",
                "OAuth-токен",
                secret=True,
                help="Нужен доступ к статистике счётчика.",
            ),
        ],
        reports=["overview", "channels", "devices", "pages", "geography", "goals"],
    ),
    dict(
        id="ga4",
        name="Google Analytics 4",
        icon="ga4",
        color="#e58e2c",
        description="Аудитория, трафик и события",
        docs="https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart",
        fields=[
            field("property_id", "Property ID", placeholder="123456789"),
            field(
                "service_account",
                "Ключ сервисного аккаунта",
                secret=True,
                kind="json",
                help="JSON из Google Cloud. Добавьте client_email в ресурс GA4 с ролью «Читатель».",
            ),
        ],
        reports=["overview", "channels", "devices", "pages", "geography", "events"],
    ),
    dict(
        id="matomo",
        name="Matomo",
        icon="matomo",
        color="#399b9a",
        description="Веб-аналитика вашего сайта",
        docs="https://developer.matomo.org/api-reference/reporting-api",
        fields=[
            field(
                "base_url", "Адрес Matomo", placeholder="https://analytics.example.com"
            ),
            field("site_id", "ID сайта", placeholder="1"),
            field(
                "token",
                "Token auth",
                secret=True,
                help="Токен пользователя с доступом только на просмотр.",
            ),
        ],
        reports=[
            "overview",
            "channels",
            "devices",
            "pages",
            "geography",
            "events",
            "goals",
        ],
    ),
    dict(
        id="amplitude",
        name="Amplitude",
        icon="amplitude",
        color="#5475dd",
        description="Пользователи и продуктовые события",
        docs="https://www.amplitude.com/docs/apis/analytics/dashboard-rest",
        fields=[
            field("api_key", "API key", secret=True),
            field("secret_key", "Secret key", secret=True),
            field("region", "Регион", kind="select", options=["US", "EU"]),
        ],
        reports=["overview", "events"],
    ),
    dict(
        id="mixpanel",
        name="Mixpanel",
        icon="mixpanel",
        color="#785cce",
        description="События и поведение пользователей",
        docs="https://developer.mixpanel.com/reference/service-accounts",
        fields=[
            field("project_id", "Project ID"),
            field("username", "Service account username"),
            field("secret", "Service account secret", secret=True),
            field("region", "Регион", kind="select", options=["US", "EU", "IN"]),
        ],
        reports=["overview", "events"],
    ),
    dict(
        id="posthog",
        name="PostHog",
        icon="posthog",
        color="#ba7e4f",
        description="Продуктовая аналитика и события",
        docs="https://posthog.com/docs/api/overview",
        fields=[
            field("project_id", "Project ID"),
            field(
                "token",
                "Personal API key",
                secret=True,
                help="Разрешения query:read и project:read.",
            ),
            field("region", "Регион", kind="select", options=["US", "EU"]),
        ],
        reports=["overview", "events", "pages", "devices", "geography"],
    ),
]

PROVIDERS = {item["id"]: item for item in CATALOG}
REPORT_NAMES = {
    "overview": "Обзор",
    "channels": "Каналы",
    "devices": "Устройства",
    "pages": "Страницы",
    "geography": "География",
    "goals": "Цели",
    "events": "События",
}
