import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/eqvol_l.xml"
REQUEST_TIMEOUT = 10

NS = {
    "atom":    "http://www.w3.org/2005/Atom",
    "jmx":     "http://xml.kishou.go.jp/jmaxml1/",
    "jmx_ib1": "http://xml.kishou.go.jp/jmaxml1/informationBasis1/",
    "eb":      "http://xml.kishou.go.jp/jmaxml1/body/seismology1/",
    "jmx_eb":  "http://xml.kishou.go.jp/jmaxml1/elementBasis1/",
}

TARGET_TITLES = {"震源・震度に関する情報"}

_HEADLINE_INTENSITY_MAP = {
    "震度１": "1", "震度２": "2", "震度３": "3", "震度４": "4",
    "震度５弱": "5-", "震度５強": "5+",
    "震度６弱": "6-", "震度６強": "6+", "震度７": "7",
}

@dataclass
class QuakeEntry:
    event_id: str
    title: str
    updated: str
    xml_url: str

@dataclass
class QuakeDetail:
    event_id: str       # 気象庁公式EventID（jmx_ib1:EventID）。同一地震の複数Serial間で共通
    title: str
    origin_time: str
    max_intensity: str
    tsunami: str
    hypocenter: Optional[str] = None
    magnitude: Optional[str] = None
    report_time: str = ""
    area_intensities: list = field(default_factory=list)
    headline_text: str = ""
    intensity_by_area: dict = field(default_factory=dict)
    intensity_by_city: dict = field(default_factory=dict)

def fetch_feed() -> list[QuakeEntry]:
    try:
        resp = requests.get(FEED_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"フィード取得失敗: {e}")
        raise

    root = ET.fromstring(resp.content)
    entries = []

    for entry in root.findall("atom:entry", NS):
        title_el   = entry.find("atom:title", NS)
        id_el      = entry.find("atom:id", NS)
        updated_el = entry.find("atom:updated", NS)
        link_el    = entry.find("atom:link", NS)

        if None in (title_el, id_el, updated_el, link_el):
            continue

        title = title_el.text or ""
        if title not in TARGET_TITLES:
            continue

        entries.append(QuakeEntry(
            event_id = id_el.text or "",
            title    = title,
            updated  = updated_el.text or "",
            xml_url  = link_el.get("href", ""),
        ))

    entries = _deduplicate_entries(entries)
    logger.info(f"フィード取得完了: 対象エントリ {len(entries)} 件（重複排除後）")
    return entries


def _parse_dt(updated: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except Exception:
        return None


def _deduplicate_entries(entries: list) -> list:
    """同一titleのエントリのうち、発表時刻が3分以内のものを同一グループとみなし最新1件に絞る。"""
    WINDOW_SECONDS = 180  # 3分

    by_title: dict[str, list] = {}
    for e in entries:
        by_title.setdefault(e.title, []).append(e)

    result = []
    for title_entries in by_title.values():
        sorted_entries = sorted(title_entries, key=lambda e: e.updated)

        clusters: list[list] = []
        current: list = [sorted_entries[0]]

        for entry in sorted_entries[1:]:
            prev_dt = _parse_dt(current[-1].updated)
            this_dt = _parse_dt(entry.updated)
            if prev_dt and this_dt and (this_dt - prev_dt).total_seconds() <= WINDOW_SECONDS:
                current.append(entry)
            else:
                clusters.append(current)
                current = [entry]
        clusters.append(current)

        for cluster in clusters:
            result.append(max(cluster, key=lambda e: e.updated))

    return result

def fetch_quake_detail(entry: QuakeEntry) -> Optional[QuakeDetail]:
    try:
        resp = requests.get(entry.xml_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"個別XML取得失敗: {e}")
        return None

    try:
        return _parse_quake_xml(entry.event_id, entry.title, resp.content)
    except Exception as e:
        logger.error(f"XMLパース失敗: {e}")
        return None

def _parse_quake_xml(event_id, title, xml_bytes):
    root = ET.fromstring(xml_bytes)
    jma_event_id  = _find_text(root, ".//jmx_ib1:Head/jmx_ib1:EventID") or event_id
    report_time   = _find_text(root, ".//jmx_ib1:Head/jmx_ib1:ReportDateTime") or ""
    origin_time   = _find_text(root, ".//eb:Earthquake/eb:OriginTime") or "不明"
    tsunami_raw   = _find_text(root, ".//eb:Tsunami") or ""
    tsunami       = _normalize_tsunami(tsunami_raw)
    max_intensity = _find_text(root, ".//eb:Intensity/eb:Observation/eb:MaxInt") or "不明"
    hypocenter    = _find_text(root, ".//eb:Earthquake/eb:Hypocenter/eb:Area/eb:Name")
    magnitude     = _find_text(root, ".//eb:Earthquake/jmx_eb:Magnitude")

    area_intensities = []
    for pref_el in root.findall(".//eb:Intensity/eb:Observation/eb:Pref", NS):
        pref_name = _find_text(pref_el, "eb:Name") or ""
        for area_el in pref_el.findall("eb:Area", NS):
            area_name = _find_text(area_el, "eb:Name") or ""
            intensity = _find_text(area_el, "eb:MaxInt") or ""
            if area_name and intensity:
                area_intensities.append({
                    "pref": pref_name, "area": area_name, "intensity": intensity,
                })

    headline_text    = _find_text(root, ".//jmx_ib1:Head/jmx_ib1:Headline/jmx_ib1:Text") or ""
    intensity_by_area: dict = {}
    intensity_by_city: dict = {}
    headline_el = root.find(".//jmx_ib1:Head/jmx_ib1:Headline", NS)
    if headline_el is not None:
        for info_el in headline_el.findall("jmx_ib1:Information", NS):
            info_type = info_el.get("type", "")
            if info_type == "震源・震度に関する情報（細分区域）":
                target = intensity_by_area
            elif info_type == "震源・震度に関する情報（市町村等）":
                target = intensity_by_city
            else:
                continue
            for item_el in info_el.findall("jmx_ib1:Item", NS):
                kind_el = item_el.find("jmx_ib1:Kind/jmx_ib1:Name", NS)
                if kind_el is None or not kind_el.text:
                    continue
                key = _HEADLINE_INTENSITY_MAP.get(kind_el.text.strip())
                if key is None or key in ("1", "2", "3"):
                    continue
                names = [
                    el.text.strip()
                    for el in item_el.findall("jmx_ib1:Areas/jmx_ib1:Area/jmx_ib1:Name", NS)
                    if el.text
                ]
                if names:
                    target[key] = names

    return QuakeDetail(
        event_id=jma_event_id,
        title=title,
        origin_time=origin_time,
        max_intensity=max_intensity,
        tsunami=tsunami,
        hypocenter=hypocenter,
        magnitude=magnitude,
        report_time=report_time,
        area_intensities=area_intensities,
        headline_text=headline_text,
        intensity_by_area=intensity_by_area,
        intensity_by_city=intensity_by_city,
    )

def _find_text(element, path):
    el = element.find(path, NS)
    return el.text.strip() if el is not None and el.text else None

def _normalize_tsunami(raw):
    mapping = {
        "なし": "なし",
        "調査中": "調査中",
        "津波注意報": "⚠️津波注意報",
        "津波警報": "🚨津波警報",
        "大津波警報": "🚨大津波警報",
    }
    for key, val in mapping.items():
        if key in raw:
            return val
    return raw if raw else "なし"


# ---------------------------------------------------------------------------
# 気象警報・注意報 / 特別警報
# ---------------------------------------------------------------------------
# eqvol_l.xml は地震・火山専用のため、気象警報は別フィードから取得する
WEATHER_FEED_URLS = [
    "https://www.data.jma.go.jp/developer/xml/feed/extra.xml",    # 随時配信（VPTW50 等）
    "https://www.data.jma.go.jp/developer/xml/feed/regular.xml",  # 定時配信（VPWW53 等）
]
WEATHER_TARGET_CODES = {"VPWW53", "VPTW50"}

# 気象 XML パース用名前空間（atom は NS と共通）
WNS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "jmx":    "http://xml.kishou.go.jp/jmaxml1/",
    "jmx_ib": "http://xml.kishou.go.jp/jmaxml1/informationBasis/",
    "mete":   "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/",
}


@dataclass
class WeatherEntry:
    event_id: str
    title: str
    updated: str
    xml_url: str
    code: str   # "VPWW53" or "VPTW50"


@dataclass
class WeatherDetail:
    event_id:   str
    info_type:  str       # 発表 / 更新 / 訂正 / 取消
    info_kind:  str       # 気象警報・注意報 / 特別警報
    headline:   str       # ヘッドライン本文
    issued_at:  str       # 発表時刻（ISO）
    areas:      list      # [{"name": "...", "warnings": [...], "cancelled": [...]}]
    is_special: bool      # True = VPTW50（特別警報）


def fetch_weather_feed() -> list[WeatherEntry]:
    entries: list[WeatherEntry] = []
    seen: set[str] = set()

    for feed_url in WEATHER_FEED_URLS:
        try:
            resp = requests.get(feed_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for entry_el in root.findall("atom:entry", WNS):
                link_el = entry_el.find("atom:link", WNS)
                if link_el is None:
                    continue
                xml_url = link_el.get("href", "")
                code = next((c for c in WEATHER_TARGET_CODES if c in xml_url), None)
                if not code:
                    continue
                id_el      = entry_el.find("atom:id", WNS)
                title_el   = entry_el.find("atom:title", WNS)
                updated_el = entry_el.find("atom:updated", WNS)
                if None in (id_el, title_el, updated_el):
                    continue
                event_id = id_el.text or ""
                if event_id in seen:
                    continue
                seen.add(event_id)
                entries.append(WeatherEntry(
                    event_id = event_id,
                    title    = title_el.text or "",
                    updated  = updated_el.text or "",
                    xml_url  = xml_url,
                    code     = code,
                ))
        except Exception as e:
            logger.error(f"気象警報フィード取得失敗 ({feed_url}): {e}")

    logger.info(f"気象警報フィード取得完了: {len(entries)} 件")
    return entries


def fetch_weather_detail(entry: WeatherEntry) -> Optional[WeatherDetail]:
    try:
        resp = requests.get(entry.xml_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"気象警報XML取得失敗: {e}")
        return None

    try:
        return _parse_weather_xml(entry.event_id, entry.code, resp.content)
    except Exception as e:
        logger.error(f"気象警報XMLパース失敗: {e}")
        return None


def _parse_weather_xml(event_id: str, code: str, xml_bytes: bytes) -> Optional[WeatherDetail]:
    root = ET.fromstring(xml_bytes)

    # 訓練・試験はスキップ
    ctrl_status = _wfind_text(root, ".//jmx:Control/jmx:Status")
    if ctrl_status in ("訓練", "試験"):
        return None

    info_type = _wfind_text(root, ".//jmx_ib:InfoType") or ""
    info_kind = _wfind_text(root, ".//jmx_ib:InfoKind") or "気象警報・注意報"
    headline  = _wfind_text(root, ".//jmx_ib:Headline/jmx_ib:Text") or ""
    issued_at = _wfind_text(root, ".//jmx_ib:ReportDateTime") or ""

    areas: list[dict] = []
    for item_el in root.findall(".//mete:Warning/mete:Item", WNS):
        area_name = _wfind_text(item_el, "mete:Area/mete:Name")
        if not area_name:
            continue
        active: list[str]    = []
        cancelled: list[str] = []
        for kind_el in item_el.findall("mete:Kind", WNS):
            w_type   = _wfind_text(kind_el, "mete:Property/mete:Type")
            w_detail = _wfind_text(kind_el, "mete:Property/mete:Detail")
            status_k = _wfind_text(kind_el, "mete:Status")
            if not w_type:
                continue
            label = f"{w_type}（{w_detail}）" if w_detail else w_type
            if status_k == "解除":
                cancelled.append(label)
            else:
                active.append(label)
        if active or cancelled:
            areas.append({"name": area_name, "warnings": active, "cancelled": cancelled})

    return WeatherDetail(
        event_id   = event_id,
        info_type  = info_type,
        info_kind  = info_kind,
        headline   = headline,
        issued_at  = issued_at,
        areas      = areas,
        is_special = (code == "VPTW50"),
    )


def _wfind_text(element, path) -> Optional[str]:
    el = element.find(path, WNS)
    return el.text.strip() if el is not None and el.text else None