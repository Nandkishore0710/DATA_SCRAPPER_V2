import concurrent.futures
import asyncio
import structlog
from django.utils import timezone
from .models import BulkJob, KeywordJob

log = structlog.get_logger()

# 🛡️ DYNAMIC QUEUE (Allows multiple keyword jobs to run in parallel)
# Max 3 concurrent keywords with 4 sub-cells each for maximum stability
MAX_CONCURRENT_KEYWORDS = 3
executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_KEYWORDS)

def run_keyword_job(keyword_job_id: int):
    """Runs one keyword pipeline in its own event loop."""
    from scraper.pipeline import run_keyword_pipeline

    import traceback
    import os
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"  # Allow DB access from async thread
    log.info("thread.executing", id=keyword_job_id)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_keyword_pipeline(keyword_job_id))
    except Exception as e:
        log.error("thread.failed", keyword_job_id=keyword_job_id, error=str(e), stack=traceback.format_exc())
    finally:
        loop.close()

def start_bulk_job(bulk_job_id: int):
    """
    Triggers concurrent execution of keyword segments.
    """
    try:
        bulk_job = BulkJob.objects.prefetch_related('keyword_jobs').get(id=bulk_job_id)
        bulk_job.status = 'running'
        bulk_job.status_message = f'Analyzing {bulk_job.keyword_jobs.count()} keywords in parallel queue...'
        bulk_job.save()

        futures = []
        for kj in bulk_job.keyword_jobs.all():
            future = executor.submit(run_keyword_job, kj.id)
            futures.append(future)
            log.info("thread.queued", keyword=kj.keyword)

        # Monitor and finalize in a separate control thread
        def monitor_batch():
            concurrent.futures.wait(futures)
            try:
                bulk_job.refresh_from_db()
                bulk_job.status = 'completed'
                bulk_job.status_message = f'Batch finished. Results analyzed.'
                bulk_job.completed_at = timezone.now()
                bulk_job.save()
                log.info("bulk.completed", bulk_job_id=bulk_job_id)
            except (BulkJob.DoesNotExist, Exception) as e:
                log.warning("bulk.monitor_stopped", bulk_job_id=bulk_job_id, reason=str(e))

        import threading
        threading.Thread(target=monitor_batch, daemon=True).start()
        
    except Exception as e:
        log.error("tasks.start_bulk_failed", error=str(e))
