from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import requests

from config import Config

logger = logging.getLogger("CareRoute.GeoService")

# ==============================================================================
# Curated Verified Directory of Community Health Centers (Rajasthan / Alwar District)
# Reliable offline fallback conforming to official MoHFW / NHM Rajasthan registry.
# ==============================================================================
VERIFIED_CHC_DIRECTORY: list[dict[str, Any]] = [
    {
        "id": "chc_alwar_main",
        "name": "सामुदायिक स्वास्थ्य केंद्र एवं सामान्य चिकित्सालय, अलवर (Alwar CHC & District Hospital)",
        "facility_type": "Community Health Center / District Hospital",
        "latitude": 27.5530,
        "longitude": 76.6346,
        "address": "Company Bagh Road, Alwar, Rajasthan 301001",
        "phone": "+91-144-2332211",
        "emergency_helpline": "108",
        "is_emergency_24x7": True,
        "opd_timings": "09:00 AM - 01:00 PM, 04:00 PM - 06:00 PM",
        "specialties": [
            "छाती एवं फेफड़ा रोग (Pulmonology)",
            "त्वचा एवं चर्म रोग (Dermatology)",
            "सामान्य चिकित्सा (General Medicine)",
            "प्रसूति एवं स्त्री रोग (Obstetrics)",
            "शिशु रोग (Pediatrics)",
        ],
    },
    {
        "id": "chc_behror",
        "name": "सामुदायिक स्वास्थ्य केंद्र, बहरोड़ (Behror CHC)",
        "facility_type": "Community Health Center",
        "latitude": 27.8872,
        "longitude": 76.2806,
        "address": "NH-48, Near Bus Stand, Behror, Alwar District, Rajasthan 301701",
        "phone": "+91-1494-220015",
        "emergency_helpline": "108",
        "is_emergency_24x7": True,
        "opd_timings": "09:00 AM - 01:00 PM",
        "specialties": [
            "सामान्य चिकित्सा (General Medicine)",
            "आपातकालीन सेवा (Trauma Care)",
            "शिशु रोग (Pediatrics)",
        ],
    },
    {
        "id": "chc_tijara",
        "name": "सामुदायिक स्वास्थ्य केंद्र, तिजारा (Tijara CHC)",
        "facility_type": "Community Health Center",
        "latitude": 27.9332,
        "longitude": 76.8524,
        "address": "Rewari-Alwar Road, Tijara, Alwar District, Rajasthan 301411",
        "phone": "+91-1469-222045",
        "emergency_helpline": "108",
        "is_emergency_24x7": True,
        "opd_timings": "09:00 AM - 01:00 PM",
        "specialties": [
            "सामान्य चिकित्सा (General Medicine)",
            "श्वसन तंत्र एवं टीबी नियंत्रण (RNTCP / Chest)",
            "मातृ एवं शिशु स्वास्थ्य (MCH)",
        ],
    },
    {
        "id": "chc_kishangarh_bas",
        "name": "सामुदायिक स्वास्थ्य केंद्र, किशनगढ़ बास (Kishangarh Bas CHC)",
        "facility_type": "Community Health Center",
        "latitude": 27.8183,
        "longitude": 76.7214,
        "address": "Main Market Road, Kishangarh Bas, Rajasthan 301405",
        "phone": "+91-1460-234012",
        "emergency_helpline": "108",
        "is_emergency_24x7": True,
        "opd_timings": "09:00 AM - 01:00 PM",
        "specialties": [
            "प्राथमिक स्वास्थ्य एवं ओपीडी (Primary OPD)",
            "नैदानिक प्रयोगशाला (Diagnostic Lab)",
            "सामान्य चिकित्सा (General Medicine)",
        ],
    },
    {
        "id": "chc_rajgarh",
        "name": "उप जिला अस्पताल एवं सीएचसी, राजगढ़ (Rajgarh Sub-District CHC)",
        "facility_type": "Sub-District Hospital / CHC",
        "latitude": 27.2346,
        "longitude": 76.6213,
        "address": "Station Road, Rajgarh, Alwar District, Rajasthan 301408",
        "phone": "+91-1464-220023",
        "emergency_helpline": "108",
        "is_emergency_24x7": True,
        "opd_timings": "09:00 AM - 01:00 PM, 04:00 PM - 06:00 PM",
        "specialties": [
            "छाती एवं सांस रोग (Chest Clinic)",
            "आपातकालीन वार्ड (Emergency 24x7)",
            "सामान्य ओपीडी (General OPD)",
        ],
    },
]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth (km)."""
    R = 6371.0  # Earth's radius in kilometers
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 2)


class GeoService:
    """
    Real-Data Geospatial Service providing nearest Community Health Center (CHC)
    and emergency hospital lookups using OpenStreetMap / Overpass API with
    local caching and verified offline fallback.
    """

    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    def __init__(
        self,
        cache_dir: Path | None = None,
        cache_ttl_hours: int = 24,
        request_timeout: float = 3.5,
    ) -> None:
        self.cache_dir = cache_dir or (Config.DATA_STORAGE_DIR / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "osm_geo_cache.json"
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        self.request_timeout = request_timeout

    def _load_cache(self) -> dict[str, Any]:
        """Load persistent cache of previous Overpass API queries."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read geo cache: {e}")
        return {}

    def _save_cache(self, cache_data: dict[str, Any]) -> None:
        """Save query result to local disk cache."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write geo cache: {e}")

    def query_overpass_chcs(
        self,
        lat: float,
        lon: float,
        radius_km: float = 30.0,
    ) -> list[dict[str, Any]] | None:
        """
        Execute live Overpass API query for hospitals, clinics, and health centres.
        Returns None if request fails or times out.
        """
        radius_meters = int(radius_km * 1000)
        query = f"""
        [out:json][timeout:5];
        (
          node["amenity"="hospital"](around:{radius_meters},{lat},{lon});
          node["amenity"="clinic"](around:{radius_meters},{lat},{lon});
          node["healthcare"="centre"](around:{radius_meters},{lat},{lon});
        );
        out body;
        """
        headers = {"User-Agent": "CareRoute-Telehealth-Bridge/0.2.0 (Fetch-a-thon 3.0)"}
        try:
            resp = requests.post(
                self.OVERPASS_URL,
                data={"data": query},
                headers=headers,
                timeout=self.request_timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])
                results = []
                for elem in elements:
                    tags = elem.get("tags", {})
                    name = tags.get("name") or tags.get("name:en") or tags.get("name:hi")
                    if not name:
                        continue
                    node_lat = elem.get("lat")
                    node_lon = elem.get("lon")
                    dist = haversine_distance_km(lat, lon, node_lat, node_lon)
                    results.append(
                        {
                            "id": f"osm_node_{elem.get('id')}",
                            "name": name,
                            "facility_type": tags.get("amenity") or tags.get("healthcare") or "Hospital",
                            "latitude": node_lat,
                            "longitude": node_lon,
                            "distance_km": dist,
                            "address": tags.get("addr:street") or tags.get("addr:city") or "Alwar, Rajasthan",
                            "phone": tags.get("phone") or tags.get("contact:phone") or "108",
                            "emergency_helpline": "108",
                            "is_emergency_24x7": tags.get("emergency") == "yes",
                            "opd_timings": tags.get("opening_hours") or "09:00 AM - 01:00 PM",
                            "specialties": ["General Healthcare", "Emergency"],
                            "source": "osm_overpass_live",
                        }
                    )
                if results:
                    results.sort(key=lambda x: x["distance_km"])
                    return results
        except Exception as exc:
            logger.warning(f"Overpass live query failed ({type(exc).__name__}): {exc}")

        return None

    def find_nearest_chc(
        self,
        latitude: float = 27.5530,
        longitude: float = 76.6346,
        radius_km: float = 35.0,
        max_results: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Locate the nearest verified Community Health Centers (CHCs) to the patient.
        Layered resolution:
          1. Check local query cache (returns if fresh).
          2. Query live OpenStreetMap Overpass API.
          3. Fallback to verified Alwar district CHC directory with calculated distance.
        """
        cache_key = f"{round(latitude, 3)}_{round(longitude, 3)}_{int(radius_km)}"
        cache = self._load_cache()

        now = time.time()
        # 1. Check cache freshness
        if cache_key in cache:
            entry = cache[cache_key]
            if now - entry.get("timestamp", 0) < self.cache_ttl_seconds:
                results = entry.get("data", [])
                for r in results:
                    r["source"] = "osm_overpass_cached"
                return results[:max_results]

        # 2. Try live Overpass API
        live_results = self.query_overpass_chcs(latitude, longitude, radius_km)
        if live_results:
            cache[cache_key] = {"timestamp": now, "data": live_results}
            self._save_cache(cache)
            return live_results[:max_results]

        # 3. Offline Verified Fallback
        fallback_results = []
        for facility in VERIFIED_CHC_DIRECTORY:
            fac_copy = dict(facility)
            dist = haversine_distance_km(latitude, longitude, fac_copy["latitude"], fac_copy["longitude"])
            fac_copy["distance_km"] = dist
            fac_copy["source"] = "verified_offline_directory"
            fallback_results.append(fac_copy)

        fallback_results.sort(key=lambda x: x["distance_km"])
        return fallback_results[:max_results]

    def format_chc_recommendation_hindi(self, facility: dict[str, Any]) -> str:
        """Render a patient-friendly Hindi notification card for the nearest CHC."""
        name = facility.get("name", "सामुदायिक स्वास्थ्य केंद्र (CHC)")
        dist = facility.get("distance_km", 0.0)
        addr = facility.get("address", "")
        phone = facility.get("phone", "108")
        opd = facility.get("opd_timings", "09:00 AM - 01:00 PM")
        specialties = ", ".join(facility.get("specialties", [])[:3])

        return (
            f"🏥 **निकटतम स्वास्थ्य केंद्र:** {name}\n"
            f"📍 **दूरी:** लगभग {dist} किमी | {addr}\n"
            f"🕒 **ओपीडी समय:** {opd}\n"
            f"🩺 **विशेषज्ञ सेवाएं:** {specialties}\n"
            f"📞 **हेल्पलाइन / फोन:** {phone} (आपातकाल: 108)"
        )
