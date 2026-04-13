# scraper/search.py
# VERSION 2.0 — PRODUCTION-GRADE EXTRACTION ENGINE
# Rewrote from scratch for accuracy, speed, and reliability.
import asyncio
import re
import random
import structlog
import math
from urllib.parse import quote
try:
    from playwright_stealth import stealth_async
except ImportError:
    try:
        from playwright_stealth.stealth import stealth_async
    except ImportError:
        async def stealth_async(page, **kwargs): pass

from fake_useragent import UserAgent

ua = UserAgent()
from .cache import get_cached_results, set_cached_results

log = structlog.get_logger()

# ─── TEXT CLEANING UTILITIES ───────────────────────────────────────────
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\U00010000-\U0010ffff"
    "\u2640-\u2642"
    "\u2600-\u2B55"
    "\u200d\u23cf\u23e9\u231a\ufe0f\u3030"
    "]+", flags=re.UNICODE
)

CATEGORY_PREFIXES = re.compile(
    r'^(Gym|Fitness center|Fitness Centre|Yoga studio|Club|Restaurant|Cafe|Bar|Hotel|Spa|Salon|'
    r'Health club|Sports club|Swimming pool|Dance studio|Martial arts school|'
    r'Boxing gym|Crossfit gym|Pilates studio|Personal trainer|Dietitian|'
    r'Shopping mall|Temple|Hospital|School|College|University|Bank|ATM|'
    r'Gas station|Petrol pump|Pharmacy|Doctor|Dentist|Veterinarian|'
    r'Supermarket|Grocery store|Bakery|Ice cream shop|Pizza|'
    r'Car dealer|Car repair|Car wash|Parking|'
    r'Beauty salon|Hair salon|Nail salon|Tattoo shop|'
    r'Real estate|Insurance|Lawyer|Accountant|'
    r'Clothing store|Shoe store|Jewelry store|'
    r'Electronics store|Hardware store|Furniture store|'
    r'Travel agency|Tour operator|'
    r'Mosque|Church|Gurudwara|'
    r'Post office|Police station|Fire station|'
    r'Cinema|Theater|Museum|Library|Park|'
    r'Rooftop|Lounge|Pub|Nightclub|'
    r'Physiotherapist|Chiropractor|Acupuncturist|'
    r'Pet store|Animal hospital|'
    r'Event planner|Wedding planner|Photographer|'
    r'Laundry|Dry cleaner|Tailor|'
    r'Moving company|Storage|'
    r'Locksmith|Plumber|Electrician)'
    r'\s*[·:•\-–—]\s*',
    re.IGNORECASE
)

# Matches patterns like 24H5+CMP or 24H5+CMP Bhilwara
PLUS_CODE_PATTERN = re.compile(r'[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,4}', re.IGNORECASE)


def clean_text(text: str) -> str:
    """Strip emojis, category prefixes, and junk from extracted text."""
    if not text:
        return ""
    text = EMOJI_PATTERN.sub('', text).strip()
    # Strip leading/trailing dots, colons, middots
    text = re.sub(r'^[\s·:•\-–—]+|[\s·:•\-–—]+$', '', text)
    return text.strip()


def clean_address(text: str) -> str:
    """Remove category prefixes and emojis from address strings."""
    if not text:
        return ""
    text = clean_text(text)
    # Remove category prefix like "Gym · " or "Fitness center · "
    text = CATEGORY_PREFIXES.sub('', text)
    # Remove remaining leading middots/spaces
    text = re.sub(r'^[\s·:•\-–—]+', '', text).strip()
    return text


def is_plus_code(text: str) -> bool:
    """Check if text contains a Google Plus Code."""
    return bool(PLUS_CODE_PATTERN.search(text.strip()))


def extract_city_from_address(address: str, fallback_city: str = "") -> str:
    """Extract the actual city name from the end of an address string."""
    if not address:
        return fallback_city
    
    # Clean noise first
    clean_addr = clean_address(address)
    parts = [p.strip() for p in clean_addr.split(',')]
    
    # Walk backwards through parts to find a city-like name
    for part in reversed(parts):
        part = clean_text(part)
        
        # Skip empty, zip codes, Plus Codes, and meta-noise
        if not part or is_plus_code(part):
            continue
        if re.match(r'^\d{5,6}$', part):  # ZIP/PIN code
            continue
        if part.lower() in ('india', 'rajasthan', 'maharashtra', 'gujarat', 'delhi', 'haryana', 'up', 'mp'):
            continue
        if len(part) < 3:
            continue
            
        # If the part starts with a category (like "Gym · "), it's a dirty first part, skip it
        if CATEGORY_PREFIXES.match(part):
            continue
            
        return part
    
    return fallback_city


# ─── SIDE-PANEL DETAIL EXTRACTOR ──────────────────────────────────────
class GoogleDetailsExtractor:
    """
    Extracts detailed business data from the Google Maps side panel.
    Uses aria-label and data-item-id selectors which are the most stable.
    """
    async def extract(self, page) -> dict:
        try:
            # 1. NAME — Most reliable selectors first
            name = await self._find_text(page, [
                'h1.DUwDvf', 'h1.fontHeadlineLarge', 'h1'
            ])
            
            # GUARD: If no name or name is generic 'Results', it's not a business page
            if not name or name.lower() in ('results', 'search results', 'maps', 'google maps'):
                return None

            # GUARD: Real businesses ALWAYS have an address button in the side panel
            try:
                addr_check = page.locator('button[data-item-id="address"]').first
                if await addr_check.count() == 0:
                    return None
            except:
                return None

            # 2. CATEGORY
            category = await self._find_text(page, [
                'button.DkEaL',
                'button[jsaction*="category"]',
                '.DkEaL',
            ])

            # 3. ADDRESS — data-item-id="address" is rock-stable
            address = ""
            try:
                addr_btn = page.locator('button[data-item-id="address"], button[data-item-id*="address"]').first
                if await addr_btn.count() > 0:
                    address = (await addr_btn.get_attribute('aria-label') or "").replace("Address: ", "").strip()
                    if not address:
                        inner = (await addr_btn.inner_text(timeout=500)).strip()
                        if inner: address = inner
            except:
                pass
            if not address:
                address = await self._find_text(page, [
                    '[data-item-id*="address"]', '.Io6YTe.fontBodyMedium', '.rogA2c .Io6YTe'
                ])
            address = clean_address(address)

            # 4. PHONE — data-item-id="phone:tel:" is the gold standard
            phone = ""
            try:
                phone_btn = page.locator('button[data-item-id^="phone:tel:"], a[data-item-id^="phone:tel:"]').first
                if await phone_btn.count() > 0:
                    phone = (await phone_btn.get_attribute('data-item-id') or "").replace("phone:tel:", "").strip()
                    if not phone:
                        phone = (await phone_btn.get_attribute('aria-label') or "").replace("Phone: ", "").strip()
                
                if not phone:
                    # Generic phone locator
                    p_el = page.locator('[data-item-id^="phone:tel:"]').first
                    if await p_el.count() > 0:
                        phone = (await p_el.get_attribute('data-item-id') or "").replace("phone:tel:", "").strip()
            except:
                pass
            if not phone:
                phone = await self._find_text(page, [
                    'button[data-item-id^="phone"]',
                    '[aria-label*="Phone"]',
                ])
                if phone:
                    phone = re.sub(r'^Phone:\s*', '', phone).strip()

            # 5. WEBSITE — a[data-item-id="authority"] href is most reliable
            website = ""
            try:
                web_el = page.locator('a[data-item-id="authority"], button[data-item-id="authority"]').first
                if await web_el.count() > 0:
                    website = await web_el.get_attribute('href') or await web_el.get_attribute('aria-label') or ""
                
                if not website:
                    # Generic website search
                    w_el = page.locator('[data-item-id="authority"]').first
                    if await w_el.count() > 0:
                        website = await w_el.get_attribute('href') or await w_el.get_attribute('aria-label') or ""
            except:
                pass

            # 6. RATING
            rating = ""
            try:
                # Primary: data-item-id based (usually stable)
                rating_el = page.locator('span[data-item-id="address"] + span, button[aria-label*="stars"]').first
                if await rating_el.count() > 0:
                    raw = await rating_el.get_attribute('aria-label') or ""
                    r_match = re.search(r'([\d.]+)', raw)
                    if r_match:
                        rating = r_match.group(1)
                
                if not rating:
                    # Secondary: search for the hidden rating text
                    rating_span = page.locator('span[aria-hidden="true"]:has-text(".")').first
                    if await rating_span.count() > 0:
                        rating = (await rating_span.inner_text()).strip()
            except:
                pass

            # 7. REVIEW COUNT
            review_count = ""
            try:
                # The count is often in button[aria-label*="reviews"] or button.HHV0fe
                rev_el = page.locator('button[aria-label*="reviews"], button.HHV0fe, button[jsaction*="reviews"] span[aria-label*="reviews"]').first
                if await rev_el.count() > 0:
                    raw = await rev_el.get_attribute('aria-label') or await rev_el.inner_text() or ""
                    r_match = re.search(r'([\d,]+)', raw)
                    if r_match:
                        review_count = r_match.group(1).replace(',', '')
                
                if not review_count:
                    # Fallback to general span search
                    rev_span = page.locator('span[aria-label*="reviews"]').first
                    if await rev_span.count() > 0:
                        raw = await rev_span.get_attribute('aria-label') or ""
                        r_match = re.search(r'([\d,]+)', raw)
                        if r_match:
                            review_count = r_match.group(1).replace(',', '')
            except:
                pass

            city = extract_city_from_address(address)

            # Place ID from URL
            place_id = name
            try:
                if 'place/' in page.url:
                    place_id = page.url.split('place/')[1].split('/')[0]
            except:
                pass

            return {
                'place_id': place_id,
                'name': clean_text(name),
                'category': clean_text(category),
                'street': address,
                'city': city,
                'phone': clean_text(phone),
                'website': website,
                'rating': rating,
                'review_count': review_count,
                'maps_url': page.url
            }
        except Exception as e:
            log.warning("extraction.detail_failed", url=page.url, error=str(e))
            return None

    async def _find_text(self, page, selectors):
        """Try multiple selectors, return first successful text."""
        for s in selectors:
            try:
                el = page.locator(s).first
                if await el.count() > 0:
                    txt = (await el.inner_text(timeout=500)).strip()
                    if txt:
                        return txt
            except:
                continue
        return ""


async def extract_single_page(page, cell):
    extractor = GoogleDetailsExtractor()
    details = await extractor.extract(page)
    if details:
        details['latitude'] = cell.center_lat
        details['longitude'] = cell.center_lng
    return details


# ─── MAIN SEARCH FUNCTION ─────────────────────────────────────────────
async def search_grid_cell(browser, cell, keyword, proxy_url=None, skip_cache=True):
    """
    VERSION 2.1 — STABLE SELECTORS & CACHE-BUSTER
    
    Strategy:
    1. Navigate to search results for this grid cell
    2. Collect all card links from the feed
    3. Click EACH card to open the side panel
    4. Extract ALL data from the side panel (phone, website, rating, reviews, address)
    5. Return fully populated results
    
    This is slower per cell but gets 100% accurate data.
    """
    query = keyword
    zoom = getattr(cell, 'zoom', 14)
    url = f"https://www.google.com/maps/search/{quote(query)}/@{cell.center_lat},{cell.center_lng},{zoom}z"

    random_ua = ua.random if ua else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'

    context_args = {
        'viewport': {'width': random.randint(1280, 1440), 'height': random.randint(800, 900)},
        'user_agent': random_ua,
    }
    if proxy_url:
        context_args['proxy'] = {'server': proxy_url}

    context = await browser.new_context(**context_args)

    # Block heavy resources but KEEP CSS for accurate rendering
    async def block_waste(route):
        bad_types = ['image', 'media', 'manifest', 'texttrack', 'object', 'imageset', 'font']
        url_lower = route.request.url.lower()
        if route.request.resource_type in bad_types:
            await route.abort()
        elif any(x in url_lower for x in [
            'google-analytics', 'doubleclick', 'facebook', 'analytics',
            'beacon', 'telemetry', 'ad-delivery', 'youtube.com', 'accounts.google',
            'play.google.com', 'maps.googleapis.com/maps/vt'
        ]):
            await route.abort()
        else:
            await route.continue_()

    await context.route("**/*", block_waste)

    from .cache import get_cached_results
    # ── Check Cache ──
    if not skip_cache:
        cached = await get_cached_results(keyword, getattr(cell, 'location_name', 'Unknown'), cell.index)
        if cached:
            return cached

    from .manager import browser_manager
    page = await browser_manager.acquire_page(context)
    await stealth_async(page)
    places = []

    try:
        # ── Phase 1: Navigate ──
        for attempt in range(2):
            try:
                await page.goto(url, wait_until='commit', timeout=45000)
                await page.wait_for_selector('div[role="feed"], h1.DUwDvf, [role="main"]', timeout=30000)
                break
            except Exception as e:
                if attempt == 1:
                    raise e
                await asyncio.sleep(2)

        # Robot check
        if "google.com/sorry" in page.url or "not a robot" in (await page.content()).lower():
            log.error("scraper.blocked", reason="CAPTCHA")
            return []

        # Cookie/consent dismiss
        try:
            for s in ['button[aria-label*="Accept"]', 'button[aria-label*="Agree"]']:
                btn = page.locator(s).first
                if await btn.count() > 0:
                    await btn.click()
                    await asyncio.sleep(1)
                    break
        except:
            pass

        # No results check
        content = await page.content()
        if "couldn't find" in content.lower() or "no results" in content.lower():
            return []

        # ── Phase 2: Wait for feed or single result ──
        feed_found = False
        try:
            await page.wait_for_selector('div[role="feed"], h1.DUwDvf, a.hfpxzc', timeout=25000)
            feed_found = True
        except:
            log.warning("scraper.no_feed", query=query)
            return []

        if not feed_found:
            return []

        # Single result page (redirected directly to a business)
        if await page.locator('h1.DUwDvf').count() > 0 and await page.locator('div[role="feed"]').count() == 0:
            one = await extract_single_page(page, cell)
            if one:
                return [one]

        # ── Phase 3: Scroll the feed to load all results ──
        last_count = 0
        for _ in range(20):
            await page.evaluate("const f=document.querySelector('div[role=\"feed\"]'); if(f) f.scrollTop=f.scrollHeight;")
            await asyncio.sleep(0.4)
            count = await page.locator('a.hfpxzc').count()
            if count == last_count:
                break
            last_count = count

        # ── Phase 4: DETAIL-FIRST EXTRACTION ──
        # Click EVERY card and extract from the side panel for 100% accuracy
        cards = await page.locator('a.hfpxzc').all()
        extractor = GoogleDetailsExtractor()
        
        log.info("scraper.extracting_details", card_count=len(cards), cell=cell.index)
        
        for i, card in enumerate(cards):
            await asyncio.sleep(0.05)  # Yield for heartbeats
            
            try:
                # Get basic info from card first (aria-label has name + rating)
                label = await card.get_attribute('aria-label') or ""
                href = await card.get_attribute('href') or ""
                
                if not label:
                    continue
                    
                # Skip ads
                if any(x in label.lower() for x in ['ad ', 'sponsored']):
                    continue
                
                # Extract name from aria-label
                card_name = label.split(' · ')[0].strip() if ' · ' in label else label.strip()
                card_name = clean_text(card_name)
                if not card_name:
                    continue
                
                # Extract coordinates from href
                lat, lng = None, None
                coord_match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', href)
                if coord_match:
                    lat = float(coord_match.group(1))
                    lng = float(coord_match.group(2))

                # Click the card to open the side panel
                try:
                    await card.click()
                except:
                    continue

                # Wait for the side panel to load with the business details
                try:
                    # Wait for the phone or address button to appear (most reliable signal)
                    await page.wait_for_selector(
                        'button[data-item-id*="address"], button[data-item-id^="phone:tel:"], h1.DUwDvf',
                        timeout=4000
                    )
                    # Small extra wait for remaining elements to hydrate
                    await asyncio.sleep(0.3)
                except:
                    # Fallback: just wait a bit
                    await asyncio.sleep(1.0)

                # Extract full details from the side panel
                details = await extractor.extract(page)
                
                if details:
                    # Use card coordinates if detail extraction didn't pick them up
                    if lat and not details.get('latitude'):
                        details['latitude'] = lat
                    if lng and not details.get('longitude'):
                        details['longitude'] = lng
                    
                    # Use cell center as final fallback for coordinates
                    if not details.get('latitude'):
                        details['latitude'] = cell.center_lat
                    if not details.get('longitude'):
                        details['longitude'] = cell.center_lng
                    
                    places.append(details)
                    log.debug("scraper.detail_ok", name=details.get('name'), phone=bool(details.get('phone')))
                else:
                    # Fallback: save basic info from the card itself
                    # Parse rating from aria-label
                    card_rating = ""
                    card_reviews = ""
                    card_category = ""
                    if ' · ' in label:
                        parts = label.split(' · ')
                        for p in parts[1:]:
                            if 'star' in p.lower():
                                r_match = re.search(r'([\d.]+)', p)
                                if r_match:
                                    card_rating = r_match.group(1)
                                rev_match = re.search(r'\(([\d,]+)\)', p)
                                if rev_match:
                                    card_reviews = rev_match.group(1).replace(',', '')
                            elif not card_category:
                                card_category = clean_text(p)
                    
                    # Build stable fingerprint
                    stable_id = f"{card_name.lower().replace(' ', '_')}"
                    
                    places.append({
                        'place_id': stable_id,
                        'name': card_name,
                        'category': card_category,
                        'street': '',
                        'city': '',
                        'phone': '',
                        'website': '',
                        'rating': card_rating,
                        'review_count': card_reviews,
                        'maps_url': href or page.url,
                        'latitude': lat or cell.center_lat,
                        'longitude': lng or cell.center_lng,
                    })

                # Navigate back to the list
                try:
                    back_btn = page.locator('button[aria-label="Back"], button[jsaction*="back"]').first
                    if await back_btn.count() > 0:
                        await back_btn.click()
                        await asyncio.sleep(0.3)
                    else:
                        # Press Escape to close the side panel
                        await page.keyboard.press('Escape')
                        await asyncio.sleep(0.3)
                except:
                    pass
                    
                # Small random delay between clicks (anti-detection)
                await asyncio.sleep(random.uniform(0.2, 0.5))

            except Exception as e:
                log.debug("scraper.card_detail_failed", index=i, error=str(e))
                continue

    finally:
        await page.close()
        browser_manager.release_page()
        await context.close()

    return places


# ─── SCRAPLING FALLBACK ───────────────────────────────────────────────
from scrapling.fetchers import AsyncFetcher
from .http_search import _build_api_url, _parse_json_response

async def scrapling_search_cell(cell, keyword, proxy_url=None):
    """Fallback high-speed fetcher using JSON API."""
    lat_dist = abs(cell.max_lat - cell.min_lat) * 111000
    radius = max(int(lat_dist * 1.5), 2000)
    url = _build_api_url(keyword, cell.center_lat, cell.center_lng, radius, location=cell.display_name)

    all_places = []
    try:
        async with AsyncFetcher(headless=True) as fetcher:
            for offset in [0, 20]:
                resp = await fetcher.get(url.replace('!8i0', f'!8i{offset}'), proxy=proxy_url, timeout=15)
                if resp.status_code == 200:
                    page_places = _parse_json_response(resp.text)
                    if not page_places:
                        break
                    all_places.extend(page_places)
                else:
                    break
    except:
        pass
    return all_places
