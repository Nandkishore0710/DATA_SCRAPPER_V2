# jobs/admin_views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from .models import BulkJob, KeywordJob, Place, ProxySetting, Package, ServerPressure
from django.db.models import Sum, Count, Q
from django.contrib.auth.models import User
from django.contrib.auth import login
from accounts.models import UserProfile
from billing.models import Transaction, RazorpayOrder, PayPalOrder, PaymentGatewaySettings
import psutil
import os
import json
import random
import threading
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from scraper.proxy_logic import test_proxy_connection
from django.core.mail import send_mail, get_connection
from functools import wraps
from django.conf import settings
from django.core.cache import cache
from decouple import config

# --- 1. Security Infrastructure ---

def admin_hub_required(view_func):
    """Decorator to ensure OTP verification or staff login has occurred."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            if not request.session.get('admin_hub_verified'):
                return redirect('admin_hub_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def admin_hub_login(request):
    """Single-stage login with Master Password bypass."""
    error = None
    if request.method == 'POST':
        pwd_input = request.POST.get('password', '').strip()
        if pwd_input == settings.ADMIN_HUB_PASSWORD:
            # Auto-login as superuser to bypass generic Django login
            target_user = User.objects.filter(is_superuser=True).first()
            if target_user:
                login(request, target_user)
            request.session['admin_hub_verified'] = True
            return redirect('admin_dashboard')
        else:
            error = "Invalid Master Password."
    
    return render(request, 'admin/intel_login.html', {'step': 2, 'error': error})

def admin_hub_logout(request):
    request.session.flush()
    return redirect('admin_hub_login')

# --- 2. Dashboard & Monitoring ---

@staff_member_required
@admin_hub_required
def admin_dashboard(request):
    # sync ghost jobs
    try:
        stale = timezone.now() - timezone.timedelta(hours=2)
        KeywordJob.objects.filter(status='running', updated_at__lt=stale).update(status='failed', status_message='Ghost Sync Timeout')
    except Exception:
        pass
    
    stats = cache.get('admin_dashboard_stats')
    if not stats:
        stats = {
            'users': User.objects.count(),
            'searches': BulkJob.objects.count(),
            'results': KeywordJob.objects.aggregate(Sum('total_extracted'))['total_extracted__sum'] or 0,
            'active_ops': KeywordJob.objects.filter(status='running').count(),
        }
        cache.set('admin_dashboard_stats', stats, 15)

    pressure = ServerPressure.objects.order_by('-timestamp')[:20]
    return render(request, 'admin/dashboard.html', {
        'metrics': stats,
        'pressure': {'values': json.dumps([p.active_jobs for p in reversed(pressure)]), 'labels': json.dumps([p.timestamp.strftime('%H:%M') for p in reversed(pressure)])},
        'now': timezone.now()
    })

@staff_member_required
@admin_hub_required
def live_monitor(request):
    active_jobs = BulkJob.objects.filter(status='running').prefetch_related('keyword_jobs')
    return render(request, 'admin/live_monitor.html', {'active_jobs': active_jobs, 'now': timezone.now()})

# --- 3. Proxy Management ---

@staff_member_required
@admin_hub_required
def proxy_settings(request):
    setting, _ = ProxySetting.objects.get_or_create(key='active_proxy')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save':
            setting.value = request.POST.get('proxy_url', '').strip()
            setting.is_active = 'is_active' in request.POST
            setting.save()
        elif action == 'remove':
            setting.value = ''; setting.is_active = False; setting.save()
    return render(request, 'admin/proxy_settings.html', {'setting': setting})

@staff_member_required
@admin_hub_required
@require_POST
async def test_proxy_ajax(request):
    data = json.loads(request.body)
    url = data.get('url', '').strip()
    if not url: return JsonResponse({'success': False, 'error': 'No URL'})
    res = await test_proxy_connection(url)
    return JsonResponse(res)

# --- 4. User Management ---

@staff_member_required
@admin_hub_required
def user_management(request):
    from django.core.paginator import Paginator
    users = User.objects.all().select_related('profile').order_by('-date_joined')
    paginator = Paginator(users, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    for u in page_obj:
        u.total_jobs = BulkJob.objects.filter(user=u).count()
        u.total_extracted = KeywordJob.objects.filter(bulk_job__user=u).aggregate(Sum('total_extracted'))['total_extracted__sum'] or 0
    return render(request, 'admin/user_management.html', {'page_obj': page_obj, 'packages': Package.objects.all()})

@staff_member_required
@admin_hub_required
def create_user_admin(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            # Create the Django user entity.
            user = User.objects.create_user(username=data['username'], email=data['email'], password=data['password'])
            
            # The UserProfile is often auto-created via a post_save signal. 
            # We must use get_or_create to avoid OneToOne UNIQUE constraint violations, then safely apply default searches.
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.searches_left = 5
            profile.save()
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'POST required'}, status=400)

@staff_member_required
@admin_hub_required
@require_POST
def toggle_user_status(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if not user.is_superuser: user.is_active = not user.is_active; user.save()
    return JsonResponse({'success': True, 'is_active': user.is_active})

@staff_member_required
@admin_hub_required
@require_POST
def reset_password(request, user_id):
    user = get_object_or_404(User, id=user_id)
    new_pw = json.loads(request.body).get('password')
    if new_pw:
        user.set_password(new_pw)
        user.save()
        return JsonResponse({'success': True, 'msg': 'Password updated successfully.'})
    return JsonResponse({'error': 'No PW provided'}, status=400)

@staff_member_required
@admin_hub_required
@require_POST
def update_credits(request, user_id):
    user = get_object_or_404(User, id=user_id)
    credits = json.loads(request.body).get('credits')
    if credits is not None:
        p, _ = UserProfile.objects.get_or_create(user=user)
        p.searches_left = int(credits); p.save()
        return JsonResponse({'success': True, 'msg': f'Credits updated to {credits}.'})
    return JsonResponse({'error': 'No credits'}, status=400)

@staff_member_required
@admin_hub_required
@require_POST
def update_user_details(request, user_id):
    user = get_object_or_404(User, id=user_id)
    data = json.loads(request.body)
    user.username = data.get('username', user.username)
    user.email = data.get('email', user.email)
    user.save()
    p, _ = UserProfile.objects.get_or_create(user=user)
    p.phone = data.get('phone', p.phone); p.save()
    return JsonResponse({'success': True, 'msg': 'User details updated.'})

@staff_member_required
@admin_hub_required
def user_activity(request, user_id):
    u = get_object_or_404(User, id=user_id)
    jobs = BulkJob.objects.filter(user=u).order_by('-created_at')
    return render(request, 'admin/user_activity.html', {'target_user': u, 'jobs': jobs, 'profile': u.profile, 'packages': Package.objects.all()})

@staff_member_required
@admin_hub_required
@require_POST
def assign_package(request, user_id):
    u = get_object_or_404(User, id=user_id)
    pkg_id = json.loads(request.body).get('package_id')
    p, _ = UserProfile.objects.get_or_create(user=u)
    package = get_object_or_404(Package, id=pkg_id) if pkg_id else None
    p.package = package
    if package:
        p.searches_left = package.search_limit
    p.save()
    return JsonResponse({'success': True, 'msg': f'Package applied. Credits set to {p.searches_left}.'})

@staff_member_required
@admin_hub_required
@require_POST
def remove_subscription(request, user_id):
    u = get_object_or_404(User, id=user_id)
    p, _ = UserProfile.objects.get_or_create(user=u)
    p.package = None
    p.searches_left = 5
    p.save()
    return JsonResponse({'success': True, 'msg': 'Subscription removed. Credits reset to 5.'})

@staff_member_required
@admin_hub_required
@require_POST
def delete_user(request, user_id):
    u = get_object_or_404(User, id=user_id)
    if not u.is_superuser: u.delete(); return JsonResponse({'success': True})
    return JsonResponse({'error': 'Cannot delete superuser'}, status=403)

# --- 5. Package & Billing ---

@staff_member_required
@admin_hub_required
def package_management(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        pid = request.POST.get('pkg_id')
        
        if action == 'delete' and pid:
            pkg = get_object_or_404(Package, id=pid)
            pkg.delete()
            return redirect('package_management')
            
        pkg = get_object_or_404(Package, id=pid) if pid else Package()
        pkg.name = request.POST.get('name')
        pkg.tier_badge = request.POST.get('tier_badge')
        pkg.price = request.POST.get('price')
        pkg.lead_limit = request.POST.get('lead_limit', 0)
        pkg.search_limit = request.POST.get('search_limit', 0)
        pkg.grid_cell_limit = request.POST.get('grid_cell_limit', 144)
        pkg.grid_strategies = request.POST.get('grid_strategies', 'fast')
        pkg.allowed_search_types = request.POST.get('allowed_search_types', 'city')
        pkg.features = request.POST.get('features', '')
        pkg.is_featured = 'is_featured' in request.POST
        pkg.save()
        return redirect('package_management')
    return render(request, 'admin/package_management.html', {'packages': Package.objects.all()})

@staff_member_required
@admin_hub_required
def view_keyword_results(request, keyword_job_id):
    kj = get_object_or_404(KeywordJob, id=keyword_job_id)
    return render(request, 'admin/keyword_results.html', {'kj': kj, 'places': kj.places.all()})

@staff_member_required
@admin_hub_required
def payment_management(request):
    return render(request, 'admin/payment_management.html', {'transactions': Transaction.objects.all().order_by('-created_at')[:50]})

@staff_member_required
@admin_hub_required
def payment_settings(request):
    obj, _ = PaymentGatewaySettings.objects.get_or_create(is_active=True)
    if request.method == 'POST':
        obj.razorpay_key_id = request.POST.get('razorpay_key_id', '')
        obj.razorpay_key_secret = request.POST.get('razorpay_key_secret', '')
        obj.save()
    return render(request, 'admin/payment_settings.html', {'settings': obj})
