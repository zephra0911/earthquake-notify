import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(from_addr: str, to_addr: str, password: str, subject: str, body: str) -> bool:
    """
    Gmail SMTPでメールを送信する。

    Args:
        from_addr: 送信元メールアドレス（Gmail）
        to_addr:   送信先メールアドレス（カンマ区切りで複数可）
        password:  Gmailアプリパスワード
        subject:   件名
        body:      本文

    Returns:
        True: 送信成功 / False: 送信失敗
    """
    try:
        msg = MIMEMultipart()
        msg["From"]    = from_addr
        msg["To"]      = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addr.split(","), msg.as_string())

        logger.info(f"メール送信成功: {to_addr}")
        return True

    except Exception as e:
        logger.error(f"メール送信失敗: {e}")
        return False


def send_email_with_retry(from_addr: str, to_addr: str, password: str, subject: str, body: str, max_retry: int = 3) -> bool:
    import time
    for attempt in range(1, max_retry + 1):
        if send_email(from_addr, to_addr, password, subject, body):
            return True
        if attempt < max_retry:
            wait = attempt * 5
            logger.warning(f"メール送信リトライ {attempt}/{max_retry}（{wait}秒後）")
            time.sleep(wait)

    logger.error(f"メール送信 {max_retry}回すべて失敗")
    return False