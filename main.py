import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import load_config
from fetcher import fetch_feed, fetch_quake_detail
from checker import (
    check_notify,
    build_quake_message,
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

_LEVEL_PRIORITY = {"none": 0, "caution": 1, "alert": 2}

def _level_priority(level: str) -> int:
    return _LEVEL_PRIORITY.get(level, 0)

JST = timezone(timedelta(hours=9))


def _format_updated_time(updated: str) -> str:
    if updated:
        try:
            dt = datetime.fromisoformat(updated).astimezone(JST)
            return dt.strftime("%m/%d %H:%M")
        except Exception:
            pass
    return "不明"


def _build_subject(level: str, detail, is_escalation: bool = False) -> str:
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

    if level == "alert":
        prefix = "【地震至急報告（更新）】" if is_escalation else "【地震至急報告】"
    else:
        prefix = "【地震注意喚起】"
    return f"{prefix} {time_str} {intensity_label} {area}"


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

    logger.debug(f"取得エントリ数: {len(entries)}")
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
    if entry.title != "震源・震度に関する情報":
        return False

    detail = fetch_quake_detail(entry)
    if detail is None:
        return False

    event_id      = detail.event_id  # 気象庁公式EventID（Serial間で共通）
    current_level = state.get(event_id)  # None | "caution" | "alert"

    result = check_notify(
        detail,
        cfg.threshold_alert_tokyo_23ku,
        cfg.threshold_alert_nationwide,
        cfg.threshold_caution_tokyo_23ku,
        cfg.threshold_caution_nationwide,
    )
    if not result.should_notify:
        logger.debug(f"通知不要: {event_id} / {result.reason}")
        return False

    if current_level is not None and _level_priority(result.level) <= _level_priority(current_level):
        logger.debug(f"既に同レベル以上で通知済みのためスキップ: {event_id} "
                     f"（記録済み: {current_level} / 今回: {result.level}）")
        return False

    is_escalation = current_level is not None
    if is_escalation:
        logger.info(f"レベルがエスカレーションしたため再通知: {event_id} "
                    f"（{current_level} → {result.level}）")
    else:
        logger.info(f"通知条件合致（{result.level}）: {result.reason}")

    subject = _build_subject(result.level, detail, is_escalation=is_escalation)
    body    = build_quake_message(detail, result,
                                  is_escalation=is_escalation,
                                  previous_level=current_level or "")

    if cfg.line_enabled:
        line_ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, subject + "\n" + body)
    else:
        line_ok = True
    if cfg.email_enabled:
        send_email_with_retry(cfg.email_from, cfg.email_to, cfg.email_password, subject, body)

    if line_ok:
        state[event_id] = result.level
        return True

    logger.error(f"通知 LINE送信失敗: {event_id}")
    return False


if __name__ == "__main__":
    main()
