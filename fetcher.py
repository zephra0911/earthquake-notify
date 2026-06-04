import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)

FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/eqvol.xml"
REQUEST_TIMEOUT = 10

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "jmx": "http://xml.kishou.go.jp/jmaxml1/",
    "eb":  "http://xml.kishou.go.jp/jmaxml1/body/seismology1/",
    "jmx_eb": "http://xml.kishou.go.jp/jmaxml1/elementBasis/",
}

TARGET_TITLES = {"震度速報", "震源・震度に関する情報"}

@dataclass
class QuakeEntry:
    event_id: str
    title: str
    updated: str
    xml_url: str

@dataclass
class QuakeDetail:
    event_id: str
    title: str
    origin_time: str
    max_intensity: str
    tsunami: str
    hypocenter: Optional[str] = None
    magnitude: Optional[str] = None
    area_intensities: list = field(default_factory=list)

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

    logger.info(f"フィード取得完了: 対象エントリ {len(entries)} 件")
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
    origin_time   = _find_text(root, ".//eb:Earthquake/eb:OriginTime") or "不明"
    tsunami_raw   = _find_text(root, ".//eb:Tsunami") or ""
    tsunami       = _normalize_tsunami(tsunami_raw)
    max_intensity = _find_text(root, ".//eb:Intensity/eb:Observation/eb:MaxInt") or "不明"
    hypocenter    = _find_text(root, ".//eb:Earthquake/eb:Hypocenter/eb:Area/eb:Name")
    magnitude     = _find_text(root, ".//eb:Earthquake/eb:jmx_eb:Magnitude")

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

    return QuakeDetail(