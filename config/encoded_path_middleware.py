import base64
from urllib.parse import unquote
from django.conf import settings


class EncodedApiPathMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "PATH_ENCODE_ENABLED", False):
            p = request.path or ""
            if p.startswith("/api/enc/"):
                enc = unquote(p[len("/api/enc/"):])
                salt = getattr(settings, "RESPONSE_ENCODE_SALT", "")
                try:
                    rev = enc[::-1]
                    uns = rev[:-len(salt)] if salt else rev
                    sub = base64.b64decode(uns.encode("ascii")).decode("utf-8")
                    if sub.startswith("/api/"):
                        new_path = sub
                    else:
                        new_path = "/api/" + sub.lstrip("/")
                    request.path_info = new_path
                except Exception:
                    pass
        return self.get_response(request)

