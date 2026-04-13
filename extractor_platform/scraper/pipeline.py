# scraper/pipeline.py
import asyncio
import random
import structlog
from django.utils import timezone
from playwright.async_api import async_playwright

# Local imports
from .boundary import get_city_boundary
from .grid import build_grid
from .cache import get_cached_results, set_cached_results
from .search import search_grid_cell, scrapling_search_cell
from .proxy_logic import get_active_proxy_url

log = structlog.get_logger()

# Global config
JOB_TIMEOUT_SECONDS = 7200 
CONCURRENCY = 4  # 🚀 PRO SPEED: Optimized for 4vCPU VPS

async def run_keyword_pipeline(keyword_job_id: int):
    """
    VERSION 1.3 SMART PIPELINE
    Includes automated stopping for lead limits and area exhaustion.
    """
    from jobs.models import KeywordJob, Place, BulkJob
    
    kj = await KeywordJob.objects.select_related('bulk_job', 'bulk_job__user').aget(id=keyword_job_id)
    bj = kj.bulk_job
    location = bj.location
    grid_size = bj.grid_size
    
    # Get User Lead Limit
    lead_limit = 5000
    try:
        profile = await bj.user.profile.aget()
        if profile.package: lead_limit = profile.package.lead_limit
    except: pass

    try:
        # Step 0: Direct Connection Mode (Force Direct Server IP)
        proxy_url = None 
        bj.execution_mode = 'direct'
        await bj.asave()

        seen_fingerprints = set() # Stable ID tracking
        saved_count = 0
        processed_cells = 0
        consecutive_empty = 0
        MAX_EMPTY = 10 
        
        async def _save_extracted_places(places):
            from jobs.models import KeywordJob
            # Check if job still exists
            if not await KeywordJob.objects.filter(id=keyword_job_id).aexists():
                return 0

            nonlocal saved_count
            new_objs = []
            for p in places:
                # 🛡️ COORDINATE GEOFENCING: Drop results further than 40km from Bhilwara
                lat, lng = p.get('latitude'), p.get('longitude')
                if lat and lng:
                    # Rough distance check for Bhilwara area (center: 25.35, 74.64)
                    dist = math.sqrt((float(lat) - 25.348)**2 + (float(lng) - 74.636)**2)
                    if dist > 0.45: # Approx 45-50km radius
                        log.info("pipeline.out_of_bounds_discarded", name=p.get('name'), dist=dist)
                        continue

                # 🆔 STABLE IDENTITY CHECK: Use place_id (fingerprint)
                pid = p.get('place_id')
                if not pid or pid in seen_fingerprints: continue
                
                # Double-check database to prevent duplicates across different cells/phases
                exists = await Place.objects.filter(keyword_job_id=keyword_job_id, place_id=pid).aexists()
                if exists:
                    seen_fingerprints.add(pid)
                    continue

                seen_fingerprints.add(pid)
                new_objs.append(Place(keyword_job_id=keyword_job_id, **p))
            
            if new_objs:
                try:
                    await Place.objects.abulk_create(new_objs, ignore_conflicts=True)
                    saved_count += len(new_objs)
                    return len(new_objs)
                except Exception as e:
                    log.warning("pipeline.save_skipped", error=str(e))
            return 0

        # Phase 1 — Boundary (CRITICAL: Need coordinates for all modes)
        kj.status = 'fetching_boundary'
        await kj.asave()

        boundary = await get_city_boundary(location)
        if not boundary:
            kj.status = 'failed'
            kj.status_message = f"Could not find coordinates for {location}"
            await kj.asave()
            return

        # Debug Prints for Colleague
        center_lat = (boundary['min_lat'] + boundary['max_lat']) / 2
        center_lng = (boundary['min_lng'] + boundary['max_lng']) / 2
        log.info("pipeline.boundary_data", boundary=boundary)
        log.info("pipeline.calculated_center", lat=center_lat, lng=center_lng)

        # Phase 2 — Grid
        kj.status = 'building_grid'
        # Even for state_country, we now build a grid to ensure we get ALL results
        cells = build_grid(boundary, grid_size)
        kj.total_cells = len(cells)
        await kj.asave()

        # Phase 3 — Execution
        kj.status = 'searching'
        await kj.asave()

        log.info("pipeline.processing_active", search_type=bj.search_type, grid_size=grid_size, total_cells=len(cells))
        
        # Decide fetcher based on search type (Always use optimized Playwright for robustness)
        use_playwright = True 
        
        # We now use the BrowserManager singleton for high-concurrency stability
        from .manager import browser_manager
        
        semaphore = asyncio.BoundedSemaphore(CONCURRENCY)
        processed_cells = 0

        async def _process_cell_logic(i, cell, browser=None):
            nonlocal saved_count, processed_cells, consecutive_empty
            
            # 🛑 STOP CHECK: Limit or Exhaustion
            if saved_count >= lead_limit:
                kj.status_message = f"Stopped: Lead Limit Reached ({lead_limit})"
                kj.status = 'completed'
                return
            if consecutive_empty >= MAX_EMPTY:
                kj.status_message = f"Stopped: Area Exhausted (Checked {processed_cells} cells)"
                kj.status = 'completed'
                return

            # 🛑 PRE-EMPTIVE INCREMENT
            processed_cells += 1
            if processed_cells % 2 == 0:
                kj.cells_done = processed_cells
                kj.total_extracted = saved_count # 🎯 CRITICAL: Sync current lead count to UI
                await kj.asave()

            try:
                async with semaphore:
                    # 🛑 CANCELLATION CHECK
                    curr_job = await KeywordJob.objects.filter(id=keyword_job_id).only('status').aget()
                    if curr_job.status in ('cancelled', 'completed'):
                        return

                    cached = await get_cached_results(kj.keyword, location, cell.index)
                    if cached is not None:
                        found = await _save_extracted_places(cached)
                        if found > 0: consecutive_empty = 0
                        else: consecutive_empty += 1
                    else:
                        if use_playwright:
                            places = await search_grid_cell(browser, cell, kj.keyword, proxy_url=proxy_url)
                        else:
                            places = await scrapling_search_cell(cell, kj.keyword, proxy_url=proxy_url)
                        
                        if places:
                            found = await _save_extracted_places(places)
                            await set_cached_results(kj.keyword, location, cell.index, places)
                            if found > 0: consecutive_empty = 0
                            else: consecutive_empty += 1
                        else:
                            consecutive_empty += 1
                    
                    # ❄️ COOLDOWN: Yield for stability
                    await asyncio.sleep(1.5)

            except Exception as e:
                log.warning("pipeline.cell_failed", index=cell.index, error=str(e))
            finally:
                # Ensure status message is always updated
                kj.total_extracted = saved_count
                kj.status_message = f'Extraction: {saved_count} found ({processed_cells}/{len(cells)} cells)'
                if processed_cells == len(cells):
                    await kj.asave()

        if use_playwright:
            browser = await browser_manager.get_browser()
            tasks = [ _process_cell_logic(i, cell, browser=browser) for i, cell in enumerate(cells) ]
            # 🛑 RETURN_EXCEPTIONS=True: Key for resiliency
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            tasks = [ _process_cell_logic(i, cell) for i, cell in enumerate(cells) ]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Finalize (Only if not cancelled)
        await kj.arefresh_from_db()
        if kj.status != 'cancelled':
            kj.total_extracted = saved_count
            kj.status = 'completed'
            kj.status_message = f'Finished! {saved_count} leads total.'
            kj.completed_at = timezone.now()
            await kj.asave()

    except Exception as e:
        # Final safety check if the job still exists
        try:
            from jobs.models import KeywordJob
            if await KeywordJob.objects.filter(id=keyword_job_id).aexists():
                kj.status = 'failed'
                kj.status_message = f'Fatal Error: {str(e)}'
                await kj.asave()
        except:
            pass
        log.error("pipeline.fatal", error=str(e))
