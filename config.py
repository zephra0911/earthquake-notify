import os
from dataclasses import dataclass

@dataclass
class Config:
    line_token: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str
    twilio_to_numbers: list[str]

def load_config() -> Config:
    required = {
        "LINE_TOKEN":         "LINE Notify トークン",
        "TWILIO_ACCOUNT_SID": "Twilio Account SID",
        "TWILIO_AUTH_TOKEN":  "Twilio Auth Token",
        "TWILIO_FROM_NUMBER": "Twilio 送信元番号",
        "TWILIO_TO_NUMBERS":  "SMS受信者番号（カンマ区切り）",
    }
    missing = [k for k, label in required.items() if not os.getenv(k)]
    if missing:
        raise ValueError(f"環境変数が未設定です: {', '.join(missing)}")

    to_numbers_raw = os.getenv("TWILIO_TO_NUMBERS", "")
    to_numbers = [n.strip() for n in to_numbers_raw.split(",") if n.strip()]

    return Config(
        line_token        = os.getenv("LINE_TOKEN", ""),
        twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token  = os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_from_number = os.getenv("TWILIO_FROM_NUMBER", ""),
        twilio_to_numbers  = to_numbers,
    )