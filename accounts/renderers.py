import base64
import json
from django.conf import settings
from rest_framework.renderers import JSONRenderer


class SaltedBase64ReverseJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        ctx = renderer_context or {}
        req = ctx.get("request")
        if not req:
            return super().render(data, accepted_media_type, renderer_context)
        view = ctx.get("view")
        if view is not None and getattr(view, "skip_response_encoding", False):
            return super().render(data, accepted_media_type, renderer_context)
        if not getattr(settings, "RESPONSE_ENCODE_ENABLED", False):
            return super().render(data, accepted_media_type, renderer_context)
        p = req.path or ""
        if "schema" in p or "docs" in p:
            return super().render(data, accepted_media_type, renderer_context)
        admin_prefix = f"/{getattr(settings, 'ADMIN_URL', 'admin')}"
        if p.startswith(admin_prefix):
            return super().render(data, accepted_media_type, renderer_context)
        raw = super().render(data, accepted_media_type, renderer_context)
        salt = getattr(settings, "RESPONSE_ENCODE_SALT", "")
        b64 = base64.b64encode(raw).decode("ascii")
        s = (b64 + salt)[::-1]
        return json.dumps({"data": s}).encode("utf-8")
