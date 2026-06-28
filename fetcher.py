import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
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

    logger.debug(f"フィード取得完了: 対象エントリ {len(entries)} 件")
    return entries


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
