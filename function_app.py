import logging
import azure.functions as func
from datetime import datetime, timezone

from config import load_config
from fetcher import fetch_feed, fetch_quake_detail
from checker import check_notify, build_alert_message, build_detail_message
from store import get_table_client, is_alerted, is_detailed, mark_alerted, mark_detailed
from notifier.line import send_line_with_retry
from notifier.sms import send_sms_with_retry

logger = logging.getLogger(__name__)

app = func.FunctionApp()

@app.timer_trigger(
    schedule="0 */1 * * * *",
    arg_name="timer",
    run_on_startup=True,
)
def earthquake_monitor(timer: func.TimerRequest) -> None:
    logger.info("=== 地震監視 開始 ===")

    try:
        cfg    = load_config()
        client = get_table_client(cfg.storage_connection_string)
    except Exception as e:
        logger.error(f"初期化失敗: {e}")
        return

    try:
        entries = fetch_feed()
    except Exception as e:
        logger.error(f"フィード取得失敗: {e}")
        return

    for entry in entries:
        try:
            _process_entry(entry, cfg, client)
        except Exception as e:
            logger.error(f"エントリ処理失敗 ({entry.event_id}): {e}")
            continue

    logger.info("=== 地震監視 完了 ===")

def _process_entry(entry, cfg, client) -> None:
    title = entry.title

    if title == "震度速報":
        if is_alerted(client, entry.event_id):
            return

        detail = fetch_quake_detail(entry)
        if detail is None:
            return

        result = check_notify(detail)
        if not result.should_notify:
            logger.info(f"通知不要: {entry.event_id} / {result.reason}")
            return

        logger.info(f"通知条件合致（速報）: {result.reason}")
        message = build_alert_message(detail, result)

        line_ok = send_line_with_retry(cfg.line_token, message)
        sms_result = send_sms_with_retry(
            cfg.twilio_account_sid,
            cfg.twilio_auth_token,
            cfg.twilio_from_number,
            cfg.twilio_to_numbers,
            message,
        )

        if line_ok or len(sms_result["success"]) > 0:
            mark_alerted(client, entry.event_id)
        else:
            logger.error(f"速報通知 LINE・SMS ともに失敗: {entry.event_id}")

    elif title == "震源・震度に関する情報":
        if is_detailed(client, entry.event_id):
            return

        if not is_alerted(client, entry.event_id):
            return

        detail = fetch_quake_detail(entry)
        if detail is None:
            return

        result = check_notify(detail)
        message = build_detail_message(detail, result)

        line_ok = send_line_with_retry(cfg.line_token, message)
        if line_ok:
            mark_detailed(client, entry.event_id)
        else:
            logger.error(f"続報通知 LINE送信失敗: {entry.event_id}")

@app.timer_trigger(
    schedule="0 0 */1 * * *",
    arg_name="timer",
    run_on_startup=False,
)
def watchdog_notify(timer: func.TimerRequest) -> None:
    now = datetime.now(timezone.utc).strftime("%m/%d %H:%M UTC")
    message = f"【監視稼働中】✅\n{now}\n地震監視システム 正常稼働中"

    try:
        cfg = load_config()
        ok  = send_line_with_retry(cfg.line_token, message)
        if ok:
            logger.info("死活確認メッセージ送信完了")
        else:
            logger.error("死活確認メッセージ送信失敗")
    except Exception as e:
        logger.error(f"死活確認 失敗: {e}")