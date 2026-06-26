from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from products.models import Investment, Product, Transaction


class Command(BaseCommand):
    help = "Seed dummy transactions+investments untuk kebutuhan grafik investor per bulan"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=str,
            default="2025-11",
            help="Bulan awal format YYYY-MM (default 2025-11)",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=6,
            help="Jumlah bulan yang dibuat (default 6)",
        )
        parser.add_argument(
            "--investors-per-month",
            type=int,
            default=12,
            help="Jumlah investor unik per bulan (default 12)",
        )
        parser.add_argument(
            "--counts",
            type=str,
            default="",
            help="Daftar jumlah investor per bulan, contoh: 100,65,87,24,90,55 (akan diulang jika lebih pendek dari --months)",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Timpa per bulan: hapus data dummy pada bulan target lalu buat ulang (berguna untuk ganti --counts tanpa --reset)",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Hapus data dummy yang pernah dibuat sebelumnya (berdasarkan marker)",
        )

    def _month_start(self, y: int, m: int) -> date:
        return date(y, m, 1)

    def _add_months(self, d: date, months: int) -> date:
        year = d.year + (d.month - 1 + months) // 12
        month = (d.month - 1 + months) % 12 + 1
        return date(year, month, 1)

    def _parse_month(self, value: str) -> date:
        value = (value or "").strip()
        dt = datetime.strptime(value, "%Y-%m")
        return date(dt.year, dt.month, 1)

    def _parse_counts(self, value: str) -> list[int]:
        value = (value or "").strip()
        if not value:
            return []
        parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
        out: list[int] = []
        for p in parts:
            try:
                n = int(p)
            except Exception:
                continue
            if n > 0:
                out.append(n)
        return out

    def _get_or_create_seed_product(self) -> Product:
        product = (
            Product.objects.filter(status=1, qualify_as_active_investment=True)
            .order_by("-id")
            .first()
        )
        if product:
            return product

        return Product.objects.create(
            name="Dummy Seed Product",
            description="Seed product for dummy analytics",
            price=Decimal("100000.00"),
            status=1,
            purchase_limit=1,
            stock=0,
            stock_enabled=False,
            max_purchase_count=999,
            profit_type="fixed",
            profit_rate=Decimal("1000.00"),
            profit_random_min=None,
            profit_random_max=None,
            profit_method="manual",
            duration=24,
            balance_source="balance",
            claim_reset_mode="after_purchase",
            claim_reset_hours=None,
            require_upline_ownership_for_commissions=False,
            qualify_as_active_investment=True,
            cashback_enabled=False,
            cashback_percentage=Decimal("0"),
            return_principal_on_completion=False,
            require_min_rank_enabled=False,
            min_required_rank=None,
            specifications="",
        )

    def handle(self, *args, **kwargs):
        marker = "[DUMMY_INVESTOR_SEED]"
        start = self._parse_month(kwargs["start"])
        months = max(1, int(kwargs["months"]))
        investors_per_month = max(1, int(kwargs["investors_per_month"]))
        counts = self._parse_counts(kwargs.get("counts", ""))
        overwrite = bool(kwargs.get("overwrite"))
        reset = bool(kwargs["reset"])

        if reset:
            tx_ids = list(
                Transaction.objects.filter(description__startswith=marker).values_list(
                    "id", flat=True
                )
            )
            inv_deleted = Investment.objects.filter(transaction_id__in=tx_ids).delete()[0]
            tx_deleted = Transaction.objects.filter(id__in=tx_ids).delete()[0]
            User = get_user_model()
            users_deleted = User.objects.filter(username__startswith="dummy_inv_").delete()[0]
            self.stdout.write(
                self.style.WARNING(
                    f"Deleted dummy data: investments={inv_deleted}, transactions={tx_deleted}, users={users_deleted}"
                )
            )

        product = self._get_or_create_seed_product()
        tz = timezone.get_current_timezone()
        User = get_user_model()

        created_users = 0
        created_tx = 0
        created_inv = 0
        skipped = 0

        for idx in range(months):
            m_start = self._add_months(start, idx)
            yyyymm = m_start.strftime("%Y%m")
            created_at = timezone.make_aware(
                datetime.combine(m_start, time(hour=12, minute=0, second=0)), tz
            )

            month_filter = {
                "description__startswith": marker,
                "description__contains": yyyymm,
            }

            existing_tx_ids = list(
                Transaction.objects.filter(**month_filter).values_list("id", flat=True)
            )
            if existing_tx_ids and overwrite:
                Investment.objects.filter(transaction_id__in=existing_tx_ids).delete()
                Transaction.objects.filter(id__in=existing_tx_ids).delete()
                existing_tx_ids = []

            if existing_tx_ids:
                skipped += 1
                continue

            month_investors = investors_per_month
            if counts:
                month_investors = counts[idx % len(counts)]

            with db_transaction.atomic():
                for i in range(month_investors):
                    username = f"dummy_inv_{yyyymm}_{i+1}"
                    phone = f"88{yyyymm}{i+1:03d}"
                    email = f"dummy_inv_{yyyymm}_{i+1}@example.com"

                    user, user_created = User.objects.get_or_create(
                        phone=phone,
                        defaults={
                            "username": username,
                            "email": email,
                            "full_name": f"Dummy Investor {yyyymm}-{i+1}",
                            "is_staff": False,
                        },
                    )
                    if user_created:
                        user.set_password("pass")
                        user.save(update_fields=["password"])
                        created_users += 1

                    trx_id = f"DUMMYINV-{yyyymm}-{user.id}-{i+1}"
                    tx = Transaction.objects.create(
                        user=user,
                        product=product,
                        upline_user=None,
                        trx_id=trx_id,
                        type="INVESTMENTS",
                        amount=product.price,
                        description=f"{marker} month={yyyymm}",
                        status="COMPLETED",
                        wallet_type="BALANCE",
                        investment_quantity=1,
                        commission_level=None,
                        related_transaction=None,
                        voucher_id=None,
                        voucher_code=None,
                    )
                    Transaction.objects.filter(id=tx.id).update(created_at=created_at)
                    created_tx += 1

                    inv = Investment.objects.create(
                        user=user,
                        product=product,
                        transaction=tx,
                        quantity=1,
                        total_amount=product.price,
                        profit_type=product.profit_type,
                        profit_rate=product.profit_rate,
                        profit_random_min=product.profit_random_min,
                        profit_random_max=product.profit_random_max,
                        profit_method=product.profit_method,
                        claim_reset_mode=product.claim_reset_mode,
                        duration_days=30,
                        remaining_days=30,
                        expires_at=created_at + timedelta(days=30),
                        status="ACTIVE",
                    )
                    Investment.objects.filter(id=inv.id).update(created_at=created_at)
                    created_inv += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. users_created={created_users}, tx_created={created_tx}, inv_created={created_inv}, months_skipped={skipped}"
            )
        )
