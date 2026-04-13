# scratch/verify_scraper.py
import os
import django
import asyncio
import structlog
import sys

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from jobs.models import BulkJob, KeywordJob, Place
from django.contrib.auth.models import User
from scraper.pipeline import run_keyword_pipeline

log = structlog.get_logger()

async def verify():
    print("--- 🏁 Standalone Verification Started ---")
    sys.stdout.flush()
    
    # 1. Get or create a test user
    user, _ = await User.objects.aget_or_create(username='testadmin', email='test@example.com')
    
    # 🎯 CACHE CLEAR: Ensure we get a fresh, accurate boundary for this test
    from jobs.models import LocationCache
    await LocationCache.objects.filter(query__icontains="Mumbai").adelete()
    
    # 2. Setup Test Job (Mumbai, India)
    location = "Mumbai, India"
    keyword = "Coffee Shops"
    
    bj = await BulkJob.objects.acreate(
        user=user,
        location=location,
        search_type='city',
        grid_size=1, # Small grid for fast test
        status='pending'
    )
    
    kj = await KeywordJob.objects.acreate(
        bulk_job=bj,
        keyword=keyword,
        status='pending'
    )
    
    print(f"🚀 Job Created: '{keyword}' in '{location}' (ID: {kj.id})")
    sys.stdout.flush()
    
    # 3. Execute Pipeline
    try:
        await run_keyword_pipeline(kj.id)
    except Exception as e:
        print(f"❌ Pipeline Failed: {str(e)}")
        sys.stdout.flush()
        return

    # 4. Analyze Results
    await kj.arefresh_from_db()
    places_count = await Place.objects.filter(keyword_job=kj).all().acount()
    
    print(f"\n✅ Search Finished! Status: {kj.status}")
    print(f"   Total leads captured: {places_count}")
    sys.stdout.flush()
    
    if places_count > 0:
        print("\n--- 📍 SAMPLE DATA (Last 3 leads) ---")
        async for p in Place.objects.filter(keyword_job=kj).order_by('-id')[:3]:
            print(f"🏢 {p.name}")
            print(f"   📞 Phone: {p.phone or 'N/A'}")
            print(f"   🌐 Web: {p.website or 'N/A'}")
            print(f"   ⭐ Rating: {p.rating or 'N/A'}")
            print(f"   🏠 Address: {p.street or 'N/A'}")
            print("-" * 20)
        sys.stdout.flush()
    else:
        print("⚠️ No leads were captured. Check scraper logs.")
        sys.stdout.flush()

if __name__ == "__main__":
    asyncio.run(verify())
