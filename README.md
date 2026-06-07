# earthquake-notify

地震発生時にLINEとメールで自動通知するシステム。
デジタル庁PMH（政府共通基盤）システムの運用監視を支援することを目的としています。

---

## システム概要

### 通知条件
- **東京23区**: 震度4以上（環境変数 `THRESHOLD_TOKYO_23KU` で変更可）
- **全国**: 震度5弱以上（環境変数 `THRESHOLD_NATIONWIDE` で変更可）

### 通知内容
1. **震度速報（VXSE51）**: 地震発生直後にLINE・メールで速報
2. **震源・震度情報（VXSE53）**: 詳細情報をLINEで続報

### 通知先
- LINE Messaging API（個人 or グループ）
- Gmail SMTP（メール）

---

## アーキテクチャ

```
気象庁XML（eqvol_l.xml）
     ↓ 1分毎ポーリング
Cloud Scheduler
     ↓ Pub/Sub
Cloud Functions（earthquake-monitor）
     ↓ 震度判定
Firestore（重複防止・状態管理）
     ↓ 閾値超過時
LINE Messaging API + Gmail SMTP
```

---

## GCPプロジェクト情報

| 項目 | 値 |
|------|-----|
| プロジェクトID | `earthquake-notify-497921` |
| リージョン | `asia-northeast1`（東京） |
| GitHubリポジトリ | `zephra0911/earthquake-notify` |

---

## Cloud Functionsの構成

| 関数名 | トリガー | 役割 |
|--------|---------|------|
| `earthquake-monitor` | Pub/Sub（1分毎） | 地震監視メイン |
| `watchdog-notify` | Pub/Sub（15分毎） | 死活確認通知 |
| `daily-summary` | Pub/Sub（毎朝9時JST） | 日次サマリー・AIコメント通知 |
| `line-webhook` | HTTP | LINE「状況は？」返信 |

---

## ファイル構成

```
earthquake-notify/
├── main.py              # エントリーポイント（earthquake_monitor, watchdog_notify, daily_summary, line_webhook）
├── config.py            # 環境変数管理
├── fetcher.py           # 気象庁XML取得
├── checker.py           # 震度判定・メッセージ生成
├── store.py             # Firestore操作（重複防止）
├── notifier/
│   ├── line.py          # LINE Messaging API送信
│   └── email.py         # Gmail SMTP送信
├── requirements.txt
└── .github/
    └── workflows/
        └── deploy.yml   # GitHub Actions（自動デプロイ）
```

---

## 環境変数一覧

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINEチャネルアクセストークン | 必須 |
| `LINE_USER_ID` | LINE送信先ユーザーID or グループID | 必須 |
| `THRESHOLD_TOKYO_23KU` | 東京23区の閾値 | `4` |
| `THRESHOLD_NATIONWIDE` | 全国の閾値 | `5-` |
| `WATCHDOG_ENABLED` | 死活監視通知オン/オフ | `true` |
| `EMAIL_ENABLED` | メール通知オン/オフ | `false` |
| `EMAIL_FROM` | 送信元Gmailアドレス | - |
| `EMAIL_TO` | 送信先メールアドレス | - |
| `EMAIL_PASSWORD` | Gmailアプリパスワード | - |
| `LINE_CHANNEL_SECRET` | LINE Webhookの署名検証用シークレット | `line_webhook`使用時に必須 |
| `ANTHROPIC_API_KEY` | Claude API キー（日次サマリーのAIコメント生成） | `daily_summary`使用時に必須 |

---

## 環境変数の変更方法

### gcloudコマンド（推奨）
```bash
gcloud run services update earthquake-monitor \
  --region=asia-northeast1 \
  --update-env-vars "THRESHOLD_TOKYO_23KU=4"
```

### Cloud Console（スマホ可）
```
console.cloud.google.com
  → Cloud Run → earthquake-monitor
  → 編集とデプロイの新リビジョン
  → 変数とシークレット
  → 変更 → デプロイ
```

---

## デプロイ方法

```bash
git add .
git commit -m "変更内容"
git push origin main
# GitHub Actionsが自動でCloud Functionsにデプロイ
```

---

## ローカルテスト

```bash
# 依存パッケージインストール
pip install -r requirements.txt
pip install google-cloud-firestore google-cloud-logging

# GCP認証
gcloud auth application-default login

# テスト実行（閾値を1に下げて通知テスト）
python -c "
import os
os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'トークン'
os.environ['LINE_USER_ID'] = 'ユーザーID'
os.environ['THRESHOLD_TOKYO_23KU'] = '1'
os.environ['THRESHOLD_NATIONWIDE'] = '1'
from main import earthquake_monitor
earthquake_monitor(None, None)
"
```

---

## Firestore

| 項目 | 値 |
|------|-----|
| コレクション名 | `earthquake_notify` |
| ドキュメントID | EventID（サニタイズ済み） |
| フィールド | `status`, `alerted_at`(Timestamp), `detailed_at`, `hypocenter`, `magnitude`, `max_intensity`, `origin_time`, `tsunami` |

状態: `ALERTED`（速報済み）→ `DETAILED`（続報済み）

---

## TODO

### 優先度高
- [x] 毎朝9時 日次サマリー通知機能
  - Cloud Schedulerに毎朝9時（JST）のジョブを追加（`daily-summary-topic` Pub/Sub）
  - Firestoreから前日〜当日朝の地震記録を取得（`alerted_at` Timestamp範囲クエリ）
  - AIによる「今日の安全コメント」を生成（Claude claude-opus-4-8）
  - 末尾に「状況確認は『状況は？』と入力」の案内を追加

- [x] LINE「状況は？」サマリー返信機能
  - `line_webhook`関数を追加（HTTPトリガー、署名検証付き）
  - Cloud FunctionsにHTTPトリガーで新規デプロイ
  - LINE DevelopersコンソールでWebhook URLを登録（要手動設定）

### 優先度低
- [ ] チームメンバーをLINEグループに追加
  - チームLINEグループを作成
  - BotをQRコードで招待
  - GCPの`LINE_USER_ID`をグループIDに変更
