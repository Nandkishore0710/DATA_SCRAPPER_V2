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
    
    # 🎯 IMPROVED STRATEGY: Explicitly look for administrative/settlement boundaries
    # We add 'city' or 'town' hints to the variants to avoid restaurants/shops
    variants = [location, f"{location} city", f"{location} town", f"{location} region"]
    best_result = None
    
    async with httpx.AsyncClient(timeout=10) as client:
        for q in variants:
            try:
                # Use 'featuretype=settlement' to filter out restaurants/shops
                params = {
                    'q': q, 
                    'format': 'json', 
                    'limit': 3, 
                    'addressdetails': 1,
                    'featuretype': 'settlement' 
                }
                response = await client.get(url, params=params, headers=headers)
                data = response.json()
                
                if not data:
                    # Fallback without featuretype if no settlement found
                    params.pop('featuretype')
                    response = await client.get(url, params=params, headers=headers)
                    data = response.json()

                for res in data:
                    # HEURISTIC: Skip if it's too small (representative points of businesses)
                    # A city/town usually has a significant bounding box
                    bbox = [float(x) for x in res['boundingbox']]
                    area = (bbox[1] - bbox[0]) * (bbox[3] - bbox[2])
                    
                    # If the area is suspiciously small (like a building), skip unless it's our only hope
                    if area < 0.0001 and len(data) > 1:
                        continue
                    
                    display_name = res.get('display_name', '').lower()
                    place_type = res.get('type', '').lower()
                    
                    # Rank results: City/Town/Administrative > Everything else
                    is_high_quality = any(x in place_type for x in ['city', 'town', 'administrative', 'postcode']) or \
                                      any(x in display_name for x in ['city', 'town', 'municipality'])

                    if not best_result or (is_high_quality and not best_result['is_high_quality']):
                        best_result = {
                            'min_lat': bbox[0],
                            'max_lat': bbox[1],
                            'min_lng': bbox[2],
                            'max_lng': bbox[3],
                            'display_name': res['display_name'],
                            'is_high_quality': is_high_quality,
                            'area': area
                        }
                        # If it's a high quality city match, we stop
                        if is_high_quality: break
                
                if best_result and best_result['is_high_quality']:
                    break

            except Exception as e:
                log.debug("boundary.variant_failed", query=q, error=str(e))
                continue

    if not best_result:
        raise Exception(f"Location not found: {location}. Please be more specific (e.g. 'City, Country')")

    # Calculate center and radius
    center_lat = (best_result['min_lat'] + best_result['max_lat']) / 2
    center_lng = (best_result['min_lng'] + best_result['max_lng']) / 2
    
    # Calculate radius based on the bounding box size
    lat_dist = abs(best_result['max_lat'] - best_result['min_lat']) * 111000
    lng_dist = abs(best_result['max_lng'] - best_result['min_lng']) * 111000 * math.cos(math.radians(center_lat))
    
    # Ensure a reasonable minimum search radius (5km) and maximum (25km)
    radius_meters = max(int(math.sqrt(lat_dist**2 + lng_dist**2) / 2 * 1.2), 5000)
    radius_meters = min(radius_meters, 25000)
    
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
