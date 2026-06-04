import logging
import time

logger = logging.getLogger(__name__)

SMS_MAX_LENGTH = 160

def send_sms(account_sid, auth_token, from_number, to_numbers, message) -> dict:
    try:
        from twilio.rest import Client
    except ImportError:
        logger.error("twilio パッケージが未インストールです")
        return {"success": [], "failed": to_numbers}

    client = Client(account_sid, auth_token)
    trimmed_message = _trim_message(message)
    result = {"success": [], "failed": []}

    for to_number in to_numbers:
        try:
            msg = client.messages.create(
                body=trimmed_message,
                from_=from_number,
                to=to_number,
            )
            logger.info(f"SMS送信成功: {to_number} (SID: {msg.sid})")
            result["success"].append(to_number)
        except Exception as e:
            logger.error(f"SMS送信失敗: {to_number} / エラー: {e}")
            result["failed"].append(to_number)

    return result

def send_sms_with_retry(account_sid, auth_token, from_number, to_numbers, message, max_retry=3) -> dict:
    remaining  = list(to_numbers)
    all_success = []

    for attempt in range(1, max_retry + 1):
        result = send_sms(account_sid, auth_token, from_number, remaining, message)
        all_success.extend(result["success"])
        remaining = result["failed"]

        if not remaining:
            break

        if attempt < max_retry:
            wait = attempt * 5
            logger.warning(f"SMS リトライ {attempt}/{max_retry}（{wait}秒後）")
            time.sleep(wait)

    if remaining:
        logger.error(f"SMS最終失敗: {remaining}")

    return {"success": all_success, "failed": remaining}

def _trim_message(message: str) -> str:
    if len(message) <= SMS_MAX_LENGTH:
        return message
    return message[: SMS_MAX_LENGTH - 3] + "..."