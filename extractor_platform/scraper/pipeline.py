# scraper/pipeline.py
# VERSION 2.0 — PRODUCTION PIPELINE
# Fixed: Instant cancellation, name-based deduplication, proper stop logic
import asyncio
import random
import math
import re
import structlog
from django.utils import timezone
from playwright.async_api import async_playwright

# Local imports
from .boundary import get_city_boundary
from .grid import build_grid
from .cache import get_cached_results, set_cached_results
from .search import search_grid_cell, scrapling_search_cell, clean_text
from .proxy_logic import get_active_proxy_url

log = structlog.get_logger()

# Global config
JOB_TIMEOUT_SECONDS = 7200
CONCURRENCY = 4  # 🚀 Optimized for 4vCPU VPS


def normalize_name(name: str) -> str:
    """Create a stable fingerprint from a business name for deduplication.
    Strips emojis, punctuation, extra spaces, and lowercases everything."""
    if not name:
        return ""
    name = clean_text(name)
    # Remove all non-alphanumeric characters except spaces
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name)
    # Collapse whitespace and lowercase
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name


async def run_keyword_pipeline(keyword_job_id: int):
    """
    VERSION 2.0 PIPELINE
    - Instant cancellation via shared flag (no waiting for semaphore)
    - Name-based deduplication (same business from different cells = 1 result)
    - Proper stop on user cancel
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
        if profile.package:
            lead_limit = profile.package.lead_limit
    except:
        pass

    try:
        proxy_url = None
        bj.execution_mode = 'direct'
        await bj.asave()

        seen_fingerprints = set()  # place_id based tracking
        seen_names = set()         # 🛡️ NAME-BASED dedup (catches cross-cell duplicates)
        saved_count = 0
        processed_cells = 0
        consecutive_empty = 0
        MAX_EMPTY = 10
        
        # 🛑 CANCELLATION FLAG — shared across all tasks for INSTANT stop
        cancelled = False

        async def _check_cancelled():
            """Check if the job has been cancelled by the user."""
            nonlocal cancelled
            if cancelled:
                return True
            try:
                curr = await KeywordJob.objects.filter(id=keyword_job_id).only('status').aget()
                if curr.status in ('cancelled', 'completed'):
                    cancelled = True
                    return True
            except:
                cancelled = True
                return True
            return False

        async def _save_extracted_places(places):
            """Save places with dual deduplication: place_id + normalized name."""
            nonlocal saved_count, cancelled

            if cancelled:
                return 0

            # Check if job still exists
            if not await KeywordJob.objects.filter(id=keyword_job_id).aexists():
                cancelled = True
                return 0

            new_objs = []
            for p in places:
                if cancelled:
                    break

                # 🛡️ DUAL DEDUP: Check both place_id AND normalized name
                pid = p.get('place_id', '')
                name_key = normalize_name(p.get('name', ''))

                # Skip if we've seen this place_id
                if pid and pid in seen_fingerprints:
                    continue

                # Skip if we've seen this exact name (catches cross-cell duplicates)
                if name_key and name_key in seen_names:
                    log.debug("pipeline.name_dedup", name=p.get('name'))
                    continue

                # Database-level check
                if pid:
                    exists = await Place.objects.filter(
                        keyword_job_id=keyword_job_id, place_id=pid
                    ).aexists()
                    if exists:
                        seen_fingerprints.add(pid)
                        if name_key:
                            seen_names.add(name_key)
                        continue

                seen_fingerprints.add(pid)
                if name_key:
                    seen_names.add(name_key)
                new_objs.append(Place(keyword_job_id=keyword_job_id, **p))

            if new_objs and not cancelled:
                try:
                    await Place.objects.abulk_create(new_objs, ignore_conflicts=True)
                    saved_count += len(new_objs)
                    return len(new_objs)
                except Exception as e:
                    log.warning("pipeline.save_skipped", error=str(e))
            return 0

        # Phase 1 — Boundary
        kj.status = 'fetching_boundary'
        await kj.asave()

        boundary = await get_city_boundary(location)
        if not boundary:
            kj.status = 'failed'
            kj.status_message = f"Could not find coordinates for {location}"
            await kj.asave()
            return

        center_lat = (boundary['min_lat'] + boundary['max_lat']) / 2
        center_lng = (boundary['min_lng'] + boundary['max_lng']) / 2
        log.info("pipeline.boundary_data", boundary=boundary)

        # Phase 2 — Grid
        kj.status = 'building_grid'
        cells = build_grid(boundary, grid_size)
        kj.total_cells = len(cells)
        await kj.asave()

        # Phase 3 — Execution
        kj.status = 'searching'
        await kj.asave()

        log.info("pipeline.start", search_type=bj.search_type, grid_size=grid_size, total_cells=len(cells))

        use_playwright = True
        from .manager import browser_manager

        semaphore = asyncio.BoundedSemaphore(CONCURRENCY)

        async def _process_cell_logic(i, cell, browser=None):
            nonlocal saved_count, processed_cells, consecutive_empty, cancelled

            # 🛑 INSTANT CANCEL CHECK — BEFORE waiting for semaphore
            if cancelled or await _check_cancelled():
                return

            # Stop conditions
            if saved_count >= lead_limit:
                cancelled = True
                return
            if consecutive_empty >= MAX_EMPTY:
                cancelled = True
                return

            async with semaphore:
                # 🛑 CHECK AGAIN after acquiring semaphore (could have been cancelled while waiting)
                if cancelled or await _check_cancelled():
                    return

                processed_cells += 1

                try:
                    cached = await get_cached_results(kj.keyword, location, cell.index)
                    if cached is not None:
                        found = await _save_extracted_places(cached)
                        if found > 0:
                            consecutive_empty = 0
                        else:
                            consecutive_empty += 1
                    else:
                        if use_playwright:
                            places = await search_grid_cell(browser, cell, kj.keyword, proxy_url=proxy_url)
                        else:
                            places = await scrapling_search_cell(cell, kj.keyword, proxy_url=proxy_url)

                        # 🛑 CHECK CANCEL after slow operation
                        if cancelled or await _check_cancelled():
                            return

                        if places:
                            found = await _save_extracted_places(places)
                            await set_cached_results(kj.keyword, location, cell.index, places)
                            if found > 0:
                                consecutive_empty = 0
                            else:
                                consecutive_empty += 1
                        else:
                            consecutive_empty += 1

                    # Update progress every cell
                    kj.cells_done = processed_cells
                    kj.total_extracted = saved_count
                    kj.status_message = f'Extraction: {saved_count} found ({processed_cells}/{len(cells)} cells)'
                    await kj.asave()

                    # Cooldown
                    await asyncio.sleep(1.0)

                except Exception as e:
                    log.warning("pipeline.cell_failed", index=cell.index, error=str(e))

        if use_playwright:
            browser = await browser_manager.get_browser()
            tasks = [_process_cell_logic(i, cell, browser=browser) for i, cell in enumerate(cells)]
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            tasks = [_process_cell_logic(i, cell) for i, cell in enumerate(cells)]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Finalize (Only if not cancelled)
        await kj.arefresh_from_db()
        if kj.status != 'cancelled':
            kj.total_extracted = saved_count
            kj.status = 'completed'
            kj.status_message = f'Finished! {saved_count} unique leads.'
            kj.completed_at = timezone.now()
            await kj.asave()

    except Exception as e:
        try:
            from jobs.models import KeywordJob
            if await KeywordJob.objects.filter(id=keyword_job_id).aexists():
                kj.status = 'failed'
                kj.status_message = f'Fatal Error: {str(e)}'
                await kj.asave()
        except:
            pass
        log.error("pipeline.fatal", error=str(e))
