import re
from django.conf import settings
from django.http import JsonResponse

class MobileOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Admin URL path
        admin_url = getattr(settings, 'ADMIN_URL', 'admin')
        
        # List of regex patterns for paths that are exempt from the mobile check
        self.exempt_patterns = [
            # Media and Static files
            re.compile(r"^" + settings.MEDIA_URL),
            re.compile(r"^" + settings.STATIC_URL),
            
            # Admin Interface
            re.compile(r"^/" + re.escape(admin_url) + r"/"),
            
            # Health Check
            re.compile(r"^/health/"),
            
            # Callbacks (Allow any URL containing 'callback')
            re.compile(r".*/callback/.*"),
            re.compile(r".*/callback$"),
        ]

    def __call__(self, request):
        path = request.path
        
        # Check if the current path is exempt
        for pattern in self.exempt_patterns:
            if pattern.match(path):
                return self.get_response(request)

        # Check User-Agent for mobile devices
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        if self.is_mobile(user_agent):
            return self.get_response(request)

        # If not mobile and not exempt, deny access
        return JsonResponse({
            'detail': 'Akses ditolak. API hanya dapat diakses melalui aplikasi mobile.',
            'code': 'mobile_device_required'
        }, status=403)

    def is_mobile(self, user_agent):
        """
        Check if the User-Agent string indicates a mobile device.
        """
        if not user_agent:
            return False
            
        # Common mobile user agent keywords
        mobile_keywords = [
            'Mobile', 'Android', 'iPhone', 'iPad', 'iPod', 
            'webOS', 'BlackBerry', 'Windows Phone', 'Opera Mini',
            'IEMobile'
        ]
        
        return any(keyword in user_agent for keyword in mobile_keywords)
