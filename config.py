import os
from dataclasses import dataclass

@dataclass
class Config:
    line_channel_access_token: str
    line_user_id: str
    line_channel_secret: str = ""
    threshold_alert_tokyo_23ku:   str = "5+"
    threshold_alert_nationwide:   str = "6-"
    threshold_caution_tokyo_23ku: str = "4"
    threshold_caution_nationwide: str = "4"
    line_enabled: bool = True
    email_enabled: bool = False
    email_from: str = ""
    email_to: str = ""
    email_password: str = ""
    info_link_title: str = "Yahoo!天気・災害"
    info_link_url: str = "https://typhoon.yahoo.co.jp/weather/jp/earthquake/"
    show_intensity_areas: bool = True
    footer_note: str = "※電源やNW障害により通知されないこともあるよ。"

def load_config() -> Config:
    required = {
        "LINE_CHANNEL_ACCESS_TOKEN": "LINEチャネルアクセストークン",
        "LINE_USER_ID":              "LINEユーザーID",
    }
    missing = [k for k, label in required.items() if not os.getenv(k)]
    if missing:
        raise ValueError(f"環境変数が未設定です: {', '.join(missing)}")

    return Config(
        line_channel_access_token    = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
        line_user_id                 = os.getenv("LINE_USER_ID", ""),
        line_channel_secret          = os.getenv("LINE_CHANNEL_SECRET", ""),
        threshold_alert_tokyo_23ku   = os.getenv("THRESHOLD_ALERT_TOKYO_23KU",   "5+"),
        threshold_alert_nationwide   = os.getenv("THRESHOLD_ALERT_NATIONWIDE",   "6-"),
        threshold_caution_tokyo_23ku = os.getenv("THRESHOLD_CAUTION_TOKYO_23KU", "4"),
        threshold_caution_nationwide = os.getenv("THRESHOLD_CAUTION_NATIONWIDE", "4"),
        line_enabled                 = os.getenv("LINE_ENABLED", "true").lower() == "true",
        email_enabled                = os.getenv("EMAIL_ENABLED", "false").lower() == "true",
        email_from                   = os.getenv("EMAIL_FROM", ""),
        email_to                     = os.getenv("EMAIL_TO", ""),
        email_password               = os.getenv("EMAIL_PASSWORD", ""),
        info_link_title              = os.getenv("INFO_LINK_TITLE", "Yahoo!天気・災害"),
        info_link_url                = os.getenv("INFO_LINK_URL", "https://typhoon.yahoo.co.jp/weather/jp/earthquake/"),
        show_intensity_areas         = os.getenv("SHOW_INTENSITY_AREAS", "true").lower() == "true",
        footer_note                  = os.getenv("FOOTER_NOTE", "※電源やNW障害により通知されないこともあるよ。"),
    )
