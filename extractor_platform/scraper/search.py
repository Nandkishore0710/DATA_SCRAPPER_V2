# scraper/search.py
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
        # Fallback to sync or no-op if async is missing
        async def stealth_async(page, **kwargs): pass

from fake_useragent import UserAgent

ua = UserAgent()
from scraper.cache import get_cached_results, set_cached_results

log = structlog.get_logger()

class GoogleDetailsExtractor:
    """
    Handles robust extraction of a single business from its detail page.
    Uses multi-strategy fallbacks to survive Google Maps UI updates.
    """
    async def extract(self, page) -> dict:
        try:
            # 1. NAME Extraction (Robust Fallbacks)
            name = await self._find_text(page, [
                'h1.DUwDvf', 'h1.fontHeadlineLarge', 'h1.du43p', 'h1', '[role="heading"]'
            ])
            if not name: return None

            # 2. CATEGORY Extraction 
            category = await self._find_text(page, [
                'button[jsaction*="category"]', '.fontBodyMedium[jsaction*="category"]', '.u60ur'
            ])
            
            # 3. ADDRESS Extraction (Data-item-id is the most stable)
            address = await self._find_text(page, [
                'button[data-item-id*="address"]', '[aria-label*="Address"]', '.Io6YTe.fontBodyMedium'
            ])

            # 4. PHONE Extraction
            phone = await self._find_text(page, [
                'button[data-item-id*="phone"]', '[aria-label*="Phone"]', '.fontBodyMedium[aria-label*="Phone"]'
            ])

            # 5. WEBSITE Extraction
            web_el = page.locator('a[data-item-id*="authority"], [aria-label*="Website"], .fontBodyMedium[aria-label*="Website"]').first
            website = await web_el.get_attribute('href') if await web_el.count() > 0 else ""

            # 6. RATING & REVIEWS
            rating = ""
            try: 
                rating_el = page.locator('span.ceNzR[aria-label*="stars"]').first
                if await rating_el.count() > 0:
                    raw = await rating_el.get_attribute('aria-label')
                    rating = re.sub(r'[^\d\.]', '', raw.split(' ')[0]) if raw else ""
            except: pass

            review_count = ""
            try: 
                review_btn = page.locator('button.HHrUfc[aria-label*="reviews"]').first
                if await review_btn.count() > 0:
                    review_text = await review_btn.inner_text()
                    review_count = re.sub(r'[^\d]', '', review_text)
            except: pass

            # Smart Address Parsing
            city = ""
            if address and ',' in address:
                parts = [p.strip() for p in address.split(',')]
                if len(parts) >= 2:
                    city = parts[-2] if len(parts) < 4 else parts[-3]

            return {
                'place_id': page.url.split('place/')[1].split('/')[0] if 'place/' in page.url else name,
                'name': name,
                'category': category,
                'street': address,
                'city': city,
                'phone': phone,
                'website': website,
                'rating': rating,
                'review_count': review_count,
                'maps_url': page.url
            }
        except Exception as e:
            log.warning("extraction.failed", url=page.url, error=str(e))
            return None

    async def _find_text(self, page, selectors):
        """Try multiple selectors and return first successful inner text."""
        for s in selectors:
            try:
                el = page.locator(s).first
                if await el.count() > 0:
                    txt = (await el.inner_text(timeout=400)).strip()
                    if txt: return txt
            except: continue
        return ""

async def extract_single_page(page, cell):
    extractor = GoogleDetailsExtractor()
    details = await extractor.extract(page)
    if details:
        # Add coordinates from cell center if not present in details
        details['latitude'] = cell.center_lat
        details['longitude'] = cell.center_lng
    return details

async def search_grid_cell(browser, cell, keyword, proxy_url=None):
    """
    VERSION 1.4 — Layout-Agnostic Extraction
    Uses multi-selector fallbacks to survive Google Maps updates.
    """
    query = keyword
    zoom = getattr(cell, 'zoom', 14)
    url = f"https://www.google.com/maps/search/{quote(query)}/@{cell.center_lat},{cell.center_lng},{zoom}z"

    # Dynamic, realistic User-Agent
    random_ua = ua.random if ua else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
    
    # Correct Playwright Proxy Parameter
    context_args = {
        'viewport': {'width': random.randint(1280, 1440), 'height': random.randint(800, 900)},
        'user_agent': random_ua,
    }
    
    if proxy_url:
        context_args['proxy'] = {'server': proxy_url}
        log.info("playwright.context_created", proxy=proxy_url)

    context = await browser.new_context(**context_args)

    # Optimize: Block images/styles (saves bandwidth & speed)
    await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf,css}", lambda r: r.abort())
    
    page = await context.new_page()
    await stealth_async(page) # Apply fingerprint masks
    places = []

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        
        # 🤖 ROBOT DETECTION (Explicit check for CAPTCHAs)
        content = await page.content()
        if "google.com/sorry" in page.url or "not a robot" in content.lower():
            log.error("scraper.blocked", reason="CAPTCHA_DETECTED", proxy=proxy_url)
            return []

        # Cookie acceptance (Aggressive & Multi-language)
        try:
            for s in ['button[aria-label*="Accept"]', 'button[aria-label*="Agree"]', 'button.VfPpkd-LgbsSe', 'button[aria-label*="Alle akzeptieren"]']:
                btn = page.locator(s).first
                if await btn.count() > 0:
                    await btn.click()
                    # WAIT LONGER for the overlay to fully clear (Crucial for Cloud VPS)
                    await asyncio.sleep(1.5) 
                    break
        except: pass

        # 🕵️‍♂️ CHECK FOR "NO RESULTS" TEXT (Avoid false blockage alarms)
        no_res_txt = await page.content()
        if "couldn't find" in no_res_txt.lower() or "no results" in no_res_txt.lower():
            log.info("scraper.zero_results", query=query, cell=cell.id)
            return []

        # Check for list or single result (Robust Multi-Selector Feed Detection)
        feed_selectors = [
            'div[role="feed"]', 
            'div[aria-label*="Results for"]', 
            '.m67q60667232', 
            '.m67q60B67232', 
            'a.hfpxzc' # If the lead cards are visible, the feed is loaded
        ]
        feed_found = False
        for fs in feed_selectors:
            try:
                await page.wait_for_selector(fs, timeout=8000)
                feed_found = True
                break
            except: continue
            
        if not feed_found:
            # Maybe it redirected to a single place page
            if await page.locator('h1.DUwDvf').count() > 0:
                one = await extract_single_page(page, cell)
                if one: return [one]
            log.warning("scraper.no_results_feed", query=query, url=page.url)
            return []

        # Fast Scroll
        last_count = 0
        for _ in range(30):
            await page.evaluate("const f=document.querySelector('div[role=\"feed\"]'); if(f) f.scrollTop=f.scrollHeight;")
            await asyncio.sleep(0.7)
            count = await page.locator('div[role="feed"] > div > div[jsaction]').count()
            if count == last_count: break
            last_count = count

        places = await extract_from_cards(page, cell)

    finally:
        await context.close()
    return places

async def extract_from_cards(page, cell) -> list:
    """Extract list of businesses from result cards using layout-agnostic selectors."""
    places = []
    # Identify result cards (links with specific class 'hfpxzc' or generic article role)
    cards = await page.locator('a.hfpxzc, [role="article"]').all()

    for i, card in enumerate(cards):
        try:
            # 🕵️‍♂️ AD BLOCKADE: Check if this is a 'Sponsored' or 'Ad' result
            card_text = (await card.text_content() or "").lower()
            if any(ad_marker in card_text for ad_marker in ['ad ', 'sponsored', 'advertisement']):
                log.info("scraper.ad_skipped", index=i)
                continue

            # 1. Activate Detail Panel by clicking the card (FORCE it to bypass overlays)
            try:
                await card.click(force=True, timeout=5000)
            except Exception as e:
                log.debug("scraper.click_retry", index=i, error=str(e))
                # Fallback to JS click if Playwright's force-click still struggles
                await page.evaluate("(el) => el.click()", await card.element_handle())
            
            # Give short time for profile to start loading
            await asyncio.sleep(1.2) 
            
            # 1. Name
            name = ""
            name_el = page.locator('h1.DUwDvf').first
            if await name_el.count() > 0:
                name = (await name_el.text_content() or "").strip()
            
            if not name:
                # Fallback to card name if panel h1 isn't ready
                name_el = card.locator('div.qBF1Pd, [role="heading"]').first
                name = (await name_el.text_content() or "").strip()
                
            if not name: continue

            # 2. Rating & Review Count
            rating = ""
            review_count = ""
            try:
                # Optimized Rating Selector (Checks aria-labels and text)
                rating_el = page.locator('span.MW4etd, span.ceA7Yc, [aria-label*="stars"]').first
                if await rating_el.count() > 0:
                    raw_rating = await rating_el.get_attribute('aria-label') or await rating_el.text_content() or ""
                    # Extract decimal number (e.g., "4.5" from "4.5 stars")
                    import re # Ensue re is available
                    match = re.search(r'(\d[\d\.]*)', raw_rating)
                    if match:
                        rating = match.group(1)
                
                rev_el = page.locator('span.UY7F9 button, span.UY7F9').first
                if await rev_el.count() > 0:
                    review_count = re.sub(r'[^\d]', '', await rev_el.text_content() or "")
            except: pass

            # 3. Precise Profile Extraction (Phone/Address/City)
            address = ""
            phone = ""
            website = ""
            city = ""
            
            # Address & City
            addr_btn = page.locator('button[aria-label^="Address:"]').first
            if await addr_btn.count() > 0:
                address = (await addr_btn.get_attribute('aria-label') or "").replace("Address: ", "").strip()
                if ',' in address:
                    parts = [p.strip() for p in address.split(',')]
                    # Logic: last part is pincode/state, 2nd to last is usually city
                    if len(parts) >= 2:
                        city = parts[-2] if len(parts) < 4 else parts[-3]
            
            # Phone
            phone_btn = page.locator('button[aria-label^="Phone:"]').first
            if await phone_btn.count() > 0:
                phone = (await phone_btn.get_attribute('aria-label') or "").replace("Phone: ", "").strip()
            
            # Website
            web_btn = page.locator('a[data-item-id="authority"]').first
            if await web_btn.count() > 0:
                website = await web_btn.get_attribute('href') or ""

            # 4. Final Place Object
            lat, lng = cell.center_lat, cell.center_lng
            places.append({
                'place_id': name,
                'name': name,
                'category': "Business",
                'street': address,
                'city': city,
                'phone': phone,
                'rating': rating, # Correctly match the 'Place' model
                'review_count': review_count,
                'website': website,
                'maps_url': page.url,
                'latitude': lat,
                'longitude': lng
            })

            # Check for early termination limit (safety)
            if len(places) >= 150: break

        except Exception as e:
            log.info("scraper.card_error", error=str(e))
            continue

    return places

# Helper imports for scrapling-based fallback if needed
from scrapling.fetchers import AsyncFetcher
from .http_search import _build_api_url, _parse_json_response

async def scrapling_search_cell(cell, keyword, proxy_url=None):
    """Fallback high-speed fetcher using JSON API obfuscation."""
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
                    if not page_places: break
                    all_places.extend(page_places)
                else: break
    except: pass
    return all_places
