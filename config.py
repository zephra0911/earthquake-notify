import os
from dataclasses import dataclass

@dataclass
class Config:
    line_channel_access_token: str
    line_user_id: str
    line_channel_secret: str = ""
    threshold_tokyo_23ku: str = "4"
    threshold_nationwide: str = "5-"
    watchdog_enabled: bool = True
    weather_alert_enabled: bool = False
    email_enabled: bool = False
    email_from: str = ""
    email_to: str = ""
    email_password: str = ""

def load_config() -> Config:
    required = {
        "LINE_CHANNEL_ACCESS_TOKEN": "LINEチャネルアクセストークン",
        "LINE_USER_ID":              "LINEユーザーID",
    }
    missing = [k for k, label in required.items() if not os.getenv(k)]
    if missing:
        raise ValueError(f"環境変数が未設定です: {', '.join(missing)}")

    return Config(
        line_channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
        line_user_id              = os.getenv("LINE_USER_ID", ""),
        line_channel_secret       = os.getenv("LINE_CHANNEL_SECRET", ""),
        threshold_tokyo_23ku      = os.getenv("THRESHOLD_TOKYO_23KU", "4"),
        threshold_nationwide      = os.getenv("THRESHOLD_NATIONWIDE", "5-"),
        watchdog_enabled          = os.getenv("WATCHDOG_ENABLED", "true").lower() == "true",
        weather_alert_enabled     = os.getenv("WEATHER_ALERT_ENABLED", "false").lower() == "true",
        email_enabled             = os.getenv("EMAIL_ENABLED", "false").lower() == "true",
        email_from                = os.getenv("EMAIL_FROM", ""),
        email_to                  = os.getenv("EMAIL_TO", ""),
        email_password            = os.getenv("EMAIL_PASSWORD", ""),
    )