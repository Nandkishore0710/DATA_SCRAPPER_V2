# scraper/boundary.py
import httpx
import structlog
import math

log = structlog.get_logger()

async def get_city_boundary(location: str) -> dict:
    """
    Gets the most comprehensive bounding box for a location using async httpx.
    Checks Postgres LocationCache first, fallbacks to Nominatim.
    """
    from jobs.models import LocationCache
    
    # 1. CHECK CACHE
    cached = await LocationCache.objects.filter(query=location.lower()).afirst()
    if cached:
        log.info("boundary.cache_hit", location=location)
        return {
            'min_lat': cached.min_lat,
            'max_lat': cached.max_lat,
            'min_lng': cached.min_lng,
            'max_lng': cached.max_lng,
            'display_name': cached.display_name,
            'radius_meters': cached.radius_meters,
            'center_lat': cached.center_lat,
            'center_lng': cached.center_lng
        }

    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'ExtractorPlatform/1.0'}
    
    variants = [f"{location} city centre", location, f"{location} city", f"{location} district"]
    best_result = None
    min_area = float('inf')

    async with httpx.AsyncClient(timeout=10) as client:
        for q in variants:
            try:
                params = {'q': q, 'format': 'json', 'limit': 1}
                response = await client.get(url, params=params, headers=headers)
                data = response.json()
                
                if data:
                    res = data[0]
                    bbox = res['boundingbox']
                    display_name = res.get('display_name', '').lower()
                    
                    # Rough area calculation
                    area = (float(bbox[1]) - float(bbox[0])) * (float(bbox[3]) - float(bbox[2]))
                    if area == 0: area = 0.0001
                    
                    # HEURISTIC: Prioritize exact 'city' or 'town' matches first
                    is_city_match = any(x in display_name for x in ['city', 'town', 'municipality', 'centre'])
                    
                    if not best_result or (is_city_match and area < min_area) or (not is_city_match and area < min_area):
                        min_area = area
                        best_result = {
                            'min_lat': float(bbox[0]),
                            'max_lat': float(bbox[1]),
                            'min_lng': float(bbox[2]),
                            'max_lng': float(bbox[3]),
                            'display_name': res['display_name'],
                            'area': area
                        }
                        # If we found a high-quality city match, we can stop early
                        if is_city_match: break 
            except Exception:
                continue

    if not best_result:
        raise Exception(f"Location not found: {location}")

    # Calculate center and radius
    center_lat = (best_result['min_lat'] + best_result['max_lat']) / 2
    center_lng = (best_result['min_lng'] + best_result['max_lng']) / 2
    
    lat_dist = abs(best_result['max_lat'] - best_result['min_lat']) * 111000
    lng_dist = abs(best_result['max_lng'] - best_result['min_lng']) * 111000 * math.cos(math.radians(center_lat))
    radius_meters = max(int(math.sqrt(lat_dist**2 + lng_dist**2) / 2 * 1.2), 5000)
    
    # 2. SAVE TO CACHE
    await LocationCache.objects.acreate(
        query=location.lower(),
        display_name=best_result['display_name'],
        min_lat=best_result['min_lat'],
        max_lat=best_result['max_lat'],
        min_lng=best_result['min_lng'],
        max_lng=best_result['max_lng'],
        center_lat=center_lat,
        center_lng=center_lng,
        radius_meters=radius_meters
    )

    return {**best_result, 'center_lat': center_lat, 'center_lng': center_lng, 'radius_meters': radius_meters}
