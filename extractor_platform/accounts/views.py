import random
import json
from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from decouple import config
from twilio.rest import Client
import firebase_admin
from firebase_admin import credentials, auth
from django.core.mail import send_mail
from django.template.loader import render_to_string
from .models import UserProfile, UserOTP

# Initialize Firebase
try:
    if not firebase_admin._apps:
        # User will need to provide this file or we use a fallback if they have it in config
        cred_path = config('FIREBASE_SERVICE_ACCOUNT_PATH', default='firebase-adminsdk.json')
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"FIREBASE INITIALIZATION ERROR: {e}")

def get_tokens_for_user(user):
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp(request):
    """Sends OTP via Email or Twilio (SMS/WhatsApp)."""
    identifier = request.data.get('identifier', '').strip() or request.data.get('phone', '').strip()
    method = request.data.get('method', 'sms') # sms, whatsapp, email

    if not identifier:
        return Response({'error': 'Identity required'}, status=400)
    
    otp = str(random.randint(100000, 999999))
    
    # ✉️ EMAIL (SMTP) METHOD
    if '@' in identifier or method == 'email':
        from billing.models import PaymentGatewaySettings
        db_settings = PaymentGatewaySettings.objects.filter(is_active=True).first()
        
        # Determine credentials (DB overrides .env)
        host = db_settings.smtp_host if db_settings and db_settings.smtp_host else config('EMAIL_HOST', 'smtp.gmail.com')
        port = db_settings.smtp_port if db_settings else config('EMAIL_PORT', 587, cast=int)
        user = db_settings.smtp_user if db_settings and db_settings.smtp_user else config('EMAIL_HOST_USER', '')
        pwrd = db_settings.smtp_password if db_settings and db_settings.smtp_password else config('EMAIL_HOST_PASSWORD', '')
        use_tls = db_settings.smtp_use_tls if db_settings else config('EMAIL_USE_TLS', True, cast=bool)
        use_ssl = db_settings.smtp_use_ssl if db_settings else config('EMAIL_USE_SSL', False, cast=bool)

        UserOTP.objects.create(phone=identifier, otp=otp)
        try:
            from django.core.mail import get_connection
            # 🛡️ Attempt 1: Standard SMTP (Bypass Port 465)
            connection = get_connection(
                host=host, port=port, username=user, password=pwrd, use_tls=use_tls, use_ssl=use_ssl
            )
            html = render_to_string('emails/otp_verification.html', {'otp': otp})
            send_mail(f"Code: {otp}", f"Your code is {otp}", user, [identifier], html_message=html, connection=connection)
            return Response({'message': 'OTP sent via SMTP', 'identifier': identifier})
        except Exception as smtp_error:
            # 🚀 Attempt 2: API Rocket Bypass (Unblockable Port 443)
            resend_key = config('RESEND_API_KEY', default='')
            if resend_key:
                try:
                    import requests
                    resp = requests.post(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                        json={
                            "from": config('DEFAULT_FROM_EMAIL', 'onboarding@resend.dev'),
                            "to": identifier,
                            "subject": f"Verify Your Code: {otp}",
                            "html": html
                        },
                        timeout=10
                    )
                    if resp.status_code in [200, 201]:
                        return Response({'message': 'OTP sent via API Bypass', 'identifier': identifier})
                except Exception as api_error:
                    pass
            
            return Response({'error': f'All delivery methods failed. SMTP Error: {str(smtp_error)}'}, status=500)

    # 📱 TWILIO METHOD
    phone = identifier if identifier.startswith('+') else f"+91{identifier}"
    UserOTP.objects.create(phone=phone, otp=otp)
    
    sid, tok = config('TWILIO_ACCOUNT_SID', ''), config('TWILIO_AUTH_TOKEN', '')
    from_n = config('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')

    try:
        if sid and tok and tok != 'your_token':
            client = Client(sid, tok)
            if method == 'whatsapp' and from_n.startswith('whatsapp:'):
                client.messages.create(from_=from_n, body=f"Code: {otp}", to=f"whatsapp:{phone}")
            else:
                client.messages.create(from_=from_n.replace('whatsapp:', ''), body=f"Code: {otp}", to=phone)
    except Exception as e:
        if not config('DEBUG', False): return Response({'error': 'SMS error'}, status=500)
    
    return Response({'message': 'OTP process initiated', 'phone': phone})
@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    """Verifies OTP and determines if user needs to set a password or just login."""
    phone = request.data.get('phone', '').strip()
    otp = request.data.get('otp', '').strip()
    
    if not phone or not otp:
        return Response({'error': 'Phone and OTP are required'}, status=400)
    
    # Check OTP (valid for 10 minutes)
    valid_time = timezone.now() - timedelta(minutes=10)
    otp_record = UserOTP.objects.filter(
        phone=phone, 
        otp=otp, 
        is_used=False,
        created_at__gte=valid_time
    ).order_by('-created_at').first()
    
    if not otp_record:
        return Response({'error': 'Invalid or expired OTP'}, status=400)
    
    # Check if user exists
    user = User.objects.filter(username=phone).first()
    
    if user:
        # Existing user - return tokens but might require password later depending on UI flow
        # For now, let's say they just need to provide password to finish login
        return Response({
            'status': 'verified',
            'user_exists': True,
            'message': 'OTP verified. Please provide your password to login.'
        })
    else:
        # New user - must set password
        return Response({
            'status': 'verified',
            'user_exists': False,
            'message': 'OTP verified. Please set a password to create your account.'
        })

@api_view(['POST'])
@permission_classes([AllowAny])
def register_with_otp(request):
    """Final step: Create user or login using verified phone + password."""
    phone = request.data.get('phone', '').strip()
    otp = request.data.get('otp', '').strip()
    password = request.data.get('password', '')
    firebase_token = request.data.get('firebaseToken')
    
    if not all([phone, password]) or (not otp and not firebase_token):
        return Response({'error': 'Missing required fields'}, status=400)
    
    if firebase_token:
        # Verify via Firebase
        try:
            decoded_token = auth.verify_id_token(firebase_token)
            if decoded_token.get('phone_number') != phone:
                return Response({'error': 'Phone number mismatch with Firebase token'}, status=400)
        except Exception as e:
            return Response({'error': f'Firebase verification failed: {str(e)}'}, status=401)
    else:
        # Re-verify OTP to ensure security
        valid_time = timezone.now() - timedelta(minutes=15)
        otp_record = UserOTP.objects.filter(
            phone=phone, 
            otp=otp, 
            is_used=False,
            created_at__gte=valid_time
        ).order_by('-created_at').first()
        
        if not otp_record:
            return Response({'error': 'Verification session expired. Please start over.'}, status=400)
        
        # Mark OTP as used
        otp_record.is_used = True
        otp_record.save()
    
    user = User.objects.filter(username=phone).first()
    
    if user:
        # Login flow
        from django.contrib.auth import authenticate
        user = authenticate(username=phone, password=password)
        if not user:
            return Response({'error': 'Incorrect password'}, status=401)
    else:
        # Registration flow
        user = User.objects.create_user(username=phone, password=password)
        UserProfile.objects.create(user=user, phone=phone, is_verified=True)
    
    tokens = get_tokens_for_user(user)
    return Response({
        'access': tokens['access'],
        'refresh': tokens['refresh'],
        'username': phone,
        'message': 'Logged in successfully'
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def traditional_login(request):
    """Standard login using username and password. Supports login by phone as well."""
    input_identifier = request.data.get('username', '').strip()
    password = request.data.get('password', '')
    
    if not input_identifier or not password:
        return Response({'error': 'Username/Phone and password are required'}, status=400)
    
    from django.contrib.auth import authenticate
    
    # 1. Try directly with the input (could be username or phone as username)
    user = authenticate(username=input_identifier, password=password)
    
    # 2. If no direct match, check if input_identifier is a phone number in UserProfile
    if not user:
        # Standardize phone for lookup
        phone_lookup = input_identifier
        if not phone_lookup.startswith('+') and len(phone_lookup) == 10:
             phone_lookup = '+91' + phone_lookup
        
        # Look for user by profile phone
        from .models import UserProfile
        profile = UserProfile.objects.filter(phone=phone_lookup).first()
        if profile:
            user = authenticate(username=profile.user.username, password=password)
    
    if not user:
        return Response({'error': 'Invalid username/phone or password'}, status=401)
    
    tokens = get_tokens_for_user(user)
    return Response({
        'access': tokens['access'],
        'refresh': tokens['refresh'],
        'username': user.username,
        'message': 'Logged in successfully'
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def firebase_login(request):
    """Verifies Firebase ID Token and creates/logs in user."""
    id_token = request.data.get('idToken')
    
    if not id_token:
        return Response({'error': 'ID Token is required'}, status=400)
    
    try:
        decoded_token = auth.verify_id_token(id_token)
        
        # Identity Logic (Phone or Email)
        firebase_phone = decoded_token.get('phone_number')
        firebase_email = decoded_token.get('email')
        firebase_uid = decoded_token.get('uid')
        
        # 1. Primary Identifier (Use phone if available, else email)
        primary_id = firebase_phone or firebase_email
        
        if not primary_id:
            return Response({'error': 'Token contains no valid phone or email identifier.'}, status=400)
            
        # 2. Lookup existing user
        user = User.objects.filter(username=primary_id).first()
        if not user and firebase_email:
            # Check by email field too
            user = User.objects.filter(email=firebase_email).first()
            
        # 3. Handle First-time Auth
        if not user:
            # If it's a social/email login with an email, we create user immediately
            if firebase_email:
                # Random password since they login via Firebase provider
                import secrets
                user = User.objects.create_user(
                    username=primary_id,
                    email=firebase_email,
                    password=secrets.token_urlsafe(16)
                )
                UserProfile.objects.get_or_create(
                    user=user, 
                    defaults={'phone': firebase_phone, 'is_verified': True}
                )
            else:
                # It's a phone login and user doesn't exist, current UI wants them to set a password
                return Response({
                    'status': 'verified',
                    'user_exists': False,
                    'phone': firebase_phone,
                    'message': 'Firebase verified. Please set a password to finalize your account.'
                })
        
        # 4. Success Login Flow
        tokens = get_tokens_for_user(user)
        return Response({
            'status': 'verified',
            'user_exists': True,
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'username': user.username,
            'message': 'Verification successful. Welcome back!'
        })
        
    except Exception as e:
        print(f"FIREBASE VERIFY ERROR: {e}")
        return Response({'error': f'Firebase authentication failed: {str(e)}'}, status=401)

@api_view(['GET'])
def get_profile(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    
    # Determine allowed strategies from the user's package
    allowed_strategies = ['fast', 'detailed']  # Free tier defaults
    package_name = 'Free'
    
    if profile.package:
        package_name = profile.package.name
        raw = profile.package.grid_strategies  # e.g. "fast,detailed,deep,ultra"
        if raw:
            allowed_strategies = [s.strip() for s in raw.split(',') if s.strip()]
    
    # Improved IP detection for Proxied environments
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        current_ip = x_forwarded_for.split(',')[0].strip()
    else:
        current_ip = request.META.get('REMOTE_ADDR', 'Unknown IP')

    return Response({
        'username': user.username,
        'email': user.email,
        'phone': profile.phone,
        'is_verified': profile.is_verified,
        'package': package_name,
        'searches_left': profile.searches_left,
        'allowed_strategies': allowed_strategies,
        'last_login': user.last_login.strftime('%d/%m/%Y • %H:%M') if user.last_login else 'Just now',
        'current_ip': current_ip,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    
    new_username = request.data.get('username')
    new_email = request.data.get('email')
    
    if new_username:
        # Check if username is taken
        if User.objects.filter(username=new_username).exclude(id=user.id).exists():
            return Response({'error': 'Username is already taken by another protocol agent.'}, status=400)
        user.username = new_username
    
    if new_email:
        user.email = new_email
    
    user.save()
    
    return Response({
        'message': 'Protocol profile updated successfully.',
        'username': user.username,
        'email': user.email
    })
