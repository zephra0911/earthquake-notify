"""
store.py
Google Cloud Firestore を使った通知済みEventID管理モジュール

コレクション設計:
  コレクション名: earthquake_notify
  ドキュメントID: EventID（サニタイズ済み）
  フィールド:
    status      : "ALERTED" | "DETAILED"
    alerted_at  : 速報通知日時（ISO8601）
    detailed_at : 続報通知日時（ISO8601）
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

COLLECTION_NAME = "earthquake_notify"
STATUS_ALERTED  = "ALERTED"
STATUS_DETAILED = "DETAILED"


def get_firestore_client():
    """Firestore クライアントを返す"""
    try:
        from google.cloud import firestore
        return firestore.Client()
    except ImportError:
        raise ImportError(
            "google-cloud-firestore パッケージが未インストールです: "
            "pip install google-cloud-firestore"
        )


def get_status(client, event_id: str) -> Optional[str]:
    """EventID の通知状態を返す"""
    try:
        doc = client.collection(COLLECTION_NAME).document(_sanitize_key(event_id)).get()
        if doc.exists:
            return doc.to_dict().get("status")
        return None
    except Exception as e:
        logger.error(f"状態取得失敗: {e}")
        return None


def is_alerted(client, event_id: str) -> bool:
    """速報送信済みか確認"""
    return get_status(client, event_id) in (STATUS_ALERTED, STATUS_DETAILED)


def is_detailed(client, event_id: str) -> bool:
    """続報送信済みか確認"""
    return get_status(client, event_id) == STATUS_DETAILED


def mark_alerted(client, event_id: str) -> bool:
    """速報送信済みとして記録"""
    try:
        client.collection(COLLECTION_NAME).document(_sanitize_key(event_id)).set({
            "status":      STATUS_ALERTED,
            "alerted_at":  _now_iso(),
            "detailed_at": "",
        })
        logger.info(f"速報済みマーク完了: {event_id}")
        return True
    except Exception as e:
        logger.error(f"速報済みマーク失敗: {e}")
        return False


def mark_detailed(client, event_id: str) -> bool:
    """続報送信済みとして更新"""
    try:
        client.collection(COLLECTION_NAME).document(_sanitize_key(event_id)).update({
            "status":      STATUS_DETAILED,
            "detailed_at": _now_iso(),
        })
        logger.info(f"続報済みマーク完了: {event_id}")
        return True
    except Exception as e:
        # ドキュメントが存在しない場合は新規作成
        logger.warning(f"続報マーク: ドキュメントなし → 新規作成 ({event_id})")
        try:
            client.collection(COLLECTION_NAME).document(_sanitize_key(event_id)).set({
                "status":      STATUS_DETAILED,
                "alerted_at":  "",
                "detailed_at": _now_iso(),
            })
            return True
        except Exception as e2:
            logger.error(f"続報済みマーク失敗: {e2}")
            return False


def _sanitize_key(event_id: str) -> str:
    """FirestoreのドキュメントIDに使えない文字を除去"""
    if "/" in event_id:
        return event_id.rstrip("/").split("/")[-1][:500]
    forbidden = set('/\\.')
    return "".join(c for c in event_id if c not in forbidden)[:500]


def _now_iso() -> str:
    """現在日時をISO8601形式（UTC）で返す"""
    return datetime.now(timezone.utc).isoformat()