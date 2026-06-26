from datetime import date, datetime, time

from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import Investment


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    return date(year, month, 1)


def _parse_month(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m")
        return date(dt.year, dt.month, 1)
    except Exception:
        return None


class AdminMonthlyInvestorsView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)
    throttle_scope = "admin_analytics"

    @extend_schema(
        tags=["Admin API"],
        parameters=[
            OpenApiParameter(
                name="start",
                type=str,
                required=False,
                description="Bulan awal (YYYY-MM). Default: 12 bulan terakhir.",
            ),
            OpenApiParameter(
                name="end",
                type=str,
                required=False,
                description="Bulan akhir (YYYY-MM). Default: bulan sekarang.",
            ),
            OpenApiParameter(
                name="include_staff",
                type=bool,
                required=False,
                description="Jika true, akun staff ikut dihitung. Default: false.",
            ),
            OpenApiParameter(
                name="include_non_qualifying",
                type=bool,
                required=False,
                description="Jika true, investasi dari produk non-qualifying ikut dihitung. Default: false.",
            ),
        ],
        responses={200: OpenApiResponse(description="Total investor per bulan")},
    )
    def get(self, request):
        start = _parse_month(request.query_params.get("start"))
        end = _parse_month(request.query_params.get("end"))

        include_staff = (request.query_params.get("include_staff") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        include_non_qualifying = (
            (request.query_params.get("include_non_qualifying") or "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

        now_dt = timezone.now()
        today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
        end_month = end or _month_start(today)
        start_month = start or _add_months(end_month, -11)

        if start_month > end_month:
            start_month, end_month = end_month, start_month

        now_dt = timezone.now()
        if timezone.is_aware(now_dt):
            tz = timezone.get_current_timezone()
            start_dt = timezone.make_aware(datetime.combine(start_month, time.min), tz)
        else:
            start_dt = datetime.combine(start_month, time.min)
        end_next = _add_months(end_month, 1)
        if timezone.is_aware(now_dt):
            end_dt = timezone.make_aware(datetime.combine(end_next, time.min), tz)
        else:
            end_dt = datetime.combine(end_next, time.min)

        qs = Investment.objects.exclude(status="CANCELLED")
        if not include_staff:
            qs = qs.filter(user__is_staff=False)
        if not include_non_qualifying:
            qs = qs.filter(product__qualify_as_active_investment=True)
        qs = qs.filter(created_at__gte=start_dt, created_at__lt=end_dt)

        rows = (
            qs.annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(total_investors=Count("user_id", distinct=True))
            .order_by("month")
        )
        counts = {r["month"].date(): int(r["total_investors"]) for r in rows if r.get("month")}

        points = []
        cur = start_month
        while cur <= end_month:
            points.append({"month": cur.strftime("%Y-%m"), "total_investors": counts.get(cur, 0)})
            cur = _add_months(cur, 1)

        return Response(
            {
                "start": start_month.strftime("%Y-%m"),
                "end": end_month.strftime("%Y-%m"),
                "points": points,
            }
        )


class MonthlyInvestorsView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_scope = "analytics_investors_monthly"

    @extend_schema(
        tags=["User API"],
        parameters=[
            OpenApiParameter(
                name="start",
                type=str,
                required=False,
                description="Bulan awal (YYYY-MM). Default: 6 bulan terakhir.",
            ),
            OpenApiParameter(
                name="end",
                type=str,
                required=False,
                description="Bulan akhir (YYYY-MM). Default: bulan sekarang.",
            ),
        ],
        responses={200: OpenApiResponse(description="Total investor per bulan (untuk user biasa)")},
    )
    def get(self, request):
        start = _parse_month(request.query_params.get("start"))
        end = _parse_month(request.query_params.get("end"))

        now_dt = timezone.now()
        today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
        end_month = end or _month_start(today)
        start_month = start or _add_months(end_month, -5)

        if start_month > end_month:
            start_month, end_month = end_month, start_month

        max_months = 24
        earliest_allowed = _add_months(end_month, -(max_months - 1))
        if start_month < earliest_allowed:
            start_month = earliest_allowed

        now_dt = timezone.now()
        if timezone.is_aware(now_dt):
            tz = timezone.get_current_timezone()
            start_dt = timezone.make_aware(datetime.combine(start_month, time.min), tz)
        else:
            start_dt = datetime.combine(start_month, time.min)
        end_next = _add_months(end_month, 1)
        if timezone.is_aware(now_dt):
            end_dt = timezone.make_aware(datetime.combine(end_next, time.min), tz)
        else:
            end_dt = datetime.combine(end_next, time.min)

        qs = (
            Investment.objects.exclude(status="CANCELLED")
            .filter(user__is_staff=False, product__qualify_as_active_investment=True)
            .filter(created_at__gte=start_dt, created_at__lt=end_dt)
        )

        rows = (
            qs.annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(total_investors=Count("user_id", distinct=True))
            .order_by("month")
        )
        counts = {r["month"].date(): int(r["total_investors"]) for r in rows if r.get("month")}

        points = []
        cur = start_month
        while cur <= end_month:
            points.append({"month": cur.strftime("%Y-%m"), "total_investors": counts.get(cur, 0)})
            cur = _add_months(cur, 1)

        return Response(
            {
                "start": start_month.strftime("%Y-%m"),
                "end": end_month.strftime("%Y-%m"),
                "points": points,
            }
        )
