from dataclasses import dataclass
from fetcher import QuakeDetail

TOKYO_23KU = {
    "東京２３区",
    "千代田区", "中央区", "港区", "新宿区", "文京区",
    "台東区", "墨田区", "江東区", "品川区", "目黒区",
    "大田区", "世田谷区", "渋谷区", "中野区", "杉並区",
    "豊島区", "北区", "荒川区", "板橋区", "練馬区",
    "足立区", "葛飾区", "江戸川区",
}

INTENSITY_ORDER = {
    "1": 1, "2": 2, "3": 3, "4": 4,
    "5-": 5, "5+": 6, "6-": 7, "6+": 8, "7": 9,
}

@dataclass
class CheckResult:
    should_notify: bool
    level: str          # "alert" | "caution" | "none"
    reason: str

def _intensity_value(intensity: str) -> int:
    return INTENSITY_ORDER.get(intensity.strip(), 0)

def _is_gte(intensity: str, threshold: str) -> bool:
    return _intensity_value(intensity) >= _intensity_value(threshold)

def check_notify(
    detail: QuakeDetail,
    threshold_alert_tokyo_23ku:   str = "5+",
    threshold_alert_nationwide:   str = "6-",
    threshold_caution_tokyo_23ku: str = "4",
    threshold_caution_nationwide: str = "4",
) -> CheckResult:
    alert_areas   = []
    caution_areas = []

    for item in detail.area_intensities:
        area      = item.get("area", "")
        pref      = item.get("pref", "")
        intensity = item.get("intensity", "")
        entry     = {"pref": pref, "area": area, "intensity": intensity}

        if area in TOKYO_23KU:
            # 東京23区は専用閾値のみで判定し、全国判定の対象外とする
            thr_alert, thr_caution, trigger = (
                threshold_alert_tokyo_23ku, threshold_caution_tokyo_23ku, "23ku"
            )
        else:
            thr_alert, thr_caution, trigger = (
                threshold_alert_nationwide, threshold_caution_nationwide, "nationwide"
            )

        if _is_gte(intensity, thr_alert):
            alert_areas.append({**entry, "trigger": trigger})
        elif _is_gte(intensity, thr_caution):
            caution_areas.append({**entry, "trigger": trigger})

    if alert_areas:
        reasons = []
        if any(a["trigger"] == "23ku"       for a in alert_areas):
            reasons.append("東京23区で{}以上を観測".format(_intensity_to_label(threshold_alert_tokyo_23ku)))
        if any(a["trigger"] == "nationwide" for a in alert_areas):
            reasons.append("全国で{}以上を観測".format(_intensity_to_label(threshold_alert_nationwide)))
        return CheckResult(
            should_notify=True, level="alert",
            reason=" / ".join(reasons),
        )

    if caution_areas:
        reasons = []
        if any(a["trigger"] == "23ku"       for a in caution_areas):
            reasons.append("東京23区で{}以上を観測".format(_intensity_to_label(threshold_caution_tokyo_23ku)))
        if any(a["trigger"] == "nationwide" for a in caution_areas):
            reasons.append("全国で{}以上を観測".format(_intensity_to_label(threshold_caution_nationwide)))
        return CheckResult(
            should_notify=True, level="caution",
            reason=" / ".join(reasons),
        )

    return CheckResult(
        should_notify=False, level="none",
        reason="閾値以下のため通知不要",
    )

_LEVEL_LABEL = {"alert": "至急報告", "caution": "注意喚起"}

def build_quake_message(
    detail: QuakeDetail,
    result: CheckResult,
    is_escalation: bool = False,
    previous_level: str = "",
    version: str = "",
    info_link_title: str = "",
    info_link_url: str = "",
    show_intensity_areas: bool = True,
    footer_note: str = "",
) -> str:
    if result.level == "alert":
        action = "至急報告してください！（閾値：23区5強、全国6弱）"
    else:
        action = "閾値（23区5強、全国6弱）に満たないため、報告不要です。"

    if detail.origin_time and detail.origin_time != "不明":
        time_str = _format_time(detail.origin_time)
    elif detail.report_time:
        time_str = detail.report_time.split("T")[1][:5]
    else:
        time_str = "不明"

    lines = [action]
    if is_escalation:
        prev_label = _LEVEL_LABEL.get(previous_level, previous_level)
        new_label  = _LEVEL_LABEL.get(result.level, result.level)
        lines.append(f"⚠️ 震度情報が更新されました（{prev_label}→{new_label}）")
    lines += [
        "",
        detail.headline_text,
        "▼地震情報",
        f"発生時刻: {time_str}　最大震度: {_intensity_to_label(detail.max_intensity)}",
        f"震源地: {detail.hypocenter or '調査中'}　規模: M{detail.magnitude or '調査中'}",
    ]

    if show_intensity_areas and detail.intensity_by_area:
        lines.append("")
        lines.append("震度別エリア（細分区域）:")
        for key in sorted(detail.intensity_by_area, key=lambda k: INTENSITY_ORDER.get(k, 0), reverse=True):
            areas = "、".join(detail.intensity_by_area[key])
            lines.append(f"{_intensity_to_label(key)}: {areas}")

    # if detail.intensity_by_city:
    #     lines.append("")
    #     lines.append("市町村レベルの最大震度:")
    #     for key in sorted(detail.intensity_by_city, key=lambda k: INTENSITY_ORDER.get(k, 0), reverse=True):
    #         cities = "、".join(detail.intensity_by_city[key])
    #         lines.append(f"{_intensity_to_label(key)}: {cities}")

    lines.append("")
    lines.append(f"津波: {detail.tsunami}")
    if info_link_url:
        lines.append("")
        lines.append(f"🔗 {info_link_title}: {info_link_url}")
    if footer_note:
        lines.append(footer_note)
    lines.append("")
    lines.append(f"sent by earthquake-notify (m.sono) [{version}]")

    return "\n".join(lines)

def _intensity_to_label(intensity: str) -> str:
    mapping = {
        "1": "震度1", "2": "震度2", "3": "震度3", "4": "震度4",
        "5-": "震度5弱", "5+": "震度5強",
        "6-": "震度6弱", "6+": "震度6強", "7": "震度7",
    }
    return mapping.get(intensity.strip(), f"震度{intensity}")

def _format_time(iso_time: str) -> str:
    try:
        return iso_time.split("T")[1][:5]
    except (IndexError, AttributeError):
        return iso_time
