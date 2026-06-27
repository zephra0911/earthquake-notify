import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import load_config
from fetcher import fetch_feed, fetch_quake_detail
from checker import (
    check_notify,
    build_alert_message, build_detail_message, build_caution_message,
    _intensity_to_label, INTENSITY_ORDER,
)
from notifier.line import send_line_with_retry
from notifier.email import send_email_with_retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

STATE_FILE = Path("state/notified_events.json")
STATUS_ALERTED  = "ALERTED"
STATUS_DETAILED = "DETAILED"

JST = timezone(timedelta(hours=9))


def _format_updated_time(updated: str) -> str:
    if updated:
        try:
            dt = datetime.fromisoformat(updated).astimezone(JST)
            return f"(発表){dt.strftime('%m/%d %H:%M')}"
        except Exception:
            pass
    return "(発表)不明"


def _build_subject(prefix: str, detail) -> str:
    origin = detail.origin_time
    if origin and origin != "不明":
        try:
            dt = datetime.fromisoformat(origin).astimezone(JST)
            time_str = dt.strftime("%m/%d %H:%M")
        except Exception:
            time_str = _format_updated_time(detail.report_time)
    else:
        time_str = _format_updated_time(detail.report_time)

    intensity_label = _intensity_to_label(detail.max_intensity)

    if detail.hypocenter:
        area = detail.hypocenter
    elif detail.area_intensities:
        top = max(
            detail.area_intensities,
            key=lambda x: INTENSITY_ORDER.get(x.get("intensity", ""), 0),
        )
        area = top.get("area", "不明")
    else:
        area = "不明"

    return f"【{prefix}:{time_str}】{intensity_label} {area}"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"状態ファイル読み込み失敗（空で初期化）: {e}")
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    logger.info("=== 地震監視 開始 ===")

    try:
        cfg = load_config()
    except Exception as e:
        logger.error(f"設定読み込み失敗: {e}")
        return

    state = load_state()

    try:
        entries = fetch_feed()
    except Exception as e:
        logger.error(f"フィード取得失敗: {e}")
        return

    logger.info(f"取得エントリ数: {len(entries)}")
    changed = False

    for entry in entries:
        try:
            if _process_entry(entry, cfg, state):
                changed = True
        except Exception as e:
            logger.error(f"エントリ処理失敗 ({entry.event_id}): {e}")

    if changed:
        save_state(state)
        logger.info("状態ファイルを更新しました")

    logger.info("=== 地震監視 完了 ===")


def _process_entry(entry, cfg, state: dict) -> bool:
    event_id       = entry.event_id
    current_status = state.get(event_id)

    if entry.title == "震度速報":
        if current_status in (STATUS_ALERTED, STATUS_DETAILED):
            return False

        detail = fetch_quake_detail(entry)
        if detail is None:
            return False

        result = check_notify(
            detail,
            cfg.threshold_alert_tokyo_23ku,
            cfg.threshold_alert_nationwide,
            cfg.threshold_caution_tokyo_23ku,
            cfg.threshold_caution_nationwide,
        )
        if not result.should_notify:
            logger.info(f"通知不要: {event_id} / {result.reason}")
            return False

        logger.info(f"通知条件合致（速報/{result.level}）: {result.reason}")
        if result.level == "alert":
            message = build_alert_message(detail, result)
            subject = _build_subject("速報", detail)
        else:
            message = build_caution_message(detail, result)
            subject = _build_subject("注意速報", detail)

        if cfg.line_enabled:
            line_ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, message)
        else:
            line_ok = True
        if cfg.email_enabled:
            send_email_with_retry(cfg.email_from, cfg.email_to, cfg.email_password, subject, message)

        if line_ok:
            state[event_id] = STATUS_ALERTED
            return True

        logger.error(f"速報通知 LINE送信失敗: {event_id}")
        return False

    elif entry.title == "震源・震度に関する情報":
        if current_status == STATUS_DETAILED:
            return False
        if current_status != STATUS_ALERTED:
            return False

        detail = fetch_quake_detail(entry)
        if detail is None:
            return False

        result = check_notify(
            detail,
            cfg.threshold_alert_tokyo_23ku,
            cfg.threshold_alert_nationwide,
            cfg.threshold_caution_tokyo_23ku,
            cfg.threshold_caution_nationwide,
        )
        if result.level == "alert":
            message = build_detail_message(detail, result)
            subject = _build_subject("続報", detail)
        else:
            message = build_caution_message(detail, result)
            subject = _build_subject("注意続報", detail)

        if cfg.line_enabled:
            line_ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, message)
        else:
            line_ok = True
        if cfg.email_enabled:
            send_email_with_retry(cfg.email_from, cfg.email_to, cfg.email_password, subject, message)

        if line_ok:
            state[event_id] = STATUS_DETAILED
            return True

        logger.error(f"続報通知 LINE送信失敗: {event_id}")
        return False

    return False


if __name__ == "__main__":
    main()
