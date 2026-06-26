from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.utils import timezone
from django.db.models import Q
from django.db import transaction
from decimal import Decimal
from decimal import InvalidOperation
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_view, OpenApiParameter, extend_schema, inline_serializer
from .models import Product, Transaction, Investment
from .serializers import ProductListSerializer, ProductDetailSerializer, TransactionSerializer, InvestmentSerializer, ProductPurchaseSerializer, ClaimProfitSerializer, ClaimCashbackSerializer, ClaimPrincipalSerializer
from django.core.files.storage import default_storage
from django.conf import settings
from config import format_currency
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
import uuid
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta

# Tags for API documentation
USER_TAG = "User API"
ADMIN_TAG = "Admin API"


def _now_in_zone(tz):
    now = timezone.now()
    if timezone.is_aware(now):
        return timezone.localtime(now, tz)
    return now

@extend_schema_view(
    list=extend_schema(tags=[USER_TAG]),
    retrieve=extend_schema(tags=[USER_TAG]),
    create=extend_schema(tags=[ADMIN_TAG]),
    update=extend_schema(tags=[ADMIN_TAG]),
    partial_update=extend_schema(tags=[ADMIN_TAG]),
    destroy=extend_schema(tags=[ADMIN_TAG])
)
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    
    def get_throttles(self):
        # Apply scoped throttle only for purchase action; others use global rates
        if getattr(self, 'action', None) == 'purchase_product':
            self.throttle_scope = 'products_purchase'
        else:
            if hasattr(self, 'throttle_scope'):
                delattr(self, 'throttle_scope')
        return super().get_throttles()
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductListSerializer
    permission_classes = [IsAuthenticated]
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()
    
    def get_queryset(self):
        """
        Override get_queryset to:
        - Show only active products for regular users in list view
        - Allow admin to see all products
        - Show full details for specific product when accessed directly
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        # If it's a detail view (retrieve), return the product regardless of status
        if self.action == 'retrieve':
            return queryset
            
        # For list view, filter active products for regular users
        if not user.is_staff:
            queryset = queryset.filter(status=1)

        params = self.request.query_params

        min_price_raw = (params.get('min_price') or '').strip()
        max_price_raw = (params.get('max_price') or '').strip()
        min_duration_raw = (params.get('min_duration') or '').strip()
        max_duration_raw = (params.get('max_duration') or '').strip()

        min_price = None
        max_price = None
        min_duration = None
        max_duration = None

        if min_price_raw:
            try:
                min_price = Decimal(min_price_raw)
            except InvalidOperation:
                raise ValidationError({'min_price': 'min_price harus berupa angka.'})
        if max_price_raw:
            try:
                max_price = Decimal(max_price_raw)
            except InvalidOperation:
                raise ValidationError({'max_price': 'max_price harus berupa angka.'})
        if min_duration_raw:
            try:
                min_duration = int(min_duration_raw)
            except ValueError:
                raise ValidationError({'min_duration': 'min_duration harus berupa integer.'})
        if max_duration_raw:
            try:
                max_duration = int(max_duration_raw)
            except ValueError:
                raise ValidationError({'max_duration': 'max_duration harus berupa integer.'})

        if min_price is not None and min_price < 0:
            raise ValidationError({'min_price': 'min_price tidak boleh kurang dari 0.'})
        if max_price is not None and max_price < 0:
            raise ValidationError({'max_price': 'max_price tidak boleh kurang dari 0.'})
        if min_duration is not None and min_duration < 0:
            raise ValidationError({'min_duration': 'min_duration tidak boleh kurang dari 0.'})
        if max_duration is not None and max_duration < 0:
            raise ValidationError({'max_duration': 'max_duration tidak boleh kurang dari 0.'})

        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValidationError({'min_price': 'min_price tidak boleh lebih besar dari max_price.'})
        if min_duration is not None and max_duration is not None and min_duration > max_duration:
            raise ValidationError({'min_duration': 'min_duration tidak boleh lebih besar dari max_duration.'})

        if min_price is not None:
            queryset = queryset.filter(price__gte=min_price)
        if max_price is not None:
            queryset = queryset.filter(price__lte=max_price)
        if min_duration is not None:
            queryset = queryset.filter(duration__gte=min_duration)
        if max_duration is not None:
            queryset = queryset.filter(duration__lte=max_duration)

        return queryset

    @extend_schema(
        tags=[USER_TAG],
        parameters=[
            OpenApiParameter(name='min_price', type=OpenApiTypes.NUMBER, description='Filter by minimum price (price >= min_price)'),
            OpenApiParameter(name='max_price', type=OpenApiTypes.NUMBER, description='Filter by maximum price (price <= max_price)'),
            OpenApiParameter(name='min_duration', type=OpenApiTypes.INT, description='Filter by minimum duration in days (duration >= min_duration)'),
            OpenApiParameter(name='max_duration', type=OpenApiTypes.INT, description='Filter by maximum duration in days (duration <= max_duration)'),
        ],
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name='ProductListResponse',
                    fields={
                        'count': serializers.IntegerField(),
                        'results': ProductListSerializer(many=True),
                    },
                ),
                description='List of products with range filtering'
            )
        },
        description="""
        Get list of active products. For regular users, only shows active products.
        For admin users, shows all products.

        Use filters to narrow down results by price and duration range.
        """
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })
    
    @extend_schema(
        tags=[USER_TAG],
        request=ProductPurchaseSerializer,
        responses={
            201: OpenApiResponse(
                response=InvestmentSerializer,
                description='Product purchased successfully'
            ),
            400: OpenApiResponse(
                description='Invalid purchase data or insufficient balance'
            )
        },
        description='Purchase a product and create an investment'
    )
    @action(detail=False, methods=['post'], url_path='purchase')
    def purchase_product(self, request):
        serializer = ProductPurchaseSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        product_id = serializer.validated_data['product_id']
        quantity = serializer.validated_data['quantity']
        
        # Use database transaction for atomicity
        with transaction.atomic():
            # Lock the user and product rows to prevent race conditions
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            # Select for update to lock the user row (for balance check)
            user = User.objects.select_for_update().get(id=request.user.id)
            # Select for update to lock the product row (for stock management)
            product = Product.objects.select_for_update().get(id=product_id)
            
            required_product = getattr(product, 'required_product', None)
            if required_product:
                if required_product.id == product.id:
                    return Response({
                        'error': 'Konfigurasi produk tidak valid (required_product sama dengan produk ini).'
                    }, status=status.HTTP_400_BAD_REQUEST)
                if not Investment.objects.filter(user=user, product=required_product).exists():
                    return Response({
                        'error': f'Anda harus memiliki produk "{required_product.name}" terlebih dahulu sebelum membeli produk ini.'
                    }, status=status.HTTP_400_BAD_REQUEST)

            required_golongan = (getattr(product, 'required_golongan', None) or '').strip()
            if required_golongan:
                if not Investment.objects.filter(user=user, product__golongan=required_golongan).exists():
                    return Response({
                        'error': f'Anda harus sudah membeli produk golongan "{required_golongan}" terlebih dahulu sebelum membeli produk ini.'
                    }, status=status.HTTP_400_BAD_REQUEST)

            total_amount = product.price * quantity
            
            # Check user balance based on product's balance source
            balance_field = 'balance' if product.balance_source == 'balance' else 'balance_deposit'
            current_balance = getattr(user, balance_field)
            
            if current_balance < total_amount:
                return Response({
                    'error': f'Insufficient {balance_field.replace("_", " ").title()}. Required: {format_currency(total_amount)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Re-validate purchase limit inside the lock
            existing_investments = Investment.objects.filter(
                user=user, 
                product=product
            ).count()
            
            if existing_investments >= product.purchase_limit:
                 return Response({
                    'error': f'Batas pembelian tercapai. Anda hanya bisa membeli produk ini {product.purchase_limit} kali. Saat ini sudah {existing_investments} kali.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Re-validate stock inside lock
            if product.stock_enabled and product.stock < quantity:
                return Response({
                    'error': f'Stok tidak mencukupi. Tersedia: {product.stock}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Deduct balance
            setattr(user, balance_field, current_balance - total_amount)
            user.save()
            
            # Create purchase transaction
            purchase_transaction = Transaction.objects.create(
                user=user,
                product=product,
                type='INVESTMENTS',
                amount=total_amount,
                description=f'Purchase {product.name} (x{quantity})',
                status='COMPLETED',
                wallet_type=product.balance_source.upper(),
                investment_quantity=quantity,
                trx_id=f'PUR-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
            )
            
            # Update product stock if enabled
            if product.stock_enabled:
                product.stock -= quantity
                product.save()
            
            # Create investment
            # Interpret product.duration as days for investment duration
            expires_at = timezone.now() + timezone.timedelta(days=product.duration)
            
            investment = Investment.objects.create(
                user=user,
                product=product,
                transaction=purchase_transaction,
                quantity=quantity,
                total_amount=total_amount,
                profit_type=product.profit_type,
                profit_rate=product.profit_rate,
                profit_random_min=getattr(product, 'profit_random_min', None),
                profit_random_max=getattr(product, 'profit_random_max', None),
                profit_method=product.profit_method,
                claim_reset_mode=product.claim_reset_mode,
                duration_days=product.duration,
                remaining_days=product.duration,
                expires_at=expires_at,
                status='ACTIVE'
            )
            
            # Set next claim time for both manual and auto based on reset mode
            investment.next_claim_time = investment.calculate_next_claim_time()
            investment.save()
            
            # Process rebate commissions for upline users
            self._process_purchase_rebates(user, product, total_amount, purchase_transaction)

            try:
                from roulette.services import grant_tickets_for_level1_purchase
                grant_tickets_for_level1_purchase(user, purchase_transaction)
            except Exception:
                pass
            
            # Cashback processing disabled - cashback must be claimed manually via API
            # self._process_cashback(user, product, total_amount, purchase_transaction)
        
        return Response(
            InvestmentSerializer(investment).data,
            status=status.HTTP_201_CREATED
        )
    
    def _process_purchase_rebates(self, buyer, product, purchase_amount, original_transaction):
        """Process rebate commissions for upline users based on purchase amount"""
        if not hasattr(buyer, 'referral_by') or not buyer.referral_by:
            return
    
        current_user = buyer.referral_by
        level = 1
    
        # Process each upline level
        while current_user and level <= 5:
            rebate_rate = getattr(product, f'purchase_rebate_level_{level}', 0)
            
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
            # Purchase commission is always percentage of purchase amount
            rebate_amount = purchase_amount * (Decimal(str(rebate_rate)) / 100)
            
            if rebate_amount > 0:
                # Purchase commission always goes to main balance (BALANCE wallet)
                current_balance = current_user.balance
                current_user.balance = current_balance + rebate_amount
                current_user.save()
                
                # Create rebate transaction
                Transaction.objects.create(
                    user=current_user,
                    product=product,
                    upline_user=buyer,  # The buyer is the source of this commission
                    type='PURCHASE_COMMISSION',
                    amount=rebate_amount,
                    description=f'Purchase rebate L{level} from {buyer.phone} - {product.name}',
                    status='COMPLETED',
                    wallet_type='BALANCE',
                    commission_level=level,
                    related_transaction=original_transaction,
                    trx_id=f'REB-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
                )
            
            # Move to next upline level
            current_user = getattr(current_user, 'referral_by', None)
            level += 1

    @extend_schema(
        tags=[USER_TAG],
        request=ClaimCashbackSerializer,
        responses={
            200: OpenApiResponse(
                description='Cashback claimed successfully',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'message': 'Cashback claimed successfully',
                            'cashback_amount': '25000.00',
                            'cashback_percentage': '12.50',
                            'transaction_id': 'CBK-20241225120000-ABC123',
                            'balance': '1025000.00',
                            'wallet_type': 'BALANCE'
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Cannot claim cashback (already claimed, not eligible, etc.)'
            )
        },
        description='Manually claim cashback from a completed purchase transaction'
    )
    @action(detail=False, methods=['post'], url_path='claim-cashback')
    def claim_cashback(self, request):
        serializer = ClaimCashbackSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        transaction_id = serializer.validated_data['transaction_id']
        
        # Get the purchase transaction
        purchase_transaction = Transaction.objects.get(
            trx_id=transaction_id,
            user=request.user,
            type='INVESTMENTS',
            status='COMPLETED'
        )
        
        product = purchase_transaction.product
        
        # Calculate cashback amount
        cashback_amount = product.calculate_cashback(purchase_transaction.amount)
        
        if cashback_amount <= 0:
            return Response({
                'error': 'Tidak ada cashback untuk transaksi ini',
                'cashback_percentage': str(product.cashback_percentage),
                'purchase_amount': str(purchase_transaction.amount)
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Use database transaction for atomicity
        with transaction.atomic():
            # Cashback always goes to main balance (BALANCE wallet)
            current_balance = request.user.balance
            
            # Add cashback to user main balance
            request.user.balance = current_balance + cashback_amount
            request.user.save()
            
            # Create cashback transaction
            cashback_transaction = Transaction.objects.create(
                user=request.user,
                product=product,
                type='CASHBACK',
                amount=cashback_amount,
                description=f'Manual cashback claim {product.cashback_percentage}% from {product.name} purchase',
                status='COMPLETED',
                wallet_type='BALANCE',
                related_transaction=purchase_transaction,
                trx_id=f'CBK-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
            )
        
        # Refresh user data
        request.user.refresh_from_db()
        
        return Response({
            'message': 'Cashback berhasil diklaim',
            'cashback_amount': str(cashback_amount),
            'cashback_percentage': str(product.cashback_percentage),
            'transaction_id': cashback_transaction.trx_id,
            'balance': str(request.user.balance),
            'wallet_type': 'BALANCE',
            'purchase_transaction_id': purchase_transaction.trx_id,
            'product_name': product.name
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='media-health', permission_classes=[AllowAny])
    def media_health(self, request):
        queryset = Product.objects.all()
        missing = []
        present = 0
        with_images = 0
        for p in queryset:
            img = getattr(p, 'image', None)
            if img:
                with_images += 1
                name = getattr(img, 'name', None)
                exists = False
                url = None
                try:
                    exists = bool(name) and default_storage.exists(name)
                    url = img.url if exists else (settings.MEDIA_URL + name if name else None)
                except Exception:
                    exists = False
                    url = None
                if exists:
                    present += 1
                else:
                    missing.append({
                        'product_id': p.id,
                        'image_field': name,
                        'expected_url': request.build_absolute_uri(url) if url else None,
                    })
        return Response({
            'total_products': queryset.count(),
            'products_with_images': with_images,
            'present_images_count': present,
            'missing_images_count': len(missing),
            'missing_images': missing,
        })

    def _process_cashback(self, buyer, product, purchase_amount, original_transaction):
        """Process cashback for the buyer if enabled on the product"""
        if not product.cashback_enabled or product.cashback_percentage <= 0:
            return
        
        # Calculate cashback amount
        cashback_amount = product.calculate_cashback(purchase_amount)
        
        if cashback_amount <= 0:
            return
        
        # Cashback always goes to main balance (BALANCE wallet)
        current_balance = buyer.balance
        
        # Add cashback to user main balance
        buyer.balance = current_balance + cashback_amount
        buyer.save()
        
        # Create cashback transaction
        now_wib = _now_in_zone(ZoneInfo("Asia/Jakarta"))
        Transaction.objects.create(
            user=buyer,
            product=product,
            type='CREDIT',
            amount=cashback_amount,
            description=f'Cashback {product.cashback_percentage}% from {product.name} purchase',
            status='COMPLETED',
            wallet_type='BALANCE',
            related_transaction=original_transaction,
            trx_id=f'CBK-{now_wib.strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
        )

@extend_schema_view(
    list=extend_schema(tags=[USER_TAG]),
    retrieve=extend_schema(tags=[USER_TAG]),
    create=extend_schema(tags=[USER_TAG]),
    update=extend_schema(tags=[ADMIN_TAG]),
    partial_update=extend_schema(tags=[ADMIN_TAG]),
    destroy=extend_schema(tags=[ADMIN_TAG])
)
class TransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_throttles(self):
        # Use scoped throttle only for write operations
        if getattr(self, 'action', None) in ['create']:
            self.throttle_scope = 'transactions'
        else:
            if hasattr(self, 'throttle_scope'):
                delattr(self, 'throttle_scope')
        return super().get_throttles()
    
    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            qs = Transaction.objects.all()
        else:
            qs = Transaction.objects.filter(user=user)
        return qs.select_related('user', 'product', 'upline_user', 'related_transaction').prefetch_related(
            'related_withdrawal__bank_account__bank',
            'related_withdrawal__withdrawal_service'
        )
    
    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()
    
    def perform_create(self, serializer):
        # Generate unique transaction ID
        now_wib = _now_in_zone(ZoneInfo("Asia/Jakarta"))
        trx_id = f"TRX{now_wib.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4]}"
        serializer.save(user=self.request.user, trx_id=trx_id)
    
    @extend_schema(
        tags=[USER_TAG],
        parameters=[
            OpenApiParameter(
                name='type',
                type=str,
                enum=[
                    'CREDIT',
                    'BONUS',
                    'DEBIT',
                    'TRANSFER',
                    'DEPOSIT',
                    'WITHDRAW',
                    'PURCHASE_COMMISSION',
                    'PROFIT_COMMISSION',
                    'INTEREST',
                    'INVESTMENTS',
                    'MISSIONS',
                    'VOUCHER',
                    'ATTENDANCE',
                    'CASHBACK',
                    'CASHBACK_DEPOSIT',
                    'REJECT',
                    'RETURN',
                    'HOLD_RELEASE',
                ],
                description='Filter by transaction type',
                required=False,
            ),
            OpenApiParameter(name='status', type=str, description='Filter by status'),
            OpenApiParameter(
                name='wallet_type',
                type=str,
                enum=['BALANCE', 'BALANCE_DEPOSIT', 'BALANCE_HOLD', 'BALANCE_CASHBACK'],
                description='Filter by wallet type',
                required=False,
            ),
            OpenApiParameter(name='start_date', type=str, description='Filter by start date (YYYY-MM-DD)'),
            OpenApiParameter(name='end_date', type=str, description='Filter by end date (YYYY-MM-DD)'),
            OpenApiParameter(name='page', type=int, description='A page number within the paginated result set.'),
        ],
        responses={
            200: OpenApiResponse(
                response=TransactionSerializer(many=True),
                description='List of user transactions'
            )
        },
        description='Get list of transactions. Regular users can only see their own transactions. Admin can see all transactions.'
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        # Apply filters
        trx_type = request.query_params.get('type')
        status = request.query_params.get('status')
        wallet_type = request.query_params.get('wallet_type')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if trx_type:
            queryset = queryset.filter(type=trx_type)
        if status:
            queryset = queryset.filter(status=status)
        if wallet_type:
            queryset = queryset.filter(wallet_type=wallet_type)
        tz = ZoneInfo('Asia/Jakarta')
        if start_date:
            try:
                sd = datetime.strptime(start_date, '%Y-%m-%d').date()
                start_dt = datetime.combine(sd, time.min, tz)
                queryset = queryset.filter(created_at__gte=start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                ed = datetime.strptime(end_date, '%Y-%m-%d').date()
                end_exclusive = datetime.combine(ed + timedelta(days=1), time.min, tz)
                queryset = queryset.filter(created_at__lt=end_exclusive)
            except ValueError:
                pass
        
        queryset = queryset.order_by('-created_at')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(tags=[USER_TAG]),
    retrieve=extend_schema(tags=[USER_TAG]),
    create=extend_schema(tags=[ADMIN_TAG]),
    update=extend_schema(tags=[ADMIN_TAG]),
    partial_update=extend_schema(tags=[ADMIN_TAG]),
    destroy=extend_schema(tags=[ADMIN_TAG])
)
class InvestmentViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_throttles(self):
        # Apply scoped throttle only for profit-claim; others use global rates
        if getattr(self, 'action', None) in {'claim_profit', 'claim_profit_all'}:
            self.throttle_scope = 'investments_claim_profit'
        else:
            if hasattr(self, 'throttle_scope'):
                delattr(self, 'throttle_scope')
        return super().get_throttles()
    
    def get_queryset(self):
        user = self.request.user
        queryset = Investment.objects.all() if user.is_staff else Investment.objects.filter(user=user)
        return queryset.select_related('user', 'product', 'transaction')
    
    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy', 'create']:
            return [IsAdminUser()]
        return super().get_permissions()
    
    @extend_schema(
        tags=[USER_TAG],
        parameters=[
            OpenApiParameter(name='status', type=str, description='Filter by status (ACTIVE/COMPLETED/EXPIRED/CANCELLED)'),
            OpenApiParameter(name='product_id', type=int, description='Filter by product ID'),
        ],
        responses={
            200: OpenApiResponse(
                response=InvestmentSerializer(many=True),
                description='List of user investments'
            )
        },
        description='Get list of investments. Regular users can only see their own investments. Admin can see all investments.'
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        # Apply filters
        investment_status = request.query_params.get('status')
        product_id = request.query_params.get('product_id')
        
        if investment_status:
            queryset = queryset.filter(status=investment_status)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        # Update remaining days for all active investments
        # Optimize by iterating over the prefetched queryset to avoid extra DB query
        investments = list(queryset)
        for investment in investments:
            if investment.status == 'ACTIVE':
                investment.update_remaining_days()
        
        serializer = self.get_serializer(investments, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=[USER_TAG],
        parameters=[
            OpenApiParameter(name='status', type=str, description='Filter berdasarkan status transaksi'),
            OpenApiParameter(name='wallet_type', type=str, description='Filter berdasarkan wallet (BALANCE/BALANCE_DEPOSIT)'),
            OpenApiParameter(name='start_date', type=str, description='Tanggal awal (YYYY-MM-DD) untuk filter created_at'),
            OpenApiParameter(name='end_date', type=str, description='Tanggal akhir (YYYY-MM-DD) untuk filter created_at'),
            OpenApiParameter(name='product_id', type=int, description='Filter berdasarkan product ID'),
            OpenApiParameter(name='page', type=int, description='A page number within the paginated result set.'),
        ],
        responses={
            200: OpenApiResponse(
                response=TransactionSerializer(many=True),
                description='List transaksi bertipe INTEREST untuk investasi'
            )
        },
        description='Ambil daftar transaksi dengan type INTEREST milik pengguna. Admin melihat semua.'
    )
    @action(detail=False, methods=['get'], url_path='transaction')
    def interest_transactions(self, request):
        user = request.user
        # Base queryset restricted by role
        if user.is_staff:
            queryset = Transaction.objects.filter(type='INTEREST')
        else:
            queryset = Transaction.objects.filter(user=user, type='INTEREST')

        # Filters
        status_param = request.query_params.get('status')
        wallet_type = request.query_params.get('wallet_type')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        product_id = request.query_params.get('product_id')

        if status_param:
            queryset = queryset.filter(status=status_param)
        if wallet_type:
            queryset = queryset.filter(wallet_type=wallet_type)
        tz = ZoneInfo('Asia/Jakarta')
        if start_date:
            try:
                sd = datetime.strptime(start_date, '%Y-%m-%d').date()
                start_dt = datetime.combine(sd, time.min, tz)
                queryset = queryset.filter(created_at__gte=start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                ed = datetime.strptime(end_date, '%Y-%m-%d').date()
                end_exclusive = datetime.combine(ed + timedelta(days=1), time.min, tz)
                queryset = queryset.filter(created_at__lt=end_exclusive)
            except ValueError:
                pass
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        queryset = queryset.select_related('user', 'product', 'upline_user').prefetch_related('related_withdrawal__bank_account__bank', 'related_withdrawal__withdrawal_service').order_by('-created_at')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=[USER_TAG],
        parameters=[
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                description='A page number within the paginated result set.',
                required=False,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=TransactionSerializer(many=True),
                description='List transaksi INTEREST terbaru yang terkait dengan investasi ini',
            )
        },
        description='Ambil transaksi INTEREST terbaru untuk 1 investasi (berdasarkan purchase transaction / rentang waktu).'
    )
    @action(detail=True, methods=['get'], url_path='interest-transactions')
    def investment_interest_transactions(self, request, pk=None):
        investment = self.get_object()

        base_qs = Transaction.objects.filter(
            user=investment.user,
            product=investment.product,
            type='INTEREST',
        )

        purchase_trx = getattr(investment, 'transaction', None)
        if purchase_trx:
            next_purchase = Transaction.objects.filter(
                user=investment.user,
                product=investment.product,
                type='INVESTMENTS',
                created_at__gt=purchase_trx.created_at,
            ).order_by('created_at').first()

            start_dt = purchase_trx.created_at
            if next_purchase:
                end_dt = next_purchase.created_at
                qs = base_qs.filter(
                    Q(related_transaction=purchase_trx) |
                    (Q(related_transaction__isnull=True) & Q(created_at__gte=start_dt) & Q(created_at__lt=end_dt))
                )
            else:
                qs = base_qs.filter(
                    Q(related_transaction=purchase_trx) |
                    (Q(related_transaction__isnull=True) & Q(created_at__gte=start_dt))
                )
        else:
            qs = base_qs.filter(created_at__gte=investment.created_at)

        qs = qs.select_related('user', 'product', 'upline_user', 'related_transaction').order_by('-created_at')
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        tags=[USER_TAG],
        request=ClaimProfitSerializer,
        responses={
            200: OpenApiResponse(
                description='Profit claimed successfully',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'message': 'Profit claimed successfully',
                            'claimed_amount': '50000.00',
                            'total_claimed': '150000.00',
                            'remaining_profit': '350000.00',
                            'next_claim_time': '2025-10-06T12:00:00Z'
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Cannot claim profit (already claimed today, expired, etc.)'
            )
        },
        description='Claim daily profit from an active investment'
    )
    @action(detail=False, methods=['post'], url_path='claim-profit')
    def claim_profit(self, request):
        serializer = ClaimProfitSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        investment_id = serializer.validated_data['investment_id']
        investment = Investment.objects.get(id=investment_id, user=request.user)
        
        # Check if this is an automatic profit method investment
        if investment.profit_method == 'auto':
            return Response({
                'error': 'Investasi ini menggunakan pemrosesan profit otomatis. Klaim manual tidak diperbolehkan.',
                'profit_method': 'auto',
                'message': 'Profit diproses otomatis setiap 5 menit oleh sistem.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update remaining days first
        investment.update_remaining_days()
        
        # Check if can claim
        if not investment.can_claim_today():
            reasons = []
            if investment.status != 'ACTIVE':
                reasons.append('Investasi tidak aktif')
            if investment.remaining_days <= 0:
                reasons.append('Investasi kedaluwarsa')
            try:
                from .models import ProfitHolidaySettings
                if ProfitHolidaySettings.is_profit_blocked_today():
                    reasons.append('Hari libur (profit dimatikan)')
            except Exception:
                pass
            if investment.last_claim_time and not investment.can_claim_today():
                reasons.append('Sudah klaim hari ini atau menunggu waktu klaim berikutnya')
            
            return Response({
                'error': 'Tidak bisa klaim profit: ' + ', '.join(reasons),
                'next_claim_time': investment.next_claim_time
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Calculate profit amount
        daily_profit = investment.daily_profit
        
        if daily_profit <= 0:
            return Response({
                'error': 'Tidak ada profit yang bisa diklaim'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Use database transaction for atomicity
        with transaction.atomic():
            # Interest/Income always goes to main balance (BALANCE wallet)
            user = request.user
            current_balance = user.balance
            user.balance = current_balance + daily_profit
            user.save()
            
            # Create profit transaction
            profit_transaction = Transaction.objects.create(
                user=user,
                product=investment.product,
                type='INTEREST',
                amount=daily_profit,
                description=f'Profit claim from {investment.product.name} investment',
                status='COMPLETED',
                wallet_type='BALANCE',
                related_transaction=investment.transaction,
                trx_id=f'CLM-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}'
            )
            
            # Process rebate commissions for profit claims
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
            
            # Update remaining days based on actual time passed (not claim count)
            investment.update_remaining_days()
            
            investment.save()
            
            # Create ClaimHistory record
            from .models import ClaimHistory
            ClaimHistory.objects.create(
                investment=investment,
                user=user,
                claim_amount=daily_profit,
                claim_type='manual',
                status='completed',
                claim_number=investment.claims_count,
                remaining_days_at_claim=investment.remaining_days,
                total_claimed_before=investment.total_claimed_profit - daily_profit,
                transaction=profit_transaction,
                notes=f'Manual profit claim from {investment.product.name}'
            )
        
        return Response({
            'message': 'Profit berhasil diklaim',
            'claimed_amount': str(daily_profit),
            'total_claimed': str(investment.total_claimed_profit),
            'remaining_profit': str(investment.remaining_profit),
            'remaining_days': investment.remaining_days,
            'progress': investment.progress_display,  # Shows "days_passed/total_duration"
            'days_passed': investment.days_passed,
            'next_claim_time': investment.next_claim_time,
            'investment_status': investment.status
        })

    @extend_schema(
        tags=[USER_TAG],
        request=None,
        responses={
            200: OpenApiResponse(
                description='Bulk profit claim processed',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'message': 'Bulk claim diproses',
                            'claimed_count': 2,
                            'skipped_count': 1,
                            'total_claimed_amount': '100000.00',
                            'balance': '1100000.00',
                            'claimed': [
                                {
                                    'investment_id': 10,
                                    'product_id': 3,
                                    'product_name': 'Product A',
                                    'claimed_amount': '50000.00',
                                    'transaction_id': 'CLM-20260509123000-ABC123',
                                    'next_claim_time': '2026-05-10T00:00:00+07:00',
                                }
                            ],
                            'skipped': [
                                {
                                    'investment_id': 11,
                                    'product_id': 4,
                                    'product_name': 'Product B',
                                    'reason': 'Sudah klaim hari ini atau menunggu waktu klaim berikutnya',
                                    'next_claim_time': '2026-05-10T00:00:00+07:00',
                                }
                            ],
                        }
                    )
                ]
            )
        },
        description='Claim profit untuk semua investasi aktif user yang eligible dalam satu request'
    )
    @action(detail=False, methods=['post'], url_path='claim-profit-all')
    def claim_profit_all(self, request):
        User = get_user_model()
        user_id = request.user.id

        claimed = []
        total_claimed = Decimal("0.00")

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user_id)
            investments = (
                Investment.objects.select_for_update()
                .select_related("product", "transaction")
                .filter(user=user, status="ACTIVE")
                .exclude(profit_method="auto")
                .order_by("id")
            )

            for investment in investments:
                investment.update_remaining_days()
                if investment.status != "ACTIVE" or investment.remaining_days <= 0:
                    continue

                if not investment.can_claim_today():
                    continue

                daily_profit = investment.daily_profit
                if daily_profit <= 0:
                    continue

                user.balance = (user.balance or Decimal("0.00")) + daily_profit

                profit_transaction = Transaction.objects.create(
                    user=user,
                    product=investment.product,
                    type="INTEREST",
                    amount=daily_profit,
                    description=f"Profit claim from {investment.product.name} investment",
                    status="COMPLETED",
                    wallet_type="BALANCE",
                    related_transaction=investment.transaction,
                    trx_id=f"CLM-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
                )

                self._process_profit_rebates(user, investment.product, daily_profit, profit_transaction)

                investment.last_claim_time = timezone.now()
                investment.next_claim_time = investment.calculate_next_claim_time()
                investment.total_claimed_profit += daily_profit

                investment.claims_count += 1
                investment.total_claimed_amount += daily_profit
                investment.last_claim_amount = daily_profit

                if investment.first_claim_time is None:
                    investment.first_claim_time = timezone.now()

                investment.claims_remaining = max(0, investment.duration_days - investment.claims_count)
                investment.update_remaining_days()
                investment.save()

                from .models import ClaimHistory
                ClaimHistory.objects.create(
                    investment=investment,
                    user=user,
                    claim_amount=daily_profit,
                    claim_type="manual",
                    status="completed",
                    claim_number=investment.claims_count,
                    remaining_days_at_claim=investment.remaining_days,
                    total_claimed_before=investment.total_claimed_profit - daily_profit,
                    transaction=profit_transaction,
                    notes=f"Manual profit claim from {investment.product.name}",
                )

                total_claimed += daily_profit
                claimed.append(
                    {
                        "investment_id": investment.id,
                        "product_id": investment.product_id,
                        "product_name": investment.product.name if investment.product else None,
                        "claimed_amount": str(daily_profit),
                        "transaction_id": profit_transaction.trx_id,
                        "next_claim_time": investment.next_claim_time,
                    }
                )

            user.save(update_fields=["balance"])

        return Response(
            {
                "message": "Bulk claim diproses",
                "claimed_count": len(claimed),
                "skipped_count": 0,
                "total_claimed_amount": str(total_claimed),
                "balance": str(user.balance),
                "claimed": claimed,
                "skipped": [],
            }
        )

    @extend_schema(
        tags=[USER_TAG],
        responses={
            200: OpenApiResponse(
                description="List investasi yang bisa klaim profit sekarang",
                examples=[
                    OpenApiExample(
                        "Success Response",
                        value={
                            "count": 1,
                            "total_claimable_amount": "50000.00",
                            "items": [
                                {
                                    "investment_id": 10,
                                    "product_id": 3,
                                    "product_name": "Product A",
                                    "claimable_amount": "50000.00",
                                    "wallet_type": "BALANCE",
                                    "next_claim_time": "2026-05-17T00:00:00+07:00",
                                }
                            ],
                        },
                    )
                ],
            )
        },
        description="Ambil hanya investasi user yang eligible untuk klaim profit (can_claim_today) saat ini."
    )
    @action(detail=False, methods=["get"], url_path="claimable-profit")
    def claimable_profit(self, request):
        user = request.user
        investments = (
            Investment.objects.select_related("product", "transaction")
            .filter(user=user, status="ACTIVE")
            .exclude(profit_method="auto")
            .order_by("id")
        )

        items = []
        total = Decimal("0.00")
        for inv in investments:
            inv.update_remaining_days()
            if inv.status != "ACTIVE" or inv.remaining_days <= 0:
                continue
            if not inv.can_claim_today():
                continue
            daily_profit = inv.daily_profit
            if daily_profit <= 0:
                continue
            wallet_type = "BALANCE"
            try:
                if inv.transaction and inv.transaction.wallet_type:
                    wallet_type = inv.transaction.wallet_type
            except Exception:
                pass
            items.append(
                {
                    "investment_id": inv.id,
                    "product_id": inv.product_id,
                    "product_name": inv.product.name if inv.product else None,
                    "claimable_amount": str(daily_profit),
                    "wallet_type": wallet_type,
                    "next_claim_time": inv.get_next_claim_time(),
                }
            )
            total += daily_profit

        return Response(
            {
                "count": len(items),
                "total_claimable_amount": str(total),
                "items": items,
            }
        )
    
    @extend_schema(
        tags=[USER_TAG],
        request=ClaimPrincipalSerializer,
        responses={
            200: OpenApiResponse(
                description='Principal returned successfully',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'message': 'Modal berhasil dikembalikan',
                            'returned_amount': '10000.00',
                            'wallet_type': 'BALANCE',
                            'transaction_id': 'INVRET-20250217120000-ABC123',
                            'balance': '110000.00',
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Cannot return principal (not completed, already returned, not enabled, etc.)'
            )
        },
        description='Manually claim principal return after investment completion'
    )
    @action(detail=False, methods=['post'], url_path='claim-principal')
    def claim_principal(self, request):
        serializer = ClaimPrincipalSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        investment_id = serializer.validated_data['investment_id']
        investment = Investment.objects.select_related('product', 'transaction', 'user').get(id=investment_id, user=request.user)
        
        investment.update_remaining_days()
        investment.refresh_from_db()

        block_reason = investment.get_principal_return_block_reason()
        if block_reason:
            return Response({
                'error': block_reason
            }, status=status.HTTP_400_BAD_REQUEST)
        
        result = investment.return_principal_if_eligible()
        if not result:
            return Response({
                'error': investment.get_principal_return_block_reason() or 'Tidak dapat mengembalikan modal'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'message': 'Modal berhasil dikembalikan',
            'returned_amount': str(result['amount']),
            'wallet_type': result['wallet_type'],
            'transaction_id': result['transaction_id'],
            'balance': str(result['balance']),
            'investment_status': investment.status,
        })
    
    def _process_profit_rebates(self, claimer, product, profit_amount, original_transaction):
        """Process rebate commissions for upline users based on profit claims"""
        if not hasattr(claimer, 'referral_by') or not claimer.referral_by:
            return
    
        current_user = claimer.referral_by
        level = 1
    
        # Process each upline level
        while current_user and level <= 5:
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
