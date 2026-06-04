import logging
from datetime import datetime, timezone

from config import load_config
from fetcher import fetch_feed, fetch_quake_detail
from checker import check_notify, build_alert_message, build_detail_message
from store import get_firestore_client, is_alerted, is_detailed, mark_alerted, mark_detailed
from notifier.line import send_line_with_retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def earthquake_monitor(event, context):
    logger.info("=== 地震監視 開始 ===")

    try:
        cfg    = load_config()
        client = get_firestore_client()
    except Exception as e:
        logger.error(f"初期化失敗: {e}")
        return "ERROR", 500

    try:
        entries = fetch_feed()
    except Exception as e:
        logger.error(f"フィード取得失敗: {e}")
        return "ERROR", 500

    for entry in entries:
        try:
            _process_entry(entry, cfg, client)
        except Exception as e:
            logger.error(f"エントリ処理失敗 ({entry.event_id}): {e}")
            continue

    logger.info("=== 地震監視 完了 ===")
    return "OK", 200


def watchdog_notify(event, context):
    now = datetime.now(timezone.utc).strftime("%m/%d %H:%M UTC")
    message = f"【監視稼働中】✅\n{now}\n地震監視システム 正常稼働中"

    try:
        cfg = load_config()
        ok  = send_line_with_retry(
            cfg.line_channel_access_token,
            cfg.line_user_id,
            message,
        )
        if ok:
            logger.info("死活確認メッセージ送信完了")
        else:
            logger.error("死活確認メッセージ送信失敗")
    except Exception as e:
        logger.error(f"死活確認 失敗: {e}")

    return "OK", 200


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

        ok = send_line_with_retry(
            cfg.line_channel_access_token,
            cfg.line_user_id,
            message,
        )
        if ok:
            mark_alerted(client, entry.event_id)
        else:
            logger.error(f"速報通知 LINE送信失敗: {entry.event_id}")

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

        ok = send_line_with_retry(
            cfg.line_channel_access_token,
            cfg.line_user_id,
            message,
        )
        if ok:
            mark_detailed(client, entry.event_id)
        else:
            logger.error(f"続報通知 LINE送信失敗: {entry.event_id}")