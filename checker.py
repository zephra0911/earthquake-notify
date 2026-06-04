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

THRESHOLD_TOKYO_23KU = "5+"
THRESHOLD_NATIONWIDE = "6-"

@dataclass
class CheckResult:
    should_notify: bool
    reason: str
    triggered_areas: list

def _intensity_value(intensity: str) -> int:
    return INTENSITY_ORDER.get(intensity.strip(), 0)

def _is_gte(intensity: str, threshold: str) -> bool:
    return _intensity_value(intensity) >= _intensity_value(threshold)

def check_notify(detail: QuakeDetail) -> CheckResult:
    triggered_areas = []

    for item in detail.area_intensities:
        area      = item.get("area", "")
        pref      = item.get("pref", "")
        intensity = item.get("intensity", "")

        if area in TOKYO_23KU and _is_gte(intensity, THRESHOLD_TOKYO_23KU):
            triggered_areas.append({
                "pref": pref, "area": area,
                "intensity": intensity, "trigger": "23ku",
            })
        elif _is_gte(intensity, THRESHOLD_NATIONWIDE):
            triggered_areas.append({
                "pref": pref, "area": area,
                "intensity": intensity, "trigger": "nationwide",
            })

    if not triggered_areas:
        return CheckResult(should_notify=False, reason="閾値以下のため通知不要", triggered_areas=[])

    reasons = []
    if any(a["trigger"] == "23ku"       for a in triggered_areas):
        reasons.append("東京23区で震度5強以上を観測")
    if any(a["trigger"] == "nationwide" for a in triggered_areas):
        reasons.append("全国で震度6弱以上を観測")

    return CheckResult(should_notify=True, reason=" / ".join(reasons), triggered_areas=triggered_areas)

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
    lines += ["", "※詳細は続報でお知らせします", "⚠️ PMH稼働確認を準備してください"]
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
            lines.appen