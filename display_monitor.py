#!/usr/bin/env python3

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.append('/home/makoto/raspberrypi-tm1637')
import tm1637
import RPi.GPIO as GPIO

CLK = 17
DIO = 27
BUZZER_PIN = 22

DISPLAY_STATUS_FILE = '/home/makoto/earthquake-notify/state/display_status.json'
POLL_INTERVAL = 10   # 秒
CRON_TIMEOUT  = 600  # 10分

JST = timezone(timedelta(hours=9))

INTENSITY_MAP = {
    "7": 70, "6+": 65, "6-": 60,
    "5+": 55, "5-": 50, "4": 40, "3": 30,
}

# ループをまたぐ状態
_alert_shown_until = None   # alert 表示終了時刻（datetime）
_caution_shown     = False  # caution 表示済みフラグ
_e_beep_done       = set()  # beep 済みエラーコード
_last_e01_mono     = None   # E-01 最終beep のモノトニック時刻


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def beep(duration: float) -> None:
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    time.sleep(duration)
    GPIO.output(BUZZER_PIN, GPIO.LOW)


def intensity_to_display(intensity: str) -> str:
    """震度コード → 2桁数字文字列（例: "6-" → "60"）"""
    return f"{INTENSITY_MAP.get(str(intensity), 0):02d}"


def load_status() -> dict:
    try:
        return json.loads(Path(DISPLAY_STATUS_FILE).read_text(encoding='utf-8'))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 表示状態の決定
# ---------------------------------------------------------------------------

def get_display_state(data: dict, now: datetime) -> dict:
    global _alert_shown_until, _caution_shown, _last_e01_mono

    # 優先度 1: E-01（cronタイムアウト）
    last_run_str = data.get("last_run")
    if last_run_str:
        try:
            last_run = datetime.fromisoformat(last_run_str)
            if (now - last_run).total_seconds() > CRON_TIMEOUT:
                return {"type": "E-01"}
        except (ValueError, TypeError):
            pass

    # 優先度 2: エラー
    if data.get("status") == "error":
        return {"type": "error", "code": data.get("error_code", "E-03")}
    else:
        _e_beep_done.clear()  # エラー解消時にbeep履歴をリセット

    # 優先度 3: alert
    alert_level   = data.get("alert_level", "none")
    max_intensity = data.get("max_intensity")

    if alert_level == "alert":
        if _alert_shown_until is None:
            _alert_shown_until = now + timedelta(minutes=3)
        if now < _alert_shown_until:
            return {"type": "alert", "intensity": max_intensity}
        return {"type": "normal"}
    else:
        _alert_shown_until = None

    # 優先度 4: caution
    if alert_level == "caution":
        if not _caution_shown:
            return {"type": "caution", "intensity": max_intensity}
        return {"type": "normal"}
    else:
        _caution_shown = False

    # 優先度 5: 正常（時刻表示）
    return {"type": "normal"}


# ---------------------------------------------------------------------------
# 表示実行
# ---------------------------------------------------------------------------

def _show_time_until(tm_dev, deadline: float) -> None:
    """deadline まで時刻を1秒ごとコロン点滅で表示する"""
    colon = True
    while time.monotonic() < deadline:
        t = datetime.now(JST)
        tm_dev.numbers(t.hour, t.minute, colon=colon)
        colon = not colon
        time.sleep(1.0)


def execute_display(state: dict, tm_dev) -> None:
    global _caution_shown, _last_e01_mono

    stype    = state["type"]
    deadline = time.monotonic() + POLL_INTERVAL

    if stype == "alert":
        num  = intensity_to_display(state.get("intensity") or "")
        text = f"A-{num}"
        while time.monotonic() < deadline:
            tm_dev.show(text)
            beep(0.1)          # 短音（点灯と同期）
            time.sleep(0.4)    # ON 合計 0.5 秒
            tm_dev.show('    ')
            time.sleep(0.5)    # OFF 0.5 秒

    elif stype == "caution":
        num  = intensity_to_display(state.get("intensity") or "")
        text = f"C-{num}"
        for _ in range(2):
            tm_dev.show(text)
            beep(0.5)          # 長音（点灯と同期）
            tm_dev.show('    ')
            time.sleep(0.5)    # OFF 0.5 秒
        _caution_shown = True
        _show_time_until(tm_dev, deadline)  # 残り時間は時刻表示

    elif stype == "E-01":
        now_mono   = time.monotonic()
        do_beep    = (_last_e01_mono is None or now_mono - _last_e01_mono >= 300)
        while time.monotonic() < deadline:
            tm_dev.show('E-01')
            if do_beep:
                beep(1.0)
                _last_e01_mono = time.monotonic()
                do_beep = False
            else:
                time.sleep(1.0)
            tm_dev.show('    ')
            time.sleep(0.5)

    elif stype == "error":
        code     = state.get("code", "E-03")
        do_beep  = code not in _e_beep_done
        while time.monotonic() < deadline:
            tm_dev.show(code)
            if do_beep:
                beep(1.0)
                _e_beep_done.add(code)
                do_beep = False
            else:
                time.sleep(1.0)
            tm_dev.show('    ')
            time.sleep(0.5)

    else:  # normal
        _show_time_until(tm_dev, deadline)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)

    tm_dev = tm1637.TM1637(clk=CLK, dio=DIO)
    tm_dev.brightness(2)

    # 起動シーケンス
    beep(0.1)
    tm_dev.show('bOOt')

    # display_status.json が生成されるまで待機
    while not Path(DISPLAY_STATUS_FILE).exists():
        time.sleep(1)

    try:
        while True:
            now  = datetime.now(JST)
            data = load_status()
            state = get_display_state(data, now)
            execute_display(state, tm_dev)
    except KeyboardInterrupt:
        pass
    finally:
        tm_dev.show('    ')
        GPIO.cleanup()


if __name__ == '__main__':
    main()
