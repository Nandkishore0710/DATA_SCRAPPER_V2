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
from .search import search_grid_cell, scrapling_search_cell, scrapling_search_full
from .proxy_logic import get_active_proxy_url

log = structlog.get_logger()

# Global config
JOB_TIMEOUT_SECONDS = 7200 
# Global config
JOB_TIMEOUT_SECONDS = 7200 
CONCURRENCY = 2  # Lowered to 2 for better stealth and to prevent IP flagging

async def run_keyword_pipeline(keyword_job_id: int):
    """
    VERSION 1.2 OPTIMIZED PIPELINE
    Uses high-concurrency cell processing and intelligent sleep management.
    """
    from jobs.models import KeywordJob, Place, BulkJob
    
    kj = await KeywordJob.objects.select_related('bulk_job').aget(id=keyword_job_id)
    bj = kj.bulk_job
    location = bj.location
    grid_size = bj.grid_size
    
    try:
        # Step 0: Direct Connection Mode (Disabled Proxy as per user request)
        proxy_url = None # Force Direct Server IP
        bj.execution_mode = 'direct'
        await bj.asave()

        seen = set()
        saved_count = 0
        processed_cells = 0
        
        async def _save_extracted_places(places):
            from jobs.models import KeywordJob
            # Check if job still exists
            if not await KeywordJob.objects.filter(id=keyword_job_id).aexists():
                return 0

            nonlocal saved_count
            new_objs = []
            for p in places:
                pid = p.get('place_id')
                if not pid or pid in seen: continue
                seen.add(pid)
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

        boundary = get_city_boundary(location)
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
        
        # Decide fetcher based on search type
        use_playwright = (bj.search_type == 'city')
        
        semaphore = asyncio.BoundedSemaphore(CONCURRENCY)
        processed_cells = 0

        async def _process_cell_logic(i, cell, browser=None):
            nonlocal saved_count, processed_cells
            async with semaphore:
                # 🛑 CANCELLATION CHECK: stop if user clicked cancel
                curr_status = await KeywordJob.objects.filter(id=keyword_job_id).avalues_list('status', flat=True)
                if curr_status and curr_status[0] == 'cancelled':
                    log.info("pipeline.cancelled_by_user", id=keyword_job_id)
                    return

                cached = await get_cached_results(kj.keyword, location, cell.index)
                if cached is not None:
                    await _save_extracted_places(cached)
                else:
                    if use_playwright:
                        log.info("playwright.fetch_start", cell=cell.index)
                        places = await search_grid_cell(browser, cell, kj.keyword, proxy_url=proxy_url)
                    else:
                        log.info("scrapling.fetch_start", cell=cell.index)
                        places = await scrapling_search_cell(cell, kj.keyword, proxy_url=proxy_url)
                    
                    if places:
                        await _save_extracted_places(places)
                        await set_cached_results(kj.keyword, location, cell.index, places)

            processed_cells += 1
            kj.total_extracted = saved_count
            kj.cells_done = processed_cells
            kj.status_message = f'Extraction: {saved_count} found ({processed_cells}/{len(cells)} cells)'
            if processed_cells % 5 == 0 or processed_cells == len(cells):
                try: await kj.asave()
                except: return # Job deleted
            await asyncio.sleep(random.uniform(0.5, 1.5))

        if use_playwright:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                tasks = [ _process_cell_logic(i, cell, browser=browser) for i, cell in enumerate(cells) ]
                await asyncio.gather(*tasks)
                await browser.close()
        else:
            # NO BROWSER OVERHEAD for State/Country searches
            tasks = [ _process_cell_logic(i, cell) for i, cell in enumerate(cells) ]
            await asyncio.gather(*tasks)

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
