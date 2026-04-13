# scraper/http_search.py
import asyncio
import aiohttp
import random
import math
import structlog
import json
import re
from urllib.parse import quote

log = structlog.get_logger()

# User Agents for realistic header construction
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

def _build_api_url(keyword, lat, lng, radius_meters, location=None):
    """Constructs the long internal Google Maps JSON API URL."""
    # Build a more robust query — for state_country we need the location name in q
    query_str = f"{keyword} in {location}" if location else keyword
    q = quote(query_str)
    
    # Try to extract a regional GL from location (basic heuristic)
    gl = 'us'
    loc_lower = location.lower() if location else ''
    if 'india' in loc_lower or 'in' == loc_lower.split()[-1]: gl = 'in'
    elif 'uk' in loc_lower or 'united kingdom' in loc_lower: gl = 'uk'
    elif 'uae' in loc_lower or 'emirates' in loc_lower: gl = 'ae'
    elif 'germany' in loc_lower: gl = 'de'
    
    r_int = int(radius_meters)
    # pb parameter contains the coordinate/zoom/offset logic
    pb = f"!4m8!1m3!1d{r_int}!2d{lng}!3d{lat}!3m2!1i1280!2i720!4f13.1!7i20!8i0!10b1!12m26!1m5!18b1!30b1!31m1!1b1!34e1!2m4!5m1!6e2!20e3!39b1!10b1!12b1!13b1!16b1!17m1!3e1!20m4!5e2!6b1!8b1!14b1!46m1!1b0!96b1!99b1!19m4!2m3!1i360!2i120!4i8"
    return f"https://www.google.com/search?tbm=map&authuser=0&hl=en&gl={gl}&q={q}&pb={pb}&tch=1&ech=1"

def _parse_json_response(raw_text: str) -> list:
    """
    Robustly extracts business data from Google Maps JSON responses.
    Uses recursive searching to find business-like objects in any structure.
    """
    places = []
    
    def find_json_objects(text):
        decoder = json.JSONDecoder()
        pos = 0
        while pos < len(text):
            try:
                match = re.search(r'[\{\[]', text[pos:])
                if not match: break
                pos += match.start()
                obj, pos = decoder.raw_decode(text, pos)
                yield obj
            except json.JSONDecodeError:
                pos += 1

    def is_business_obj(item):
        """Check if a list item looks like a Google Maps business record."""
        if not isinstance(item, list):
            return False
        # Check for a list representing the business. 
        # Typically index 1 contains the name, and index 14 contains the address.
        if len(item) > 1 and isinstance(item[1], str) and len(item) > 14:
            # Further verification: Rating usually at index 2, nested
            if isinstance(item[2], list) and len(item[2]) > 7:
                 return True
        return False


    def recursive_find_businesses(obj):
        """Recursively traverses the JSON structure to find business objects."""
        found = []
        if is_business_obj(obj):
            found.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                found.extend(recursive_find_businesses(item))
        elif isinstance(obj, dict):
            for value in obj.values():
                found.extend(recursive_find_businesses(value))
        return found

    try:
        data_objs = list(find_json_objects(raw_text))
        print(f"DEBUG: Found {len(data_objs)} JSON objects in response")
        
        for data in data_objs:
            # Google often wraps the payload in a 'd' field
            d_val = data.get('d') if isinstance(data, dict) else data
            if not d_val: 
                continue
            
            try:
                if isinstance(d_val, str):
                    if d_val.startswith(")]}'"):
                        d_val = d_val[4:].strip()
                    d_parsed = json.loads(d_val)
                else:
                    d_parsed = d_val
            except Exception as je: 
                print(f"DEBUG: JSON decode error for 'd': {je}")
                continue

            # Deep search through the parsed JSON for anything that looks like a business record
            business_records = recursive_find_businesses(d_parsed)
            print(f"DEBUG: Found {len(business_records)} potential business records in this chunk")
            
            for r in business_records:
                try:
                    # New mapping based on latest Google Maps JSON API structure
                    name = r[1]
                    if not name: continue 
                    
                    # place_id fallback: use index 10 if present
                    p_id = r[10] if (len(r) > 10 and r[10]) else name
                    
                    places.append({
                        'place_id': p_id,
                        'name': name,
                        'category': r[13][0] if (len(r) > 13 and r[13]) else "",
                        'street': r[14] if (len(r) > 14 and isinstance(r[14], str)) else "",
                        'phone': (r[178][0][0] if (len(r) > 178 and r[178] and r[178][0]) else "") if len(r) > 178 else "",
                        'website': r[7][0] if (len(r) > 7 and r[7] and isinstance(r[7], list) and r[7][0]) else "",
                        'rating': r[2][6] if (len(r) > 2 and r[2] and len(r[2]) > 6) else "",
                        'review_count': r[2][7] if (len(r) > 2 and r[2] and len(r[2]) > 7) else "",
                        'latitude': r[9][2] if (len(r) > 9 and r[9] and len(r[9]) > 2) else None,
                        'longitude': r[9][3] if (len(r) > 9 and r[9] and len(r[9]) > 3) else None,
                        'maps_url': f"https://www.google.com/maps/place/?q=place_id:{p_id}" if p_id else ""
                    })
                except Exception as pe:
                    print(f"DEBUG: Error parsing record: {pe}")

    except Exception as e:
        log.error('http_search.parse_error', error=str(e))
        
    return places

async def http_search_cell(session: aiohttp.ClientSession, cell, keyword: str, grid_size: int = 8, manual_cookies: str = None) -> list:

    """
    Direct HTTP Search using Manual Cookies.
    Zero Playwright overhead. Instant Execution.
    """
    # Build URL based on cell center
    lat_dist = abs(cell.max_lat - cell.min_lat) * 111000
    lng_dist = abs(cell.max_lng - cell.min_lng) * 111111 * math.cos(math.radians(cell.center_lat))
    radius_meters = int(math.sqrt(lat_dist**2 + lng_dist**2) * 2.2)
    radius_meters = max(radius_meters, 1500)
    
    base_url = _build_api_url(keyword, cell.center_lat, cell.center_lng, radius_meters, location=cell.display_name)
    
    all_places = []
    offsets = [0, 20, 40, 60, 80, 100, 120, 140, 160, 180] # 10 pages = 200 leads/cell.
    
    headers = {
        "User-Agent": USER_AGENTS[0],
        "Accept": "*/*",
        "Referer": "https://www.google.com/maps",
        "Cookie": manual_cookies,
        "X-Requested-With": "XMLHttpRequest"
    }

    for offset in offsets:
        url = base_url.replace('!8i0', f'!8i{offset}')
        try:
            async with session.get(url, headers=headers, timeout=20) as resp:
                if resp.status == 200:
                    raw = await resp.text()
                    page_places = _parse_json_response(raw)
                    if not page_places: 
                        break # End of results for this cell
                    all_places.extend(page_places)
                    log.info("search.page_success", offset=offset, found=len(page_places))
                elif resp.status == 429:
                    log.error("search.rate_limited", offset=offset)
                    return all_places, True # Signal rate limit
        except Exception as e:
            log.debug("search.error", error=str(e))
            break
            
        await asyncio.sleep(random.uniform(0.3, 0.7)) # Slightly more conservative

    return all_places, False


