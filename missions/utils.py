from typing import List, Set
from accounts.models import User
from products.models import Transaction, Investment
from deposits.models import Deposit
from withdrawal.models import Withdrawal
from django.db.models import Sum


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


def compute_mission_progress(mission, user: User) -> int:
    if not user or not user.is_authenticated:
        return 0

    mtype = mission.type
    levels = mission.referral_levels or []
    levels = [lvl for lvl in levels if lvl in [1, 2, 3]]

    if mtype == 'referral':
        downline_ids = _get_downlines(user, levels or [1])
        return len(downline_ids)

    if mtype == 'active_downline':
        downline_ids = _get_downlines(user, levels or [1])
        if not downline_ids:
            return 0
        return (
            Investment.objects.filter(
                user_id__in=downline_ids,
                status='ACTIVE',
                product__qualify_as_active_investment=True,
            )
            .values('user_id')
            .distinct()
            .count()
        )

    if mtype == 'purchase':
        downline_ids = _get_downlines(user, levels or [1])
        if not downline_ids:
            return 0
        return Investment.objects.filter(user_id__in=downline_ids).values('user_id').distinct().count()

    if mtype == 'purchase_self':
        # Hitung jumlah pembelian/aktivasi milik user sendiri
        # Pilih menghitung berdasarkan transaksi purchase (INVESTMENTS) yang COMPLETED
        return Transaction.objects.filter(
            user_id=user.id,
            type='INVESTMENTS',
            status='COMPLETED'
        ).count()

    if mtype == 'deposit_self':
        # Progres adalah total nominal deposit milik user sendiri yang berstatus COMPLETED
        agg = Deposit.objects.filter(user_id=user.id, status='COMPLETED').aggregate(total=Sum('amount'))
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
        agg = Deposit.objects.filter(user_id__in=downline_ids, status='COMPLETED').aggregate(total=Sum('amount'))
        total = agg.get('total') or 0
        try:
            return int(total)
        except Exception:
            return 0

    if mtype == 'service':
        downline_ids = _get_downlines(user, levels or [1])
        if not downline_ids:
            return 0
        return Transaction.objects.filter(
            user_id__in=downline_ids,
            type='INTEREST'
        ).values('user_id').distinct().count()

    if mtype == 'service_self':
        # Hitung jumlah klaim profit (INTEREST) milik user sendiri
        return Transaction.objects.filter(
            user_id=user.id,
            type='INTEREST',
            status='COMPLETED'
        ).count()

    if mtype == 'withdrawal':
        # Hitung jumlah withdraw user sendiri dengan status COMPLETED
        return Withdrawal.objects.filter(user=user, status='COMPLETED').count()

    return 0
