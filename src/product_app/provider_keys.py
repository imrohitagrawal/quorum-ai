from enum import StrEnum


class ProviderCredentialSource(StrEnum):
    APP_OWNED = "app_owned"
    NOT_CONFIGURED = "not_configured"
    BYO_OPENROUTER = "byo_openrouter"
