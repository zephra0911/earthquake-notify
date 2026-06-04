import os
from dataclasses import dataclass

@dataclass
class Config:
    line_channel_access_token: str
    line_user_id: str

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
    )