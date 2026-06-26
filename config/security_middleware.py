"""
Security Middleware untuk membatasi akses API berdasarkan domain dan IP yang diizinkan.
"""
import os
from django.http import JsonResponse
from django.conf import settings
import ipaddress
import re


class DomainIPSecurityMiddleware:
    """
    Middleware untuk membatasi akses API berdasarkan:
    1. Domain yang diizinkan (ALLOWED_DOMAINS)
    2. IP Address yang diizinkan (ALLOWED_IPS)
    3. IP Range yang diizinkan (ALLOWED_IP_RANGES)
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Load allowed domains from environment or settings
        self.allowed_domains = self._get_allowed_domains()
        
        # Load allowed IPs from environment or settings
        self.allowed_ips = self._get_allowed_ips()
        
        # Load allowed IP ranges from environment or settings
        self.allowed_ip_ranges = self._get_allowed_ip_ranges()
        
        # Bypass security for development
        self.bypass_security = getattr(settings, 'BYPASS_DOMAIN_IP_SECURITY', False)
        
    def __call__(self, request):
        # Skip security check if bypassed (for development)
        if self.bypass_security:
            return self.get_response(request)
            
        # Skip security check for admin panel and static files
        if self._should_skip_security_check(request):
            return self.get_response(request)
            
        # Validate domain and IP
        if not self._is_access_allowed(request):
            return JsonResponse({
                'error': 'Access denied',
                'message': 'Your domain or IP address is not authorized to access this API',
                'code': 'DOMAIN_IP_RESTRICTED'
            }, status=403)
            
        return self.get_response(request)
    
    def _get_allowed_domains(self):
        """Get allowed domains from environment variables or settings"""
        domains_str = os.environ.get('ALLOWED_DOMAINS', '')
        if domains_str:
            domains = [domain.strip() for domain in domains_str.split(',') if domain.strip()]
        else:
            # Default allowed domains
            domains = getattr(settings, 'ALLOWED_DOMAINS', [
                'localhost',
                '127.0.0.1',
                'localhost:8000',
                '127.0.0.1:8000',
            ])
        return domains
    
    def _get_allowed_ips(self):
        """Get allowed IP addresses from environment variables or settings"""
        ips_str = os.environ.get('ALLOWED_IPS', '')
        if ips_str:
            ips = [ip.strip() for ip in ips_str.split(',') if ip.strip()]
        else:
            # Default allowed IPs
            ips = getattr(settings, 'ALLOWED_IPS', [
                '127.0.0.1',
                '::1',  # IPv6 localhost
            ])
        return ips
    
    def _get_allowed_ip_ranges(self):
        """Get allowed IP ranges from environment variables or settings"""
        ranges_str = os.environ.get('ALLOWED_IP_RANGES', '')
        if ranges_str:
            ranges = [range_ip.strip() for range_ip in ranges_str.split(',') if range_ip.strip()]
        else:
            # Default allowed IP ranges (local networks)
            ranges = getattr(settings, 'ALLOWED_IP_RANGES', [
                '192.168.0.0/16',    # Private network
                '10.0.0.0/8',        # Private network
                '172.16.0.0/12',     # Private network
            ])
        return ranges
    
    def _should_skip_security_check(self, request):
        skip_paths = [
            '/static/',
            '/media/',
            '/favicon.ico',
        ]
        path = request.path or ''
        admin_base = f"/{getattr(settings, 'ADMIN_URL', 'admin').strip('/')}"
        if path == admin_base or path.startswith(admin_base + "/"):
            return True
        return any(path.startswith(skip_path) for skip_path in skip_paths)
    
    def _is_access_allowed(self, request):
        """Check if the request is from an allowed domain or IP"""
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Get host/domain - handle potential DisallowedHost error
        try:
            host = request.get_host()
        except Exception:
            # If get_host() fails (e.g., DisallowedHost), deny access
            return False
        
        # Check if IP is allowed
        if self._is_ip_allowed(client_ip):
            return True
            
        # Check if domain is allowed
        if self._is_domain_allowed(host):
            return True
            
        return False
    
    def _get_client_ip(self, request):
        """Get the real client IP address"""
        meta = request.META
        forwarded_client_ip = meta.get('HTTP_X_ORIGINAL_CLIENT_IP') or meta.get('HTTP_X_CLIENT_IP')
        if forwarded_client_ip and '{' not in forwarded_client_ip and '}' not in forwarded_client_ip:
            return forwarded_client_ip
        cf_ip = meta.get('HTTP_CF_CONNECTING_IP')
        if cf_ip and '{' not in cf_ip and '}' not in cf_ip:
            return cf_ip
        x_forwarded_for = meta.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
            if ip and '{' not in ip and '}' not in ip:
                return ip
        x_real_ip = meta.get('HTTP_X_REAL_IP')
        if x_real_ip and '{' not in x_real_ip and '}' not in x_real_ip:
            return x_real_ip
        ip = meta.get('REMOTE_ADDR', '')
        if ip and '{' not in ip and '}' not in ip:
            return ip
        return ''
    
    def _is_ip_allowed(self, client_ip):
        """Check if client IP is in allowed IPs or IP ranges"""
        if not client_ip:
            return False
            
        try:
            client_ip_obj = ipaddress.ip_address(client_ip)
            
            # Check exact IP matches
            for allowed_ip in self.allowed_ips:
                if str(client_ip_obj) == allowed_ip:
                    return True
            
            # Check IP ranges
            for ip_range in self.allowed_ip_ranges:
                try:
                    network = ipaddress.ip_network(ip_range, strict=False)
                    if client_ip_obj in network:
                        return True
                except ValueError:
                    continue
                    
        except ValueError:
            # Invalid IP address
            return False
            
        return False
    
    def _is_domain_allowed(self, host):
        """Check if host/domain is in allowed domains"""
        if not host:
            return False
            
        # Remove port from host if present
        host_without_port = host.split(':')[0]
        
        # Check exact domain matches
        for allowed_domain in self.allowed_domains:
            # Remove port from allowed domain if present
            allowed_domain_without_port = allowed_domain.split(':')[0]
            
            # Exact match
            if host == allowed_domain or host_without_port == allowed_domain_without_port:
                return True
                
            # Wildcard subdomain match (e.g., *.example.com)
            if allowed_domain.startswith('*.'):
                domain_pattern = allowed_domain[2:]  # Remove *.
                if host_without_port.endswith('.' + domain_pattern) or host_without_port == domain_pattern:
                    return True
        
        return False
