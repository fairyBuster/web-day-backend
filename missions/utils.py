from typing import List, Set, Tuple
from datetime import timedelta
from accounts.models import User
from products.models import Transaction, Investment
from deposits.models import Deposit
from withdrawal.models import Withdrawal
from .models import Mission, MissionUserState
from django.db.models import Sum
from django.utils import timezone


def _get_downlines(user: User, levels: List[int]) -> Set[int]:
    ids: Set[int] = set()
    current_level = [user]
    for lvl in range(1, max(levels or [0]) + 1):
        if not current_level:
            break
        # Bulk fetch next level users to avoid N+1
        next_level = list(User.objects.filter(referral_by__in=current_level))
        
        if lvl in levels:
            for d in next_level:
                ids.add(d.id)
        
        current_level = next_level
    return ids


def _get_period_bounds(mission: Mission, state: MissionUserState, user: User) -> Tuple[timezone.datetime, timezone.datetime]:
    """Get start and end time of the current fixed period based on user registration date"""
    now = timezone.now()
    period_days = mission.time_period_days
    
    # Start with user's registration date as anchor point
    anchor_date = user.date_joined
    
    if not state.period_start:
        # Calculate how many full periods have passed since anchor date
        delta = now - anchor_date
        periods_passed = delta.total_seconds() // (period_days * 86400)  # 86400 seconds = 1 day
        current_period_start = anchor_date + timedelta(days=periods_passed * period_days)
        return current_period_start, current_period_start + timedelta(days=period_days)
    
    # Check if current period has expired
    period_end = state.period_start + timedelta(days=period_days)
    if now >= period_end:
        # Period has expired, calculate next period based on anchor date
        delta = now - anchor_date
        periods_passed = delta.total_seconds() // (period_days * 86400)
        new_period_start = anchor_date + timedelta(days=periods_passed * period_days)
        return new_period_start, new_period_start + timedelta(days=period_days)
    
    # Still in current period
    return state.period_start, period_end


def compute_mission_progress(mission: Mission, user: User, state: MissionUserState = None) -> int:
    if not user or not user.is_authenticated:
        return 0

    mtype = mission.type
    levels = mission.referral_levels or []
    levels = [lvl for lvl in levels if lvl in [1, 2, 3]]
    
    # Calculate time limit filter if mission is time limited
    period_start = None
    period_end = None
    if mission.is_time_limited and mission.time_period_days:
        if not state:
            state, _ = MissionUserState.objects.get_or_create(user=user, mission=mission)
        period_start, period_end = _get_period_bounds(mission, state, user)

    if mtype == 'referral':
        # For referral, we usually don't have a time (since it's user registration)
        # but if needed, we could check user.date_joined
        downline_ids = _get_downlines(user, levels or [1])
        if period_start:
            # Filter downlines who joined within the time period
            downline_ids = set(User.objects.filter(id__in=downline_ids, date_joined__gte=period_start, date_joined__lt=period_end).values_list('id', flat=True))
        return len(downline_ids)

    if mtype == 'active_downline':
        downline_ids = _get_downlines(user, levels or [1])
        if not downline_ids:
            return 0
        query = Investment.objects.filter(
            user_id__in=downline_ids,
            status='ACTIVE',
            product__qualify_as_active_investment=True,
        )
        if period_start:
            # Filter investments created within the time period
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        return (
            query
            .values('user_id')
            .distinct()
            .count()
        )

    if mtype == 'purchase':
        downline_ids = _get_downlines(user, levels or [1])
        if not downline_ids:
            return 0
        query = Investment.objects.filter(user_id__in=downline_ids)
        if period_start:
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        return query.values('user_id').distinct().count()

    if mtype == 'purchase_self':
        # Hitung jumlah pembelian/aktivasi milik user sendiri
        # Pilih menghitung berdasarkan transaksi purchase (INVESTMENTS) yang COMPLETED
        query = Transaction.objects.filter(
            user_id=user.id,
            type='INVESTMENTS',
            status='COMPLETED'
        )
        if period_start:
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        return query.count()

    if mtype == 'deposit_self':
        # Progres adalah total nominal deposit milik user sendiri yang berstatus COMPLETED
        query = Deposit.objects.filter(user_id=user.id, status='COMPLETED')
        if period_start:
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        agg = query.aggregate(total=Sum('amount'))
        total = agg.get('total') or 0
        try:
            # Kembalikan sebagai integer unit (mis. rupiah) untuk konsistensi requirement (integer)
            return int(total)
        except Exception:
            # Fallback jika tipe tidak konversi: gunakan 0
            return 0

    if mtype == 'deposit':
        downline_ids = _get_downlines(user, levels or [1])
        if not downline_ids:
            return 0
        query = Deposit.objects.filter(user_id__in=downline_ids, status='COMPLETED')
        if period_start:
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        agg = query.aggregate(total=Sum('amount'))
        total = agg.get('total') or 0
        try:
            return int(total)
        except Exception:
            return 0

    if mtype == 'service':
        downline_ids = _get_downlines(user, levels or [1])
        if not downline_ids:
            return 0
        query = Transaction.objects.filter(
            user_id__in=downline_ids,
            type='INTEREST'
        )
        if period_start:
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        return query.values('user_id').distinct().count()

    if mtype == 'service_self':
        # Hitung jumlah klaim profit (INTEREST) milik user sendiri
        query = Transaction.objects.filter(
            user_id=user.id,
            type='INTEREST',
            status='COMPLETED'
        )
        if period_start:
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        return query.count()

    if mtype == 'withdrawal':
        # Hitung jumlah withdraw user sendiri dengan status COMPLETED
        query = Withdrawal.objects.filter(user=user, status='COMPLETED')
        if period_start:
            query = query.filter(created_at__gte=period_start, created_at__lt=period_end)
        return query.count()

    return 0
