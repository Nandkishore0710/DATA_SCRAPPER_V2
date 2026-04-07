# jobs/views.py
import csv
from django.http import HttpResponse
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import render
from .models import BulkJob, KeywordJob, Place, Package
from .tasks import start_bulk_job

def home(request):
    """The master console view."""
    # Enforce specific order: Starter -> Premium Pro -> Professional Pro
    all_packages = list(Package.objects.all())
    order = ["Starter", "Premium Pro", "Professional Pro"]
    
    # Sort packages based on the predefined order list
    packages = sorted(
        all_packages, 
        key=lambda p: order.index(p.name) if p.name in order else 999
    )
    
    return render(request, 'index.html', {'packages': packages})


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '')
        email = request.data.get('email', '').strip()

        if not username or not password:
            return Response(
                {'error': 'Username and password required'},
                status=400
            )
        if User.objects.filter(username=username).exists():
            return Response(
                {'error': 'Username taken'},
                status=400
            )

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'username': user.username,
        }, status=201)


class StartBulkJobView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Input:
        {
            "location": "Jaipur",
            "grid_size": 8,
            "keywords": ["IT Company", "Tech", "Software", "Web Development"]
        }
        """
        location = request.data.get('location', '').strip()
        keywords = request.data.get('keywords', [])
        strategy = request.data.get('strategy', 'detailed').lower()

        # Map strategy to grid size (Pillar 1 — Grid Density Fix)
        strategy_map = {
            'fast': 12,         # 144 cells
            'detailed': 15,     # 225 cells
            'deep': 20,         # 400 cells
            'ultra': 25,        # 625 cells (Massive Coverage)
            'geolocation': 2,   # 4 cells
        }
        
        # Priority: 1. Request Grid Size, 2. Strategy Map
        grid_size = request.data.get('grid_size')
        if grid_size:
            try:
                grid_size = int(grid_size)
            except (ValueError, TypeError):
                grid_size = strategy_map.get(strategy, 12)
        else:
            grid_size = strategy_map.get(strategy, 12)

        # Validation
        if not location:
            return Response(
                {'error': 'location is required'},
                status=400
            )

        # Sanitation Helper (no html, no scripts, no weird characters)
        import re
        from django.utils.html import strip_tags
        def sanitize(text):
            if not isinstance(text, str): return ""
            # 1. Remove HTML tags
            text = strip_tags(text)
            # 2. Keep word characters (including international letters), spaces, hyphens and ampersands
            # (Allows "Café", "München", "AT&T" etc but blocks <scripts>, html entities)
            text = re.sub(r'[^\w\s\-\&]', '', text, flags=re.UNICODE)
            return text.strip()

        location = sanitize(location)
        if not location:
            return Response({'error': 'invalid location input'}, status=400)

        # 🚀 Search Type (City vs State/Country)
        search_type = request.data.get('search_type', 'city').lower()
        if search_type not in ['city', 'state_country']:
            search_type = 'city'

        if not keywords or not isinstance(keywords, list):
            return Response(
                {'error': 'keywords must be a non-empty list'},
                status=400
            )

        # Force single keyword for state_country
        if search_type == 'state_country' and len(keywords) > 1:
            keywords = [keywords[0]]

        if len(keywords) > 20: 
            return Response(
                {'error': 'Max 20 keywords per job'},
                status=400
            )

        # Clean and Sanitize keywords
        clean_keywords = []
        for k in keywords:
            sanitized = sanitize(k)
            if sanitized:
                clean_keywords.append(sanitized)
        
        keywords = clean_keywords
        if not keywords:
            return Response({'error': 'no valid keywords provided'}, status=400)

        # --- Package Enforcement ---
        try:
            from accounts.models import UserProfile
            profile = UserProfile.objects.select_related('package').get(user=request.user)
            if profile.package:
                allowed_strategies = [s.strip() for s in profile.package.grid_strategies.split(',') if s.strip()]
                allowed_search_types = [t.strip() for t in profile.package.allowed_search_types.split(',') if t.strip()]
            else:
                allowed_strategies = ['fast', 'detailed']
                allowed_search_types = ['city']
        except Exception:
            allowed_strategies = ['fast', 'detailed']
            allowed_search_types = ['city']
        
        # Check Strategy
        if strategy not in allowed_strategies:
            return Response(
                {'error': f'Your current plan does not include the "{strategy}" grid. Please upgrade!'},
                status=403
            )
            
        # Check Search Type
        if search_type not in allowed_search_types:
            return Response(
                {'error': f'Your plan does not include the "{search_type}" feature. Please upgrade!'},
                status=403
            )

        grid_size = max(1, min(grid_size, 30))

        # Create bulk job
        bulk_job = BulkJob.objects.create(
            user=request.user,
            location=location,
            grid_size=grid_size,
            strategy=strategy,
            search_type=search_type,
        )

        # Create one KeywordJob per keyword
        for keyword in keywords:
            KeywordJob.objects.create(
                bulk_job=bulk_job,
                keyword=keyword,
            )

        # Fire all keyword jobs in parallel background threads
        import threading
        threading.Thread(
            target=start_bulk_job,
            args=(bulk_job.id,),
            daemon=True
        ).start()

        return Response({
            'bulk_job_id': bulk_job.id,
            'location': location,
            'keywords': keywords,
            'strategy': strategy,
            'grid_size': grid_size,
            'max_possible_per_keyword': grid_size * grid_size * 400,
            'status': 'running',
        }, status=201)


class BulkJobStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, bulk_job_id):
        try:
            bulk_job = BulkJob.objects.prefetch_related(
                'keyword_jobs'
            ).get(id=bulk_job_id, user=request.user)
        except BulkJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

        keyword_statuses = []
        for kj in bulk_job.keyword_jobs.all():
            keyword_statuses.append({
                'keyword_job_id': kj.id,
                'keyword': kj.keyword,
                'status': kj.status,
                'status_message': kj.status_message,
                'progress_percent': kj.progress_percent,
                'cells_done': kj.cells_done,
                'total_cells': kj.total_cells,
                'total_extracted': kj.total_extracted,
                'completed_at': kj.completed_at,
            })

        return Response({
            'bulk_job_id': bulk_job.id,
            'location': bulk_job.location,
            'status': bulk_job.status,
            'status_message': bulk_job.status_message,
            'total_extracted': bulk_job.total_extracted,
            'keywords': keyword_statuses,
            'search_type': bulk_job.search_type,
            'execution_mode': bulk_job.execution_mode,
            'created_at': bulk_job.created_at,
            'completed_at': bulk_job.completed_at,
        })


class BulkJobListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        jobs = BulkJob.objects.filter(
            user=request.user
        ).prefetch_related('keyword_jobs').order_by('-created_at')[:20]

        return Response([{
            'bulk_job_id': j.id,
            'location': j.location,
            'status': j.status,
            'keywords': [{
                'keyword_job_id': kj.id,
                'keyword': kj.keyword,
                'status': kj.status,
                'total_cells': kj.total_cells,
                'cells_done': kj.cells_done,
                'status_message': kj.status_message,
            } for kj in j.keyword_jobs.all()],
            'total_extracted': j.total_extracted,
            'strategy': j.strategy,
            'search_type': j.search_type,
            'execution_mode': j.execution_mode,
            'created_at': j.created_at,
            'completed_at': j.completed_at,
        } for j in jobs])


class BulkJobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, bulk_job_id):
        try:
            bulk_job = BulkJob.objects.prefetch_related('keyword_jobs').get(id=bulk_job_id, user=request.user)
            return Response({
                'bulk_job_id': bulk_job.id,
                'location': bulk_job.location,
                'status': bulk_job.status,
                'total_extracted': bulk_job.total_extracted,
                'created_at': bulk_job.created_at,
            }, status=200)
        except BulkJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

    def delete(self, request, bulk_job_id):
        try:
            bulk_job = BulkJob.objects.get(id=bulk_job_id, user=request.user)
            bulk_job.delete()
            return Response({'status': 'deleted'}, status=200)
        except BulkJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)


class BulkJobCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, bulk_job_id):
        from django.utils import timezone
        try:
            bulk_job = BulkJob.objects.prefetch_related('keyword_jobs').get(id=bulk_job_id, user=request.user)
            if bulk_job.status not in ['pending', 'running']:
                return Response({'error': 'Job is already finished or cannot be cancelled'}, status=400)
            
            bulk_job.status = 'cancelled'
            bulk_job.status_message = 'Termination requested by user.'
            bulk_job.completed_at = timezone.now()
            bulk_job.save()
            
            # Cascading cancel to keywords
            bulk_job.keyword_jobs.all().update(status='cancelled', status_message='Protocol Terminated.', completed_at=timezone.now())
            
            return Response({'status': 'cancelled'}, status=200)
        except BulkJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)


class KeywordResultsView(APIView):
    """Get results for one specific keyword."""
    permission_classes = [IsAuthenticated]

    def get(self, request, keyword_job_id):
        try:
            kj = KeywordJob.objects.select_related(
                'bulk_job'
            ).get(
                id=keyword_job_id,
                bulk_job__user=request.user
            )
        except KeywordJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

        places = kj.places.all().values(
            'name', 'category', 'street', 'city',
            'state', 'phone', 'website', 'rating',
            'review_count', 'maps_url', 'latitude', 'longitude'
        )
        return Response({
            'keyword': kj.keyword,
            'location': kj.bulk_job.location,
            'total': kj.total_extracted,
            'results': list(places),
        })


class ExportKeywordCSVView(APIView):
    """Download CSV for one specific keyword."""
    permission_classes = [IsAuthenticated]

    def get(self, request, keyword_job_id):
        try:
            kj = KeywordJob.objects.select_related(
                'bulk_job'
            ).get(
                id=keyword_job_id,
                bulk_job__user=request.user
            )
        except KeywordJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

        filename = (
            f"{kj.keyword}_{kj.bulk_job.location}"
            .replace(' ', '_') + '.csv'
        )
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            f'attachment; filename="{filename}"'
        )

        # Write BOM for Excel/Windows compatibility
        response.write('\ufeff')

        fields = [
            'name', 'category', 'street', 'city', 'state',
            'phone', 'website', 'rating', 'review_count', 'maps_url'
        ]
        writer = csv.DictWriter(
            response, fieldnames=fields, extrasaction='ignore',
            quoting=csv.QUOTE_ALL
        )
        writer.writeheader()

        for place in kj.places.all():
            writer.writerow({
                f: getattr(place, f, '') for f in fields
            })

        return response


class BulkJobResultsView(APIView):
    """Get consolidated results for an entire BulkJob."""
    permission_classes = [IsAuthenticated]

    def get(self, request, bulk_job_id):
        try:
            bulk_job = BulkJob.objects.prefetch_related(
                'keyword_jobs__places'
            ).get(id=bulk_job_id, user=request.user)
        except BulkJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

        all_places = []
        for kj in bulk_job.keyword_jobs.all():
            places = kj.places.all().values(
                'name', 'category', 'street', 'city',
                'state', 'phone', 'website', 'rating',
                'review_count', 'maps_url', 'latitude', 'longitude'
            )
            # Add keyword info to each result so user knows which keyword it came from
            for p in places:
                p['source_keyword'] = kj.keyword
                # Fix Frontend Dashboard Aliases
                p['totalscore'] = p.get('rating') or ""
                p['reviewscount'] = p.get('review_count') or ""
                all_places.append(p)

        return Response({
            'bulk_job_id': bulk_job.id,
            'location': bulk_job.location,
            'total': len(all_places),
            'results': all_places,
        })


class ExportBulkCSVView(APIView):
    """Download combined CSV for an entire BulkJob."""
    permission_classes = [IsAuthenticated]

    def get(self, request, bulk_job_id):
        try:
            bulk_job = BulkJob.objects.prefetch_related(
                'keyword_jobs__places'
            ).get(id=bulk_job_id, user=request.user)
        except BulkJob.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

        filename = f"Bulk_Export_{bulk_job.location}_{bulk_job.id}.csv".replace(' ', '_')
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.write('\ufeff')

        fields = [
            'name', 'source_keyword', 'category', 'street', 'city', 'state',
            'phone', 'website', 'rating', 'review_count', 'maps_url'
        ]
        writer = csv.DictWriter(
            response, fieldnames=fields, extrasaction='ignore',
            quoting=csv.QUOTE_ALL
        )
        writer.writeheader()

        for kj in bulk_job.keyword_jobs.all():
            for place in kj.places.all():
                row = {f: getattr(place, f, '') for f in fields if f != 'source_keyword'}
                row['source_keyword'] = kj.keyword
                writer.writerow(row)

        return response
