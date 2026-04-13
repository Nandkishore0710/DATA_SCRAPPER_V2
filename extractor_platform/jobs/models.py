# jobs/models.py
from django.db import models
from django.contrib.auth.models import User


class BulkJob(models.Model):
    """
    One bulk job = multiple keywords, one location.
    Parent that holds everything together.
    """
    STATUS = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    EXECUTION_MODES = [
        ('direct', 'Direct Connection'),
        ('proxy', 'Proxy Active'),
    ]

    SEARCH_TYPES = [
        ('city', 'City Search'),
        ('state_country', 'State/Country Search'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='bulk_jobs'
    )
    location = models.CharField(max_length=500)
    grid_size = models.IntegerField(default=8)
    search_type = models.CharField(
        max_length=20, choices=SEARCH_TYPES, default='city'
    )
    strategy = models.CharField(
        max_length=50, 
        choices=[
            ('fast', 'Fast (144 cells)'),
            ('detailed', 'Detailed (225 cells)'),
            ('deep', 'Deep (400 cells)'),
            ('ultra', 'Ultra (625 cells)'),
            ('geolocation', 'Geolocation'),
        ],
        default='fast'
    )
    status = models.CharField(
        max_length=20, choices=STATUS, default='pending'
    )
    execution_mode = models.CharField(
        max_length=20, choices=EXECUTION_MODES, default='direct'
    )
    status_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"BulkJob({self.id}) in {self.location} — {self.status}"

    @property
    def total_extracted(self):
        return sum(j.total_extracted for j in self.keyword_jobs.all())

    @property
    def all_complete(self):
        jobs = self.keyword_jobs.all()
        return jobs.exists() and all(
            j.status in ('completed', 'failed') for j in jobs
        )


class KeywordJob(models.Model):
    """
    One keyword inside a BulkJob.
    Each gets its own results, own status, own CSV.
    """
    STATUS = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    bulk_job = models.ForeignKey(
        BulkJob, on_delete=models.CASCADE, related_name='keyword_jobs'
    )
    keyword = models.CharField(max_length=500)
    status = models.CharField(
        max_length=30, choices=STATUS, default='pending'
    )
    status_message = models.CharField(max_length=500, blank=True)
    error_message = models.TextField(blank=True)

    total_cells = models.IntegerField(default=0)
    cells_done = models.IntegerField(default=0)
    total_extracted = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"KeywordJob({self.id}) '{self.keyword}' — {self.status}"

    @property
    def progress_percent(self):
        if self.total_cells == 0:
            return 0
        return int((self.cells_done / self.total_cells) * 100)


class Place(models.Model):
    """One extracted business. Belongs to a KeywordJob."""
    keyword_job = models.ForeignKey(
        KeywordJob, on_delete=models.CASCADE, related_name='places'
    )

    place_id = models.CharField(max_length=500, blank=True)
    name = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=300, blank=True)
    street = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=200, blank=True)
    state = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=100, blank=True)
    website = models.URLField(max_length=2000, blank=True)
    rating = models.CharField(max_length=20, blank=True)
    review_count = models.CharField(max_length=50, blank=True)
    maps_url = models.URLField(max_length=2000, blank=True)
    latitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=13, decimal_places=8, null=True, blank=True)
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['keyword_job', 'place_id']

    def __str__(self):
        return self.name


class Proxy(models.Model):
    """Proxy storage for management via Admin Panel."""
    PROTOCOL_CHOICES = [
        ('http', 'HTTP'),
        ('socks4', 'SOCKS4'),
        ('socks5', 'SOCKS5'),
    ]

    url = models.CharField(max_length=500, unique=True)
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default='http')
    provider = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    
    last_checked = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=50, blank=True) # e.g. "working", "failed", "slow"
    avg_response_ms = models.IntegerField(default=0)
    
    usage_count = models.IntegerField(default=0)
    success_rate = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} ({self.url})"

    class Meta:
        verbose_name_plural = "Proxies"


class ProxySetting(models.Model):
    """
    Version 1.1 Single Active Proxy Setting.
    Stores the global proxy used by Playwright.
    """
    key = models.CharField(max_length=50, default='active_proxy', unique=True)
    value = models.CharField(max_length=500, help_text="http://user:pass@host:port")
    is_active = models.BooleanField(default=True)
    
    # Metadata for the Admin UI
    tested_at = models.DateTimeField(null=True, blank=True)
    is_working = models.BooleanField(default=False)
    response_ms = models.IntegerField(default=0)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    last_location = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Proxy: {self.value}"


class Package(models.Model):
    """Platform subscription tiers with resource limits."""
    name = models.CharField(max_length=100)
    price = models.CharField(max_length=50, help_text="e.g. $49/mo")
    lead_limit = models.IntegerField(default=2000, help_text="Monthly leads")
    search_limit = models.IntegerField(default=5, help_text="Number of searches allowed")
    grid_cell_limit = models.IntegerField(default=144, help_text="Max grid cells per search")
    grid_strategies = models.CharField(max_length=200, default="fast,detailed", help_text="Allowed: fast, detailed, deep, ultra (comma separated)")
    allowed_search_types = models.CharField(max_length=200, default="city", help_text="Allowed: city, state_country (comma separated)")
    features = models.TextField(blank=True, help_text="Comma-separated: Real-time scan, API access, etc.")
    description = models.TextField(blank=True)
    tier_badge = models.CharField(max_length=50, default="Starter", help_text="e.g. Popular, Best Value, etc.")
    is_featured = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def grid_strategies_list(self):
        if not self.grid_strategies: return []
        return [s.strip() for s in self.grid_strategies.split(',') if s.strip()]

    @property
    def allowed_search_types_list(self):
        if not self.allowed_search_types: return []
        return [t.strip() for t in self.allowed_search_types.split(',') if t.strip()]

    @property
    def features_list(self):
        if not self.features: return []
        return [f.strip() for f in self.features.split(',') if f.strip()]

class ServerPressure(models.Model):
    """Log entry for server load analysis."""
    timestamp = models.DateTimeField(auto_now_add=True)
    active_jobs = models.IntegerField(default=0)
    cpu_load = models.IntegerField(default=0) # We might still want to log it internally for pressure logic
    
    def __str__(self):
        return f"Pressure @ {self.timestamp}: {self.active_jobs} jobs"

class SearchedCell(models.Model):
    """Tracks which grid cells have already been searched to prevent double-dipping."""
    keyword_job = models.ForeignKey(KeywordJob, on_delete=models.CASCADE, related_name='searched_cells')
    cell_index = models.IntegerField()
    status = models.CharField(max_length=20, default='completed')
    found_count = models.IntegerField(default=0)
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['keyword_job', 'cell_index']


class LocationCache(models.Model):
    """Persistent storage for Nominatim boundary lookups to avoid rate limiting."""
    query = models.CharField(max_length=500, unique=True)
    display_name = models.CharField(max_length=1000)
    min_lat = models.FloatField()
    max_lat = models.FloatField()
    min_lng = models.FloatField()
    max_lng = models.FloatField()
    center_lat = models.FloatField()
    center_lng = models.FloatField()
    radius_meters = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cache: {self.query}"


class ScraperCache(models.Model):
    """Persistent storage for individual cell results (replaces file-based cache)."""
    # Using a composite key logic via indexes
    keyword = models.CharField(max_length=500)
    location = models.CharField(max_length=500)
    cell_index = models.IntegerField()
    
    results_json = models.JSONField() # Persistent storage of the results list
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['keyword', 'location', 'cell_index']),
        ]
        unique_together = ['keyword', 'location', 'cell_index']
