"""
CBR (Bank of Russia) key rate client.

SOAP endpoint DailyInfoWebServ/KeyRate, XML parsed with lxml.
Results are cached for 7 days via the existing file CacheManager, and the
last successful response is additionally stored without practical TTL as a
fallback for when cbr.ru is unreachable.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import aiohttp
from lxml import etree

from cache import CacheManager

logger = logging.getLogger("cbr")

SOAP_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
SOAP_BODY = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRate xmlns="http://web.cbr.ru/">
      <fromDate>{from_date}</fromDate>
      <ToDate>{to_date}</ToDate>
    </KeyRate>
  </soap:Body>
</soap:Envelope>"""

CACHE_KEY = "cbr://keyrate"
FALLBACK_KEY = "cbr://keyrate/last_known"
# Last resort when neither cbr.ru nor cache are available (14.25% on 2026-06)
STATIC_FALLBACK = [{"date": "2026-06-05", "rate": 14.25}]


async def fetch_key_rate_history(months: int = 4,
                                 cache: Optional[CacheManager] = None) -> List[Dict]:
    """Returns [{'date': 'YYYY-MM-DD', 'rate': float}, ...] ascending, ~N months back"""
    cache = cache or CacheManager()

    cached = cache.get(CACHE_KEY, ttl_hours=7 * 24)
    if cached:
        return cached

    to_date = datetime.now()
    from_date = to_date - timedelta(days=months * 31)
    body = SOAP_BODY.format(
        from_date=from_date.strftime("%Y-%m-%d"),
        to_date=to_date.strftime("%Y-%m-%d"),
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                SOAP_URL,
                data=body.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "http://web.cbr.ru/KeyRate",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"CBR HTTP {response.status}")
                xml = await response.read()

        tree = etree.fromstring(xml)
        rows = []
        for kr in tree.iter("KR"):
            dt = kr.findtext("DT")
            rate = kr.findtext("Rate")
            if dt and rate:
                rows.append({"date": dt[:10], "rate": float(rate)})
        rows.sort(key=lambda r: r["date"])
        if not rows:
            raise RuntimeError("CBR returned no KeyRate rows")

        cache.set(CACHE_KEY, rows)
        cache.set(FALLBACK_KEY, rows)
        return rows
    except Exception as e:
        logger.error(f"CBR key rate fetch failed: {e}")
        last_known = cache.get(FALLBACK_KEY, ttl_hours=24 * 365 * 10)
        if last_known:
            logger.warning("Using last known CBR key rate from cache")
            return last_known
        logger.warning("Using static CBR key rate fallback")
        return STATIC_FALLBACK


def rate_now_and_3m_ago(history: List[Dict]) -> tuple:
    """(current_rate, rate_3_months_ago) from ascending history"""
    if not history:
        return None, None
    current = history[-1]["rate"]
    target = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    past = history[0]["rate"]
    for row in history:
        if row["date"] <= target:
            past = row["rate"]
        else:
            break
    return current, past
