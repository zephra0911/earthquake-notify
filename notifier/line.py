import requests
import logging
import time

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
REQUEST_TIMEOUT = 10


def send_line(channel_access_token: str, user_id: str, message: str) -> bool:
    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}]
    }

    try:
        resp = requests.post(
            LINE_API_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        logger.info("LINE通知送信成功")
        return True

    except requests.HTTPError as e:
        logger.error(f"LINE通知 HTTPエラー: {e} / レスポンス: {resp.text}")
        return False

    except requests.RequestException as e:
        logger.error(f"LINE通知 通信エラー: {e}")
        return False


def send_line_with_retry(channel_access_token: str, user_id: str, message: str, max_retry: int = 3) -> bool:
    for attempt in range(1, max_retry + 1):
        if send_line(channel_access_token, user_id, message):
            return True
        if attempt < max_retry:
            wait = attempt * 5
            logger.warning(f"LINE通知リトライ {attempt}/{max_retry}（{wait}秒後）")
            time.sleep(wait)

    logger.error(f"LINE通知 {max_retry}回すべて失敗")
    return False