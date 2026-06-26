from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from products.models import Investment, Transaction
import uuid
import logging
from decimal import Decimal
from zoneinfo import ZoneInfo
from config import format_currency

logger = logging.getLogger(__name__)


def _now_in_zone(tz):
    now = timezone.now()
    if timezone.is_aware(now):
        return timezone.localtime(now, tz)
    return now


class Command(BaseCommand):
    help = 'Process automatic profits for investments with auto profit method'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without actually processing',
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Reduce output for scheduled runs',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        quiet = options['quiet']
        
        if dry_run and not quiet:
            self.stdout.write(self.style.WARNING('🔍 DRY RUN MODE - No actual processing will occur'))
        
        # Get all active investments with automatic or hold profit method that can claim today
        eligible_investments = Investment.objects.filter(
            status='ACTIVE',
            product__profit_method__in=['auto', 'hold'],
            remaining_days__gt=0
        )
        
        processed_count = 0
        skipped_count = 0
        error_count = 0
        
        if not quiet:
            self.stdout.write(f"📊 Found {eligible_investments.count()} investments with automatic profit method")
        
        # Log untuk monitoring
        logger.info(f"Starting automatic profit processing - Found {eligible_investments.count()} eligible investments")
        
        for investment in eligible_investments:
            try:
                # Check if can claim today
                if not investment.can_claim_today():
                    skipped_count += 1
                    if dry_run and not quiet:
                        self.stdout.write(f"⏭️  Skip: {investment.user.phone} - {investment.product.name} (already claimed or not eligible)")
                    continue
                
                # Calculate daily profit
                daily_profit = investment.daily_profit
                
                if daily_profit <= 0:
                    skipped_count += 1
                    if dry_run and not quiet:
                        self.stdout.write(f"⏭️  Skip: {investment.user.phone} - {investment.product.name} (no profit to claim)")
                    continue
                
                if dry_run:
                    if not quiet:
                        self.stdout.write(
                            f"✅ Would process: {investment.user.phone} - {investment.product.name} "
                            f"(Profit: {format_currency(daily_profit)})"
                        )
                    processed_count += 1
                    continue
                
                # Process the automatic profit claim
                with transaction.atomic():
                    # Re-fetch with lock to prevent race conditions (double claiming)
                    # This ensures only one process can claim for this investment at a time
                    investment = Investment.objects.select_for_update().get(pk=investment.pk)
                    
                    # Re-check eligibility after acquiring lock
                    if not investment.can_claim_today():
                        skipped_count += 1
                        continue

                    user = investment.user
                    
                    # Decide wallet based on profit method
                    if investment.product.profit_method == 'hold':
                        current_balance = user.balance_hold
                        user.balance_hold = current_balance + daily_profit
                        user.save(update_fields=['balance_hold'])
                        wallet_type = 'BALANCE_HOLD'
                        description = f'Hold profit (accrual) from {investment.product.name} investment'
                    else:
                        current_balance = user.balance
                        user.balance = current_balance + daily_profit
                        user.save(update_fields=['balance'])
                        wallet_type = 'BALANCE'
                        description = f'Automatic profit from {investment.product.name} investment'
                    
                    # Create profit transaction
                    profit_transaction = Transaction.objects.create(
                        user=user,
                        product=investment.product,
                        type='INTEREST',
                        amount=daily_profit,
                        description=description,
                        status='COMPLETED',
                        wallet_type=wallet_type,
                        related_transaction=investment.transaction,
                        trx_id=f'AUTO-{_now_in_zone(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
                    )
                    
                    # Process rebate commissions for profit claims
                    # Call the rebate processing directly without viewset
                    self._process_profit_rebates(user, investment.product, daily_profit, profit_transaction)
                    
                    # Update investment
                    investment.last_claim_time = timezone.now()
                    investment.next_claim_time = investment.calculate_next_claim_time()
                    investment.total_claimed_profit += daily_profit
                    
                    # Update claim tracking fields
                    investment.claims_count += 1
                    investment.total_claimed_amount += daily_profit
                    investment.last_claim_amount = daily_profit
                    
                    # Set first claim time if this is the first claim
                    if investment.first_claim_time is None:
                        investment.first_claim_time = timezone.now()
                    
                    # Update claims remaining
                    investment.claims_remaining = max(0, investment.duration_days - investment.claims_count)
                    
                    # Update remaining days based on actual time passed
                    investment.update_remaining_days()
                    
                    investment.save()
                    
                    # If HOLD method and investment completed, release held profits and principal
                    if investment.product.profit_method == 'hold' and investment.status == 'COMPLETED':
                        release_amount = investment.total_claimed_profit
                        if release_amount and release_amount > 0:
                            # Move from balance_hold to balance
                            user.refresh_from_db(fields=['balance', 'balance_hold'])
                            if user.balance_hold >= release_amount:
                                user.balance_hold -= release_amount
                            else:
                                release_amount = max(0, user.balance_hold)
                                user.balance_hold = 0
                            user.balance += release_amount
                            user.save(update_fields=['balance', 'balance_hold'])
                            # Record release transaction
                            Transaction.objects.create(
                                user=user,
                                product=investment.product,
                                type='TRANSFER',
                                amount=release_amount,
                                description=f'Transfer profit from balance hold to balance at maturity for {investment.product.name}',
                                status='COMPLETED',
                                wallet_type='BALANCE',
                                related_transaction=profit_transaction,
                                trx_id=f'REL-{_now_in_zone(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
                            )
                        # Return principal to user's wallet regardless of product flag
                        try:
                            original_trx = investment.transaction
                            wallet_type = original_trx.wallet_type if original_trx else 'BALANCE'
                            if wallet_type == 'BALANCE':
                                user.balance += investment.total_amount
                                user.save(update_fields=['balance'])
                            elif wallet_type == 'BALANCE_DEPOSIT':
                                user.balance_deposit += investment.total_amount
                                user.save(update_fields=['balance_deposit'])
                            Transaction.objects.create(
                                user=user,
                                product=investment.product,
                                upline_user=None,
                                trx_id=f'INVRET-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}',
                                type='RETURN',
                                amount=investment.total_amount,
                                description=f'Principal return at maturity for {investment.product.name}',
                                status='COMPLETED',
                                wallet_type=wallet_type,
                                related_transaction=investment.transaction,
                            )
                            investment.principal_returned = True
                            investment.save(update_fields=['principal_returned'])
                        except Exception as e:
                            logger.error(f'Failed to return principal at maturity: {e}')
                    
                    # Create ClaimHistory record
                    from products.models import ClaimHistory
                    ClaimHistory.objects.create(
                        investment=investment,
                        user=user,
                        claim_amount=daily_profit,
                        claim_type='auto',
                        status='completed',
                        claim_number=investment.claims_count,
                        remaining_days_at_claim=investment.remaining_days,
                        total_claimed_before=investment.total_claimed_profit - daily_profit,
                        transaction=profit_transaction,
                        notes=f'Automatic profit from {investment.product.name}'
                    )
                    
                    processed_count += 1
                    if not quiet:
                        self.stdout.write(
                            f"✅ Processed: {user.phone} - {investment.product.name} "
                            f"(Profit: {format_currency(daily_profit)})"
                        )
                    
                    # Log successful processing
                    logger.info(f"Processed automatic profit: {user.phone} - {investment.product.name} - {format_currency(daily_profit)}")
                    
            except Exception as e:
                error_count += 1
                error_msg = f"Error processing {investment.user.phone} - {investment.product.name}: {str(e)}"
                if not quiet:
                    self.stdout.write(self.style.ERROR(f"❌ {error_msg}"))
                logger.error(error_msg)
        
        # Summary
        self.stdout.write("\n" + "="*50)
        if dry_run:
            if not quiet:
                self.stdout.write(self.style.SUCCESS(f"🔍 DRY RUN SUMMARY:"))
                self.stdout.write(f"📈 Would process: {processed_count} investments")
        else:
            if not quiet:
                self.stdout.write(self.style.SUCCESS(f"🎉 PROCESSING COMPLETE:"))
                self.stdout.write(f"📈 Processed: {processed_count} investments")
        
        if not quiet:
            self.stdout.write(f"⏭️  Skipped: {skipped_count} investments")
            self.stdout.write(f"❌ Errors: {error_count} investments")
            self.stdout.write("="*50)
        
        # Log summary untuk monitoring
        logger.info(f"Automatic profit processing completed - Processed: {processed_count}, Skipped: {skipped_count}, Errors: {error_count}")
    
    def _process_profit_rebates(self, claimer, product, profit_amount, original_transaction):
        """Process rebate commissions for upline users based on profit claims"""
        if not hasattr(claimer, 'referral_by') or not claimer.referral_by:
            return

        current_user = claimer.referral_by
        level = 1

        # Process each upline level
        while current_user and level <= 5:  # Max 5 levels
            rebate_rate = getattr(product, f'profit_rebate_level_{level}', 0)

            if rebate_rate <= 0:
                current_user = getattr(current_user, 'referral_by', None)
                level += 1
                continue

            # Optional rule: require upline to own the same product
            if getattr(product, 'require_upline_ownership_for_commissions', False):
                if not Investment.objects.filter(user=current_user, product=product, status='ACTIVE').exists():
                    current_user = getattr(current_user, 'referral_by', None)
                    level += 1
                    continue

            # Calculate rebate amount - ALWAYS USE PERCENTAGE
            # Profit commission is always percentage of profit amount
            rebate_amount = profit_amount * (Decimal(str(rebate_rate)) / 100)

            if rebate_amount > 0:
                # Profit commission always goes to main balance (BALANCE wallet)
                current_balance = current_user.balance
                current_user.balance = current_balance + rebate_amount
                current_user.save()

                # Create rebate transaction
                Transaction.objects.create(
                    user=current_user,
                    product=product,
                    upline_user=claimer,  # The claimer is the source of this commission
                    type='PROFIT_COMMISSION',
                    amount=rebate_amount,
                    description=f'Profit rebate L{level} from {claimer.phone} - {product.name}',
                    status='COMPLETED',
                    wallet_type='BALANCE',
                    commission_level=level,
                    related_transaction=original_transaction,
                    trx_id=f'PRB-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
                )

            # Move to next upline level
            current_user = getattr(current_user, 'referral_by', None)
            level += 1
