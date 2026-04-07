# core/middleware.py

class SecurityHeadersMiddleware:
    """
    Injects modern security headers that satisfy clickjacking and framing detectors.
    Ensures 'Content-Security-Policy: frame-ancestors none' is always present.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # 🛡️ THE MODERN SHIELD: Satisfies Clickjacker.io 'frame-ancestors' check
        # This tells the browser NO ONE is allowed to embed this site in an iframe.
        response['Content-Security-Policy'] = "frame-ancestors 'none';"
        
        # Performance/Security Extras
        response['X-Content-Type-Options'] = "nosniff"
        response['Referrer-Policy'] = "same-origin"
        
        return response
