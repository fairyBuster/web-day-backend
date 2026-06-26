from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiResponse
from django.utils import timezone
from django.db import transaction as db_transaction, connection, IntegrityError
from django.db.models import Q
import uuid
from zoneinfo import ZoneInfo

from .models import Voucher, VoucherUsage
from .serializers import (
    VoucherSerializer,
    ClaimVoucherSerializer,
    VoucherListResponseSerializer,
    ClaimVoucherResponseSerializer,
)
from products.models import Transaction


from django.contrib.auth import get_user_model


def _now_in_zone(tz):
    now = timezone.now()
    if timezone.is_aware(now):
        return timezone.localtime(now, tz)
    return now


def _sync_voucher_usages_sequence():
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", ["public.voucher_usages"])
        table_ref = cursor.fetchone()[0] or None
        if not table_ref:
            cursor.execute("SELECT to_regclass(%s)", ["voucher_usages"])
            table_ref = cursor.fetchone()[0] or None
        if not table_ref:
            return

        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [str(table_ref)])
        seq = cursor.fetchone()[0] or None
        if not seq:
            cursor.execute("SELECT pg_get_identity_sequence(%s, 'id')", [str(table_ref)])
            seq = cursor.fetchone()[0] or None
        if not seq:
            return

        cursor.execute(
            f"""
            SELECT setval(
                %s,
                COALESCE(MAX(id), 1),
                MAX(id) IS NOT NULL
            )
            FROM {table_ref}
            """,
            [seq],
        )

class VoucherListView(APIView):
    @extend_schema(
        tags=["User API"],
        description="List voucher aktif yang bisa diklaim",
        responses={200: OpenApiResponse(response=VoucherListResponseSerializer)},
    )
    def get(self, request):
        now = timezone.now()
        qs = Voucher.objects.filter(is_active=True, claim_mode='automatic').filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        serializer = VoucherSerializer(qs, many=True, context={'request': request})
        return Response({
            'count': qs.count(),
            'results': serializer.data
        })


class ClaimVoucherView(APIView):
    throttle_scope = 'voucher_claim'
    @extend_schema(
        tags=["User API"],
        description="Claim voucher untuk menambah saldo user",
        request=ClaimVoucherSerializer,
        responses={
            201: OpenApiResponse(response=ClaimVoucherResponseSerializer),
            400: OpenApiResponse(description='Voucher tidak aktif/kedaluwarsa/batas penggunaan habis/nominal tidak valid'),
            404: OpenApiResponse(description='Voucher tidak ditemukan'),
        },
    )
    def post(self, request):
        serializer = ClaimVoucherSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data['code']
        
        # Use atomic transaction with select_for_update to prevent race conditions
        with db_transaction.atomic():
            User = get_user_model()
            # Lock the user row to prevent concurrent claims by the same user
            try:
                user = User.objects.select_for_update().get(pk=request.user.pk)
            except User.DoesNotExist:
                # Should not happen if authenticated
                return Response({'error': 'User invalid'}, status=status.HTTP_400_BAD_REQUEST)

            # Lock the voucher row to handle global usage limits correctly
            try:
                voucher = Voucher.objects.select_for_update().get(code=code)
            except Voucher.DoesNotExist:
                return Response({'error': 'Voucher tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

            # Validate voucher
            if not voucher.is_active:
                return Response({'error': 'Voucher tidak aktif'}, status=status.HTTP_400_BAD_REQUEST)

            if voucher.start_at and timezone.now() < voucher.start_at:
                return Response({'error': 'Voucher belum dapat diklaim'}, status=status.HTTP_400_BAD_REQUEST)

            if voucher.expires_at and timezone.now() >= voucher.expires_at:
                return Response({'error': 'Voucher sudah kedaluwarsa'}, status=status.HTTP_400_BAD_REQUEST)

            # Check global limit OR daily limit depending on mode
            if voucher.is_daily_claim:
                 jakarta_tz = ZoneInfo('Asia/Jakarta')
                 now_local = _now_in_zone(jakarta_tz)
                 today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                 
                 # Count usage TODAY across ALL users for this voucher
                 daily_usage_count = VoucherUsage.objects.filter(
                     voucher=voucher, 
                     used_at__gte=today_start_local
                 ).count()
                 
                 if daily_usage_count >= voucher.usage_limit:
                     return Response({'error': 'Kuota voucher harian telah habis'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                if voucher.used_count >= voucher.usage_limit:
                    return Response({'error': 'Voucher telah mencapai batas penggunaan'}, status=status.HTTP_400_BAD_REQUEST)

            # Enforce usage limit per user
            if voucher.is_daily_claim:
                jakarta_tz = ZoneInfo('Asia/Jakarta')
                now_local = _now_in_zone(jakarta_tz)
                today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                
                # Check if claimed today (in Jakarta time)
                if VoucherUsage.objects.filter(voucher=voucher, user=user, used_at__gte=today_start_local).exists():
                    return Response({'error': 'Anda sudah klaim voucher ini hari ini. Coba lagi besok.'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                # Enforce one-time usage per user per voucher code (lifetime)
                if VoucherUsage.objects.filter(voucher=voucher, user=user).exists():
                    return Response({'error': 'Voucher ini sudah digunakan oleh akun Anda'}, status=status.HTTP_400_BAD_REQUEST)

            # Calculate amount mirroring attendance types
            from decimal import Decimal
            import random

            if voucher.type == 'fixed':
                base_amount = Decimal(voucher.amount or 0)
            elif voucher.type == 'random':
                min_amt = Decimal(voucher.min_amount or 0)
                max_amt = Decimal(voucher.max_amount or 0)
                if max_amt < min_amt:
                    max_amt = min_amt
                rand_float = random.uniform(float(min_amt), float(max_amt))
                base_amount = Decimal(str(rand_float)).quantize(Decimal('0.01'))
            elif voucher.type == 'rank':
                rank_key = str(user.rank or '').strip()
                amount_from_rank = None
                if rank_key:
                    try:
                        amount_from_rank = Decimal(str((voucher.rank_rewards or {}).get(rank_key, 0)))
                    except Exception:
                        amount_from_rank = Decimal('0')
                base_amount = amount_from_rank if amount_from_rank and amount_from_rank > 0 else Decimal(voucher.amount or 0)
            else:
                base_amount = Decimal(voucher.amount or 0)

            amount = base_amount

            if amount <= 0:
                return Response({'error': 'Nominal voucher tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

            balance_field = 'balance' if voucher.balance_type == 'BALANCE' else 'balance_deposit'

            # Credit balance
            current_balance = getattr(user, balance_field)
            setattr(user, balance_field, current_balance + amount)
            user.save()

            # Create transaction record
            now_wib = _now_in_zone(ZoneInfo('Asia/Jakarta'))
            trx_id = f"VCH-{now_wib.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
            trx = Transaction.objects.create(
                user=user,
                product=None,
                type='VOUCHER',
                amount=amount,
                description=f'Voucher claim {voucher.code}',
                status='COMPLETED',
                wallet_type=voucher.balance_type,
                voucher_id=voucher.id,
                voucher_code=voucher.code,
                trx_id=trx_id,
            )

            # Log usage
            try:
                with db_transaction.atomic():
                    VoucherUsage.objects.create(
                        voucher=voucher,
                        user=user,
                        transaction=trx,
                        voucher_code=voucher.code,
                        amount_credited=amount,
                        amount_received=amount,
                        balance_type=voucher.balance_type,
                    )
            except IntegrityError as e:
                if "voucher_usages_pkey" in str(e):
                    _sync_voucher_usages_sequence()
                    with db_transaction.atomic():
                        VoucherUsage.objects.create(
                            voucher=voucher,
                            user=user,
                            transaction=trx,
                            voucher_code=voucher.code,
                            amount_credited=amount,
                            amount_received=amount,
                            balance_type=voucher.balance_type,
                        )
                else:
                    raise

            # Increment usage counter
            voucher.used_count += 1
            voucher.save(update_fields=['used_count'])

        return Response({
            'message': 'Voucher berhasil diclaim',
            'voucher_code': voucher.code,
            'amount': str(amount),
            'wallet_type': voucher.balance_type,
            'transaction_id': trx.trx_id,
            'balance': str(getattr(user, balance_field))
        }, status=status.HTTP_201_CREATED)
