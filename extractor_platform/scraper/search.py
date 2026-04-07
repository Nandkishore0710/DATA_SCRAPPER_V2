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

    # 🏎️ ULTRA-SLIM: Block all non-essential resources to kill CPU spikes
    async def block_waste(route):
        bad_types = ['image', 'stylesheet', 'font', 'media', 'other', 'manifest', 'texttrack', 'object', 'imageset']
        if route.request.resource_type in bad_types:
            await route.abort()
        elif any(x in route.request.url.lower() for x in ['google-analytics', 'doubleclick', 'facebook', 'analytics', 'beacon', 'telemetry', 'ad-delivery']):
            await route.abort()
        else:
            await route.continue_()

    await context.route("**/*", block_waste)
    
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
    """HYPER-FAST ARIA SCANNER: Extracts data instantly from the list without clicking."""
    places = []
    # Identify result cards (links with specific class 'hfpxzc' or generic article role)
    cards = await page.locator('a.hfpxzc, [role="article"]').all()

    for i, card in enumerate(cards):
        try:
            # 1. Get ARIA metadata (High efficiency)
            label = await card.get_attribute('aria-label') or ""
            text = await card.inner_text() or ""
            
            # 🕵️‍♂️ AD BLOCKADE
            if any(ad_marker in label.lower() or ad_marker in text.lower() for ad_marker in ['ad ', 'sponsored']):
                continue

            # 2. NAME EXTRACTION (From card text)
            name = label.split(' · ')[0] if ' · ' in label else text.split('\n')[0]
            if not name: continue

            # 3. METADATA PARSING (Rating, Count, Category)
            # Google often formats aria-label: "Name · Rating (Reviews) · Category"
            rating = ""
            review_count = ""
            category = ""
            
            if ' · ' in label:
                parts = [p.strip() for p in label.split(' · ')]
                if len(parts) >= 2:
                    # Look for rating e.g. "4.5 stars"
                    r_match = re.search(r'(\d[\d\.]*)\s+stars', label)
                    if r_match: rating = r_match.group(1)
                    
                    # Look for reviews e.g. "(1,234)"
                    rev_match = re.search(r'\((\d[\d,]*)\)', label)
                    if rev_match: review_count = rev_match.group(1).replace(',', '')
                    
                    # Category is often the last part or middle
                    category = parts[1] if len(parts) > 1 else ""

            # 4. ADDRESS / PHONE / WEBSITE (Scraped from card text lines)
            lines = text.split('\n')
            address = ""
            phone = ""
            website = ""
            
            # Heuristic: Addresses or phone numbers are usually in the 3rd or 4th line
            for line in lines[1:]:
                if re.search(r'\d{5}', line): address = line # Zip code hint
                if re.search(r'(\d{3}-\d{3}-\d{4}|\+\d{2})', line): phone = line # Phone pattern
                if '.' in line and '/' not in line and ' ' not in line: website = line # Simple URL hint

            places.append({
                'place_id': f"{name}_{cell.index}_{i}",
                'name': name,
                'category': category,
                'street': address or "See Dashboard",
                'city': address.split(',')[0].strip() if address and ',' in address else "Bhilwara",
                'phone': phone or "Check Panel",
                'website': website,
                'rating': rating,
                'review_count': review_count,
                'maps_url': await card.get_attribute('href') or page.url
            })
        except Exception as e:
            log.debug("scraper.card_skipped", error=str(e))
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
