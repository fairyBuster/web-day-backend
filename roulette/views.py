from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import RoulettePrize, RouletteTicketWallet
from .serializers import (
    RouletteStatusResponseSerializer,
    RouletteSpinResponseSerializer,
    RoulettePrizeSerializer,
    RouletteEarnMethodsResponseSerializer,
)
from .services import get_settings, spin


USER_TAG = "User API"


class RouletteStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=[USER_TAG],
        summary="Roulette status",
        responses={200: OpenApiResponse(response=RouletteStatusResponseSerializer)},
    )
    def get(self, request):
        settings_obj = get_settings()
        is_active = bool(settings_obj and settings_obj.is_active)
        ticket_cost = int(getattr(settings_obj, "ticket_cost", 1) or 1)

        wallet = RouletteTicketWallet.objects.filter(user=request.user).first()
        tickets = int(getattr(wallet, "balance", 0) or 0)

        prizes_qs = RoulettePrize.objects.filter(is_active=True).order_by("sort_order", "id")
        prizes = list(prizes_qs)
        total_weight = sum(int(p.weight or 0) for p in prizes if int(p.weight or 0) > 0)
        ser_prizes = RoulettePrizeSerializer(prizes, many=True, context={"total_weight": total_weight})

        return Response(
            {
                "is_active": is_active,
                "ticket_cost": ticket_cost,
                "tickets": tickets,
                "prizes": ser_prizes.data,
            }
        )


class RouletteSpinView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=[USER_TAG],
        summary="Spin roulette",
        request=None,
        responses={
            200: OpenApiResponse(response=RouletteSpinResponseSerializer),
            400: OpenApiResponse(description="Cannot spin"),
        },
    )
    def post(self, request):
        try:
            res = spin(request.user)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        prize = res.get("prize")
        return Response(
            {
                "message": "Spin berhasil",
                "tickets_before": res.get("tickets_before"),
                "tickets_after": res.get("tickets_after"),
                "prize_id": prize.id if prize else None,
                "prize_name": prize.name if prize else None,
                "prize_type": res.get("prize_type"),
                "prize_amount": res.get("prize_amount"),
                "transaction_id": res.get("transaction_id"),
            }
        )


class RouletteEarnMethodsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=[USER_TAG],
        summary="Roulette earn methods",
        responses={200: OpenApiResponse(response=RouletteEarnMethodsResponseSerializer)},
    )
    def get(self, request):
        settings_obj = get_settings()
        is_active = bool(settings_obj and settings_obj.is_active)
        return Response(
            {
                "is_active": is_active,
                "grant_tickets_from_level1_purchase": bool(
                    getattr(settings_obj, "grant_tickets_from_level1_purchase", True)
                )
                if settings_obj
                else False,
                "tickets_per_level1_purchase": int(
                    getattr(settings_obj, "tickets_per_level1_purchase", 0) or 0
                )
                if settings_obj
                else 0,
                "grant_tickets_from_self_deposit": bool(
                    getattr(settings_obj, "grant_tickets_from_self_deposit", False)
                )
                if settings_obj
                else False,
                "tickets_per_completed_deposit": int(
                    getattr(settings_obj, "tickets_per_completed_deposit", 0) or 0
                )
                if settings_obj
                else 0,
                "min_deposit_amount_for_tickets": str(
                    getattr(settings_obj, "min_deposit_amount_for_tickets", 0) or 0
                )
                if settings_obj
                else "0",
                "ticket_cost": int(getattr(settings_obj, "ticket_cost", 1) or 1)
                if settings_obj
                else 1,
            }
        )
