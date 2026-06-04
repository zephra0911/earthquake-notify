import logging
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

from config import load_config
from fetcher import fetch_feed, fetch_quake_detail
from checker import check_notify, build_alert_message, build_detail_message
from store import get_firestore_client, is_alerted, is_detailed, mark_alerted, mark_detailed
from notifier.line import send_line_with_retry


def earthquake_monitor(event, context):
    logger.info("=== 地震監視 開始 ===")

    try:
        cfg    = load_config()
        client = get_firestore_client()
    except Except