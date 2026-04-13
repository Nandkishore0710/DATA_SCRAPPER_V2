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
        elif any(x in route.request.url.lower() for x in ['google-analytics', 'doubleclick', 'facebook', 'analytics', 'beacon', 'telemetry', 'ad-delivery', 'youtube.com', 'accounts.google']):
            await route.abort()
        else:
            await route.continue_()

    await context.route("**/*", block_waste)
    
    from .manager import browser_manager
    page = await browser_manager.acquire_page(context)
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
                    await asyncio.sleep(1) 
                    break
        except: pass

        # 🕵️‍♂️ CHECK FOR "NO RESULTS" TEXT
        no_res_txt = await page.content()
        if "couldn't find" in no_res_txt.lower() or "no results" in no_res_txt.lower():
            log.info("scraper.zero_results", query=query, cell=cell.id)
            return []

        # Check for list or single result
        feed_found = False
        try:
            await page.wait_for_selector('div[role="feed"], h1.DUwDvf', timeout=12000)
            feed_found = True
        except: pass
            
        if not feed_found:
            log.warning("scraper.no_results_feed", query=query, url=page.url)
            return []

        if await page.locator('h1.DUwDvf').count() > 0:
            one = await extract_single_page(page, cell)
            if one: return [one]

        # Fast Scroll
        last_count = 0
        for _ in range(25):
            await page.evaluate("const f=document.querySelector('div[role=\"feed\"]'); if(f) f.scrollTop=f.scrollHeight;")
            await asyncio.sleep(0.5)
            count = await page.locator('div[role="feed"] > div > div[jsaction]').count()
            if count == last_count: break
            last_count = count

        places = await extract_from_cards(page, cell)

        # 🎯 PRECISION UPGRADE: Deep Scan Fallback
        # If any place is missing critical data, click and extract specifically from the side panel
        # Limit deep scans to 20 per cell to maintain performance/avoid detection
        incomplete_places = [p for p in places if not p.get('phone') or not p.get('website')]
        
        if incomplete_places:
            log.info("scraper.deep_scan_start", count=len(incomplete_places))
            extractor = GoogleDetailsExtractor()
            cards = await page.locator('a.hfpxzc, [role="article"]').all()
            
            for i, p in enumerate(places):
                # Skip if already complete
                if p.get('phone') and p.get('website'):
                    continue
                
                # Check for stopping condition/exhaustion
                if i >= len(cards): break
                
                try:
                    card = cards[i]
                    # Ensure we are clicking the right card by checking the name
                    card_label = await card.get_attribute('aria-label') or ""
                    if p['name'] not in card_label:
                        continue
                    
                    await card.click()
                    # Wait for side panel to update (Name should match)
                    try:
                        await page.wait_for_selector(f'h1:has-text("{p["name"]}")', timeout=5000)
                    except:
                        # Fallback: maybe just wait a second
                        await asyncio.sleep(1.2)
                    
                    details = await extractor.extract(page)
                    if details:
                        # Merge details (Detail page is always more accurate)
                        p.update({
                            'street': details.get('street') or p.get('street'),
                            'phone': details.get('phone') or p.get('phone'),
                            'website': details.get('website') or p.get('website'),
                            'rating': details.get('rating') or p.get('rating'),
                            'review_count': details.get('review_count') or p.get('review_count'),
                            'category': details.get('category') or p.get('category'),
                        })
                        log.debug("scraper.deep_scan_success", name=p['name'])
                    
                    # Small human-like variance
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                except Exception as e:
                    log.debug("scraper.deep_scan_failed", name=p['name'], error=str(e))

    finally:
        await page.close()
        browser_manager.release_page()
        await context.close()
    return places

async def extract_from_cards(page, cell) -> list:
    """HYPER-FAST ARIA SCANNER: Extracts data instantly from the list with improved regex heuristics."""
    places = []
    cards = await page.locator('a.hfpxzc, [role="article"]').all()

    for i, card in enumerate(cards):
        try:
            label = await card.get_attribute('aria-label') or ""
            text = await card.inner_text() or ""
            
            if any(ad_marker in label.lower() or ad_marker in text.lower() for ad_marker in ['ad ', 'sponsored']):
                continue

            # 2. NAME EXTRACTION
            name = label.split(' · ')[0] if ' · ' in label else text.split('\n')[0]
            if not name: continue

            # 3. METADATA PARSING (Rating, Count, Category)
            rating = ""
            review_count = ""
            category = ""
            
            # Use Regex on Label which is more structured
            # Format: "Name · 4.5 stars (1,234) · Category"
            if ' · ' in label:
                parts = label.split(' · ')
                for p in parts:
                    # Check for rating
                    if 'stars' in p.lower():
                        r_match = re.search(r'(\d[\d\.]*)', p)
                        if r_match: rating = r_match.group(1)
                        # Check for reviews inside parentheses after the rating
                        rev_match = re.search(r'\((\d[\d,]*)\)', p)
                        if rev_match: review_count = rev_match.group(1).replace(',', '')
                    elif p != name and not any(x in p.lower() for x in ['stars', 'reviews']):
                        # If it's not the name and not rating, it's likely the category
                        if not category: category = p.strip()

            # 4. ADDRESS / PHONE / WEBSITE
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            address = ""
            phone = ""
            website = ""
            
            for line in lines:
                # Website Heuristic: Must contain '.' but NOT be a number (like rating 4.5)
                # Stricter URL regex
                if re.search(r'^[a-zA-Z0-9-]+\.[a-zA-Z]{2,6}(/.*)?$', line) or ('.' in line and ('/' in line or 'www' in line.lower())):
                    # Ensure it's not a rating (e.g. "4.5") or review count
                    if not re.search(r'^\d+\.?\d*$', line):
                        website = line
                # Phone Heuristic (Standard formats)
                elif re.search(r'(\d{3,}-\d{3,}-\d{4}|\+\d{1,3}|^\d{10,12}$)', line.replace(' ', '')):
                    phone = line
                # Address Heuristic: Usually longer lines or lines with specific parts
                elif len(line) > 10 and (any(x in line.lower() for x in ['rd', 'st', 'ave', 'lane', 'mumbai', 'india', 'pincode']) or re.search(r'\d{6}', line)):
                    if not address: address = line

            places.append({
                'place_id': f"{name}_{cell.index}_{i}",
                'name': name,
                'category': category,
                'street': address,
                'city': address.split(',')[0].strip() if address and ',' in address else "Bhilwara",
                'phone': phone,
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
