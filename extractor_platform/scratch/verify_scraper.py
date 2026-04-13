# scratch/verify_scraper.py
import os
import django
import asyncio
import structlog

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from jobs.models import BulkJob, KeywordJob, Place
from django.contrib.auth.models import User
from scraper.pipeline import run_keyword_pipeline

log = structlog.get_logger()

async def verify():
    # 1. Get or create a test user
    user, _ = await User.objects.aget_or_create(username='testadmin', email='test@example.com')
    
    # 2. Setup Test Job (Coffee Shops in Mumbai)
    location = "Mumbai"
    keyword = "Coffee Shops"
    
    bj = await BulkJob.objects.acreate(
        user=user,
        location=location,
        search_type='city',
        grid_size=1, # Very small grid for fast test
        status='pending'
    )
    
    kj = await KeywordJob.objects.acreate(
        bulk_job=bj,
        keyword=keyword,
        status='pending'
    )
    
    print(f"🚀 Starting Verification Search: '{keyword}' in '{location}'")
    print(f"   BulkJob ID: {bj.id}, KeywordJob ID: {kj.id}")
    
    # 3. Execute Pipeline
    try:
        await run_keyword_pipeline(kj.id)
    except Exception as e:
        print(f"❌ Pipeline Failed: {str(e)}")
        return

    # 4. Analyze Results
    await kj.arefresh_from_db()
    places = await Place.objects.filter(keyword_job=kj).all().acount()
    
    print(f"\n✅ Search Finished!")
    print(f"   Status: {kj.status}")
    print(f"   Message: {kj.status_message}")
    print(f"   Total leads captured: {places}")
    
    if places > 0:
        print("\n--- SAMPLE DATA (Last 5 leads) ---")
        async for p in Place.objects.filter(keyword_job=kj).order_by('-id')[:5]:
            print(f"📍 {p.name}")
            print(f"   📞 Phone: {p.phone or 'MISSING'}")
            print(f"   🌐 Web: {p.website or 'MISSING'}")
            print(f"   ⭐ Rating: {p.rating} ({p.review_count} reviews)")
            print(f"   🏠 Address: {p.street}")
            print("-" * 30)
    else:
        print("⚠️ No leads were captured. Check logs for blocks or empty results.")

if __name__ == "__main__":
    asyncio.run(verify())
