from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from .models import Bank, UserBank
from .serializers import BankSerializer, UserBankSerializer, UserBankListSerializer


class BanksListView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'banks_list'

    @extend_schema(
        tags=["User API"],
        description="List bank aktif untuk keperluan withdraw",
        parameters=[
            OpenApiParameter(
                name="currency_code",
                type=str,
                required=False,
                description="Filter kategori currency bank (IDR/USD/EUR/SGD/MYR)",
            )
        ],
        responses={200: OpenApiResponse(response=BankSerializer(many=True))},
    )
    def get(self, request):
        currency_code = (request.query_params.get("currency_code") or "").strip().upper()
        banks = Bank.objects.filter(is_active=True)
        if currency_code:
            banks = banks.filter(currency_code=currency_code)
        banks = banks.order_by('name')
        ser = BankSerializer(banks, many=True)
        return Response(ser.data)


class UserBankView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'banks_user'

    @extend_schema(
        tags=["User API"],
        description="List semua bank milik user saat ini",
        responses={200: OpenApiResponse(response=UserBankListSerializer(many=True))},
    )
    def get(self, request):
        user_banks = UserBank.objects.filter(user=request.user).select_related('bank').order_by('-is_default', 'created_at')
        ser = UserBankListSerializer(user_banks, many=True)
        return Response(ser.data)

    @extend_schema(
        tags=["User API"],
        description="Tambah bank milik user (dengan limit yang bisa dikonfigurasi)",
        request=UserBankSerializer,
        responses={
            201: OpenApiResponse(response=UserBankSerializer),
            400: OpenApiResponse(description="Validation errors")
        },
    )
    def post(self, request):
        ser = UserBankSerializer(data=request.data, context={'request': request})
        ser.is_valid(raise_exception=True)
        obj = ser.save()
        return Response(UserBankSerializer(obj).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["User API"],
        description="Edit bank milik user berdasarkan ID",
        request=UserBankSerializer,
        responses={
            200: OpenApiResponse(response=UserBankSerializer),
            404: OpenApiResponse(description="Bank not found")
        },
    )
    def put(self, request):
        bank_id = request.data.get('id')
        if not bank_id:
            return Response({"detail": "ID bank diperlukan untuk update."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            ub = UserBank.objects.get(id=bank_id, user=request.user)
        except UserBank.DoesNotExist:
            return Response({"detail": "Bank tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        
        ser = UserBankSerializer(ub, data=request.data, partial=True, context={'request': request})
        ser.is_valid(raise_exception=True)
        obj = ser.save()
        return Response(UserBankSerializer(obj).data)


class UserBankDetailView(APIView):
    """View untuk operasi pada bank spesifik"""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'banks_user'

    @extend_schema(
        tags=["User API"],
        description="Hapus bank milik user",
        responses={
            204: OpenApiResponse(description="Bank berhasil dihapus"),
            404: OpenApiResponse(description="Bank not found"),
            400: OpenApiResponse(description="Cannot delete default bank")
        },
    )
    def delete(self, request, pk):
        try:
            ub = UserBank.objects.get(id=pk, user=request.user)
        except UserBank.DoesNotExist:
            return Response({"detail": "Bank tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        
        # Tidak boleh hapus bank default jika masih ada bank lain
        if ub.is_default and UserBank.objects.filter(user=request.user).count() > 1:
            return Response(
                {"detail": "Tidak bisa hapus bank default. Set bank lain sebagai default terlebih dahulu."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        ub.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["User API"],
        description="Set bank sebagai default",
        responses={
            200: OpenApiResponse(response=UserBankSerializer),
            404: OpenApiResponse(description="Bank not found")
        },
    )
    def patch(self, request, pk):
        try:
            ub = UserBank.objects.get(id=pk, user=request.user)
        except UserBank.DoesNotExist:
            return Response({"detail": "Bank tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        
        # Unset default lainnya
        UserBank.objects.filter(user=request.user, is_default=True).update(is_default=False)
        
        # Set sebagai default
        ub.is_default = True
        ub.save()
        
        return Response(UserBankSerializer(ub).data)
