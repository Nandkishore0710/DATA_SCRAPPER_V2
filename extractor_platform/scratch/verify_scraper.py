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
    
    # 🎯 CACHE CLEAR: Ensure we get a fresh, accurate boundary and results for this test
    from jobs.models import LocationCache, ScraperCache
    await LocationCache.objects.filter(query__icontains="Bhilwara").adelete()
    await ScraperCache.objects.filter(location__icontains="Bhilwara", keyword__icontains="Gym").adelete()
    
    # 2. Setup Test Job (Bhilwara City)
    location = "Bhilwara city"
    keyword = "Gym"
    
    bj = await BulkJob.objects.acreate(
        user=user,
        location=location,
        search_type='city',
        grid_size=3, # 3x3 Grid (9 cells) ensures we hit the actual city area
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
    places_count = await Place.objects.filter(keyword_job=kj).acount()
    with_phone = await Place.objects.filter(keyword_job=kj).exclude(phone='').acount()
    with_web = await Place.objects.filter(keyword_job=kj).exclude(website='').acount()
    
    print(f"\n✅ Search Finished! Status: {kj.status}")
    print(f"   Total leads captured: {places_count}")
    print(f"   Leads with Phone: {with_phone}")
    print(f"   Leads with Website: {with_web}")
    sys.stdout.flush()
    
    if places_count > 0:
        print("\n--- 📍 SAMPLE DATA (Leads with details) ---")
        # Try to find leads that actually have data to show off the precision logic
        sample_qs = Place.objects.filter(keyword_job=kj).exclude(phone='').order_by('-id')[:3]
        if not await sample_qs.aexists():
            sample_qs = Place.objects.filter(keyword_job=kj).order_by('-id')[:3]
            
        async for p in sample_qs:
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
