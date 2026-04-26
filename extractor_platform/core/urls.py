# core/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
import jobs.admin_views
import jobs.views

urlpatterns = [
    path('', jobs.views.home, name='home'),
    
    # Stealth Administrative Hub (Access restricted to authorized operatives)
    path('omega-hq/gateway/', jobs.admin_views.admin_hub_login, name='admin_hub_login'),
    path('omega-hq/exit/', jobs.admin_views.admin_hub_logout, name='admin_hub_logout'),
    path('omega-hq/dashboard/', jobs.admin_views.admin_dashboard, name='admin_dashboard'),
    path('omega-hq/live/', jobs.admin_views.live_monitor, name='live_monitor'),
    path('omega-hq/proxy/', jobs.admin_views.proxy_settings, name='proxy_settings'),
    path('omega-hq/proxy/test/', jobs.admin_views.test_proxy_ajax, name='test_proxy_ajax'),
    path('omega-hq/users/', jobs.admin_views.user_management, name='user_management'),
    path('omega-hq/users/create/', jobs.admin_views.create_user_admin, name='create_user_admin'),
    path('omega-hq/users/toggle/<int:user_id>/', jobs.admin_views.toggle_user_status, name='toggle_user_status'),
    path('omega-hq/users/reset/<int:user_id>/', jobs.admin_views.reset_password, name='reset_password'),
    path('omega-hq/users/update-credits/<int:user_id>/', jobs.admin_views.update_credits, name='update_credits'),
    path('omega-hq/users/update-details/<int:user_id>/', jobs.admin_views.update_user_details, name='update_user_details'),
    path('omega-hq/users/delete/<int:user_id>/', jobs.admin_views.delete_user, name='delete_user'),
    path('omega-hq/users/activity/<int:user_id>/', jobs.admin_views.user_activity, name='user_activity'),
    path('omega-hq/users/assign-package/<int:user_id>/', jobs.admin_views.assign_package, name='assign_package'),
    path('omega-hq/users/subscription/delete/<int:user_id>/', jobs.admin_views.remove_subscription, name='remove_subscription'),
    path('omega-hq/keyword/<int:keyword_job_id>/results/', jobs.admin_views.view_keyword_results, name='admin_keyword_results'),
    path('omega-hq/packages/', jobs.admin_views.package_management, name='package_management'),
    path('omega-hq/payments/', jobs.admin_views.payment_management, name='payment_management'),
    path('omega-hq/payments/settings/', jobs.admin_views.payment_settings, name='payment_settings'),

    path('admin/login/', jobs.admin_views.admin_hub_login),
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view()),
    path('api/token/refresh/', TokenRefreshView.as_view()),
    path('api/', include('jobs.urls')),
    path('api/auth/', include('accounts.urls')),
    path('api/billing/', include('billing.urls')),
]
