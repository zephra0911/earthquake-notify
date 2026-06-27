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
    triggered_areas: list

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
            reason=" / ".join(reasons), triggered_areas=alert_areas,
        )

    if caution_areas:
        reasons = []
        if any(a["trigger"] == "23ku"       for a in caution_areas):
            reasons.append("東京23区で{}以上を観測".format(_intensity_to_label(threshold_caution_tokyo_23ku)))
        if any(a["trigger"] == "nationwide" for a in caution_areas):
            reasons.append("全国で{}以上を観測".format(_intensity_to_label(threshold_caution_nationwide)))
        return CheckResult(
            should_notify=True, level="caution",
            reason=" / ".join(reasons), triggered_areas=caution_areas,
        )

    return CheckResult(
        should_notify=False, level="none",
        reason="閾値以下のため通知不要", triggered_areas=[],
    )

def build_alert_message(detail: QuakeDetail, result: CheckResult) -> str:
    lines = [
        "【地震速報】⚠️",
        f"発生時刻: {_format_time(detail.origin_time)}",
        f"最大震度: {_intensity_to_label(detail.max_intensity)}（速報値）",
        f"津波:     {detail.tsunami}",
        "",
        "▼ 閾値超過エリア",
    ]
    for item in result.triggered_areas:
        lines.append(f"  {item['pref']} {item['area']}: {_intensity_to_label(item['intensity'])}")
    lines += ["", "※詳細は続報でお知らせします", "⚠️ 対象システムの稼働確認を準備してください"]
    return "\n".join(lines)

def build_detail_message(detail: QuakeDetail, result: CheckResult) -> str:
    lines = [
        "【地震詳細・続報】",
        f"震源地:   {detail.hypocenter or '調査中'}",
        f"規模:     M{detail.magnitude or '調査中'}",
        f"発生時刻: {_format_time(detail.origin_time)}",
        f"最大震度: {_intensity_to_label(detail.max_intensity)}",
        f"津波:     {detail.tsunami}",
        "",
        "▼ 主な観測地域",
    ]
    sorted_areas = sorted(
        detail.area_intensities,
        key=lambda x: _intensity_value(x.get("intensity", "")),
        reverse=True,
    )[:10]

    current_pref = ""
    for item in sorted_areas:
        if item["pref"] != current_pref:
            lines.append(f"─ {item['pref']} ─")
            current_pref = item["pref"]
        lines.append(f"  {item['area']}: {_intensity_to_label(item['intensity'])}")

    lines += ["", f"【判定】{result.reason}", "⚠️ 対象システムの稼働確認を実施してください"]
    return "\n".join(lines)

def build_caution_message(detail: QuakeDetail, result: CheckResult) -> str:
    lines = [
        "【地震情報（注意）】",
        f"発生時刻: {_format_time(detail.origin_time)}",
        f"最大震度: {_intensity_to_label(detail.max_intensity)}",
        f"津波:     {detail.tsunami}",
        "",
        "▼ 観測エリア",
    ]
    for item in result.triggered_areas:
        lines.append(f"  {item['pref']} {item['area']}: {_intensity_to_label(item['intensity'])}")
    lines += [
        "",
        "揺れを感じた方はご注意ください。",
        "※ 対象システムの稼働確認の参考情報です",
    ]
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
