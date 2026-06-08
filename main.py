import logging
import json
import hashlib
import hmac
import base64
import functions_framework
from datetime import datetime, timezone, timedelta

from config import load_config
from fetcher import fetch_feed, fetch_quake_detail, fetch_weather_feed, fetch_weather_detail
from checker import check_notify, build_alert_message, build_detail_message
from store import (
    get_firestore_client, is_alerted, is_detailed,
    mark_alerted, mark_detailed, get_recent_earthquakes,
    is_weather_alerted, mark_weather_alerted,
)
from notifier.line import send_line_with_retry, reply_line
from notifier.email import send_email_with_retry

try:
    import google.cloud.logging
    google.cloud.logging.Client().setup_logging()
except Exception:
    pass

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


@functions_framework.cloud_event
def earthquake_monitor(_cloud_event):
    logger.info("=== 地震監視 開始 ===")

    try:
        cfg    = load_config()
        client = get_firestore_client()
    except Exception as e:
        logger.error(f"初期化失敗: {e}")
        return

    try:
        entries = fetch_feed()
    except Exception as e:
        logger.error(f"フィード取得失敗: {e}")
        return

    logger.info(f"取得エントリ数: {len(entries)}")

    for entry in entries:
        try:
            _process_entry(entry, cfg, client)
        except Exception as e:
            logger.error(f"エントリ処理失敗 ({entry.event_id}): {e}")
            continue

    if cfg.weather_alert_enabled:
        try:
            weather_entries = fetch_weather_feed()
            for w_entry in weather_entries:
                try:
                    _process_weather_entry(w_entry, cfg, client)
                except Exception as e:
                    logger.error(f"気象警報エントリ処理失敗 ({w_entry.event_id}): {e}")
        except Exception as e:
            logger.error(f"気象警報フィード取得失敗: {e}")

    logger.info("=== 地震監視 完了 ===")


def _process_entry(entry, cfg, client) -> None:
    title = entry.title

    if title == "震度速報":
        if is_alerted(client, entry.event_id):
            return

        detail = fetch_quake_detail(entry)
        if detail is None:
            return

        result = check_notify(detail, cfg.threshold_tokyo_23ku, cfg.threshold_nationwide)
        if not result.should_notify:
            logger.info(f"通知不要: {entry.event_id} / {result.reason}")
            return

        logger.info(f"通知条件合致（速報）: {result.reason}")
        message = build_alert_message(detail, result)
        subject = "【地震速報】⚠️ PMH稼働確認を準備してください"

        line_ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, message)
        if cfg.email_enabled:
            send_email_with_retry(cfg.email_from, cfg.email_to, cfg.email_password, subject, message)

        if line_ok:
            mark_alerted(client, entry.event_id, detail)
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

        result = check_notify(detail, cfg.threshold_tokyo_23ku, cfg.threshold_nationwide)
        message = build_detail_message(detail, result)
        subject = "【地震詳細・続報】⚠️ PMH稼働確認を実施してください"

        line_ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, message)
        if cfg.email_enabled:
            send_email_with_retry(cfg.email_from, cfg.email_to, cfg.email_password, subject, message)

        if line_ok:
            mark_detailed(client, entry.event_id)
        else:
            logger.error(f"続報通知 LINE送信失敗: {entry.event_id}")


@functions_framework.cloud_event
def watchdog_notify(_cloud_event):
    try:
        cfg = load_config()
    except Exception as e:
        logger.error(f"設定読み込み失敗: {e}")
        return

    if not cfg.watchdog_enabled:
        logger.info("ウォッチドッグ無効のためスキップ")
        return

    now     = datetime.now(JST).strftime("%m/%d %H:%M JST")
    message = f"【監視稼働中】✅\n{now}\n地震監視システム 正常稼働中"

    ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, message)
    if ok:
        logger.info("死活確認メッセージ送信完了")
    else:
        logger.error("死活確認メッセージ送信失敗")


@functions_framework.cloud_event
def daily_summary(_cloud_event):
    logger.info("=== 日次サマリー 開始 ===")

    try:
        cfg    = load_config()
        client = get_firestore_client()
    except Exception as e:
        logger.error(f"初期化失敗: {e}")
        return

    # 昨日09:00 JST 〜 本日09:00 JST を集計対象とする
    today_9 = datetime.now(JST).replace(hour=9, minute=0, second=0, microsecond=0)
    yest_9  = today_9 - timedelta(days=1)
    records    = get_recent_earthquakes(
        client,
        since=yest_9.astimezone(timezone.utc),
        until=today_9.astimezone(timezone.utc),
    )
    ai_comment = _generate_safety_comment(records)
    message    = _build_daily_summary_message(records, ai_comment, yest_9, today_9)

    ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, message)
    if ok:
        logger.info("日次サマリー送信完了")
    else:
        logger.error("日次サマリー送信失敗")

    logger.info("=== 日次サマリー 完了 ===")


@functions_framework.http
def line_webhook(request):
    try:
        cfg = load_config()
    except Exception as e:
        logger.error(f"設定読み込み失敗: {e}")
        return ("Internal Server Error", 500)

    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)

    if not _verify_line_signature(cfg.line_channel_secret, body, signature):
        logger.warning("LINE署名検証失敗")
        return ("Forbidden", 403)

    try:
        events = json.loads(body).get("events", [])
    except Exception:
        return ("Bad Request", 400)

    for event in events:
        if event.get("type") != "message":
            continue
        if event.get("message", {}).get("type") != "text":
            continue
        if event["message"]["text"].strip() != "状況は？":
            continue

        reply_token = event.get("replyToken", "")
        # 00000... はLINEのテストイベント用ダミートークン
        if not reply_token or set(reply_token) == {"0"}:
            continue

        details = _fetch_live_quake_status()
        message = _build_status_message(details)
        reply_line(cfg.line_channel_access_token, reply_token, message)

    return ("OK", 200)


def _verify_line_signature(channel_secret: str, body: str, signature: str) -> bool:
    if not channel_secret or not signature:
        return False
    digest   = hmac.new(channel_secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _generate_safety_comment(records: list) -> str:
    try:
        import anthropic
        ai_client = anthropic.Anthropic()

        if not records:
            record_text = "昨日の通知対象地震: なし"
        else:
            lines = []
            for r in records:
                hypocenter = r.get("hypocenter", "不明")
                magnitude  = r.get("magnitude", "不明")
                intensity  = r.get("max_intensity", "不明")
                lines.append(f"・{hypocenter} M{magnitude} 最大震度{intensity}")
            record_text = "\n".join(lines)

        response = ai_client.messages.create(
            model="claude-opus-4-8",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    "以下は昨日の地震記録です。政府共通基盤（PMH）の運用監視担当者向けに、"
                    "今日の安全状況について50文字以内の簡潔な日本語コメントを1文で生成してください。\n\n"
                    + record_text
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"AIコメント生成失敗: {e}")
        return "本日も安全な一日をお過ごしください。"


def _build_daily_summary_message(
    records: list,
    ai_comment: str,
    since: datetime,
    until: datetime,
) -> str:
    date_str  = until.strftime("%Y/%m/%d")
    since_str = since.strftime("%m/%d %H:%M")
    until_str = until.strftime("%m/%d %H:%M")
    threshold_status = "⚠️ 閾値超過あり" if records else "✅ 閾値超過なし"

    lines = [
        f"【日次サマリー】{date_str}",
        f"対象: {since_str} 〜 {until_str} JST",
        "",
        threshold_status,
    ]

    if records:
        lines.append(f"▼ 通知した地震（{len(records)}件）")
        for r in records[:5]:
            hypocenter   = r.get("hypocenter", "不明")
            magnitude    = r.get("magnitude", "")
            intensity    = r.get("max_intensity", "不明")
            mag_str      = f" M{magnitude}" if magnitude else ""
            lines.append(f"  {hypocenter}{mag_str} 最大震度{intensity}")
        if len(records) > 5:
            lines.append(f"  … 他 {len(records) - 5} 件")
    else:
        lines.append("▼ 通知した地震: なし（閾値以下）")

    lines += ["", f"🤖 {ai_comment}", "状況確認は『状況は？』と入力してください。"]
    return "\n".join(lines)


def _fetch_live_quake_status(max_entries: int = 5) -> list:
    try:
        entries = fetch_feed()
        detail_entries = [e for e in entries if e.title == "震源・震度に関する情報"]
        alert_entries  = [e for e in entries if e.title == "震度速報"]
        targets = (detail_entries + alert_entries)[:max_entries]

        results = []
        for entry in targets:
            try:
                detail = fetch_quake_detail(entry)
                if detail:
                    results.append(detail)
            except Exception:
                continue
        return results
    except Exception as e:
        logger.error(f"JMAライブ取得失敗: {e}")
        return []


def _build_status_message(details: list) -> str:
    time_str = datetime.now(JST).strftime("%m/%d %H:%M JST")

    if not details:
        return (
            f"【状況確認】{time_str}\n\n"
            "直近の地震情報: なし\n"
            "システム正常稼働中です。"
        )

    lines = [
        f"【状況確認】{time_str}",
        "",
        f"▼ 直近の地震情報（{len(details)}件）",
    ]
    for d in details:
        hypocenter = d.hypocenter or "不明"
        mag_str    = f" M{d.magnitude}" if d.magnitude else ""
        intensity  = d.max_intensity or "-"
        origin     = _format_origin_time(d.origin_time)
        tsunami    = f" {d.tsunami}" if d.tsunami and d.tsunami != "なし" else ""
        lines.append(f"  [{origin}]")
        lines.append(f"  {hypocenter}{mag_str} 最大震度{intensity}{tsunami}")

    return "\n".join(lines)


def _format_origin_time(origin_time: str) -> str:
    try:
        dt = datetime.fromisoformat(origin_time)
        return dt.astimezone(JST).strftime("%m/%d %H:%M")
    except Exception:
        return origin_time[:16] if len(origin_time) >= 16 else origin_time


def _process_weather_entry(entry, cfg, client) -> None:
    if is_weather_alerted(client, entry.event_id):
        return

    detail = fetch_weather_detail(entry)
    if detail is None:
        return

    message = _build_weather_alert_message(detail)
    ok = send_line_with_retry(cfg.line_channel_access_token, cfg.line_user_id, message)
    if ok:
        mark_weather_alerted(client, entry.event_id)
        logger.info(f"気象警報通知完了: {entry.event_id} ({detail.info_type})")
    else:
        logger.error(f"気象警報 LINE送信失敗: {entry.event_id}")


def _build_weather_alert_message(detail) -> str:
    type_map   = {"発表": "発表", "更新": "更新", "訂正": "訂正", "取消": "解除"}
    type_label = type_map.get(detail.info_type, "発表")
    is_cancel  = detail.info_type == "取消"

    if detail.is_special:
        kind_label = "気象特別警報"
        icon       = "✅" if is_cancel else "🚨"
    else:
        kind_label = "気象警報・注意報"
        icon       = "✅" if is_cancel else "⚠️"

    now_str = datetime.now(JST).strftime("%m/%d %H:%M JST")
    header  = f"{icon}【{kind_label} {type_label}】{now_str}"

    summary = _build_weather_summary(detail.areas)
    return f"{header}\n{summary}" if summary else header


def _warning_severity(w: str) -> int:
    if "特別警報" in w:
        return 3
    if "警報" in w:
        return 2
    return 1  # 注意報


def _build_weather_summary(areas: list, max_chars: int = 80) -> str:
    # 警報種別ごとに対象地域を集約
    by_type: dict[str, list[str]]      = {}
    by_cancelled: dict[str, list[str]] = {}

    for area in areas:
        for w in area["warnings"]:
            by_type.setdefault(w, []).append(area["name"])
        for w in area["cancelled"]:
            by_cancelled.setdefault(w, []).append(area["name"])

    # 深刻度の高い順にソート
    active    = sorted(by_type.items(),      key=lambda x: _warning_severity(x[0]), reverse=True)
    cancelled = sorted(by_cancelled.items(), key=lambda x: _warning_severity(x[0]), reverse=True)

    parts = [f"{w}: {'・'.join(names)}"          for w, names in active]
    parts += [f"{w}（解除）: {'・'.join(names)}" for w, names in cancelled]

    # 80字以内に収める
    result = ""
    for i, part in enumerate(parts):
        sep       = " / " if result else ""
        candidate = result + sep + part
        if len(candidate) <= max_chars:
            result = candidate
        else:
            suffix = f" 他{len(parts) - i}件"
            if result and len(result) + len(suffix) <= max_chars:
                result += suffix
            elif not result:
                result = part[:max_chars - 1] + "…"
            break

    return result
