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
                rating = await rating_el.get_attribute('aria-label') if await rating_el.count() > 0 else ""
            except: pass

            review_count = ""
            try: 
                review_btn = page.locator('button.HHrUfc[aria-label*="reviews"]').first
                if await review_btn.count() > 0:
                    review_text = await review_btn.inner_text()
                    review_count = re.sub(r'[^\d]', '', review_text)
            except: pass

            return {
                'place_id': page.url.split('place/')[1].split('/')[0] if 'place/' in page.url else name,
                'name': name,
                'category': category,
                'street': address,
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
    query = f"{keyword} in {cell.display_name}" if cell.display_name and cell.display_name.lower() not in keyword.lower() else keyword
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
        await page.goto(url, wait_until='domcontentloaded', timeout=40000)
        
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
                    await asyncio.sleep(0.5) # Wait for overlay to clear
                    break
        except: pass

        # Check for list or single result (Robust Multi-Selector Feed Detection)
        feed_selectors = ['div[role="feed"]', 'div[aria-label*="Results for"]', '.m67q60667232']
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
    cards = await page.locator('a.hfpxzc, div[role="article"], div.m67q60').all()

    for card in cards:
        try:
            # 1. Name
            name = ""
            for s in ['div.qBF1Pd', 'span.fontHeadlineSmall', '[role="heading"]']:
                el = card.locator(s).first
                if await el.count() > 0:
                    name = (await el.text_content() or "").strip()
                    if name: break
            if not name: continue

            # 2. Rating & Reviews
            rating = ""
            rating_el = card.locator('span.MW4etd, [aria-label*="stars"]').first
            if await rating_el.count() > 0:
                rating = re.sub(r'[^\d\.]', '', (await rating_el.text_content() or ""))

            # 3. Details (Category/Address/Phone)
            lines = await card.locator('div.W4Efsd').all_text_contents()
            clean = [l.strip() for l in lines if l.strip()]
            
            category = clean[0] if clean else ""
            address = ""
            phone = ""
            for line in clean[1:]:
                if re.search(r'[\+\d][\d\s\-]{7,}', line): phone = line
                elif not address and len(line) > 5: address = line

            # 4. Lat/Lng and ID from URL
            lat, lng = cell.center_lat, cell.center_lng
            place_id = name
            maps_url = ""
            link_el = card.locator('a[href*="/maps/place/"]').first
            if await link_el.count() > 0:
                href = await link_el.get_attribute('href')
                maps_url = href
                id_match = re.search(r'place/([^/]+)/', href)
                if id_match: place_id = id_match.group(1)
                coord_match = re.search(r'!3d([-\d\.]+)!4d([-\d\.]+)', href)
                if coord_match:
                    lat, lng = float(coord_match.group(1)), float(coord_match.group(2))

            places.append({
                'place_id': place_id,
                'name': name,
                'category': category,
                'street': address,
                'phone': phone,
                'rating': rating,
                'maps_url': maps_url,
                'latitude': lat,
                'longitude': lng,
            })
        except: continue
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
