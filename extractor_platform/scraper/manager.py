# scraper/manager.py
import asyncio
import structlog
from playwright.async_api import async_playwright

log = structlog.get_logger()

class BrowserManager:
    """
    SINGLETON Browser Manager
    Maintains a single persistent browser instance per server for extreme CPU efficiency.
    Throttles concurrency to keep server load under 30%.
    """
    _instance = None
    _browser = None
    _playwright = None
    _lock = asyncio.Lock()
    _semaphore = asyncio.Semaphore(4) # 🛡️ SAFETY LOCK: Global max 4 browsers across ALL users to prevent CPU meltdown

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BrowserManager, cls).__new__(cls)
        return cls._instance

    async def get_browser(self):
        async with self._lock:
            if self._browser is None:
                log.info("browser.launching_singleton")
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-gpu',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--js-flags="--max-old-space-size=512"',
                        '--disable-canvas-aa',
                        '--disable-2d-canvas-clip-aa',
                        '--disable-gl-drawing-for-tests',
                        '--disable-single-click-autofill',
                        '--disable-infobars',
                        '--no-pings',
                        '--mute-audio',
                        '--disable-background-networking',
                        '--disable-background-timer-throttling',
                        '--disable-backgrounding-occluded-windows',
                        '--disable-breakpad',
                        '--disable-client-side-phishing-detection',
                        '--disable-component-update',
                        '--disable-default-apps',
                        '--disable-extensions',
                        '--disable-hang-monitor',
                        '--disable-ipc-flooding-protection',
                        '--disable-notifications',
                        '--disable-prompt-on-repost',
                        '--disable-renderer-backgrounding',
                        '--disable-sync',
                        '--force-color-profile=srgb',
                        '--metrics-recording-only',
                        '--no-first-run',
                        '--password-store=basic',
                        '--use-mock-keychain',
                    ]
                )
            return self._browser

    async def new_context(self, **kwargs):
        browser = await self.get_browser()
        return await browser.new_context(**kwargs)

    async def acquire_page(self, context):
        await self._semaphore.acquire()
        return await context.new_page()

    def release_page(self):
        self._semaphore.release()

    async def teardown(self):
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

# Global instance
browser_manager = BrowserManager()
