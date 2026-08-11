from django.contrib import admin
from django import forms
from django.contrib.admin.widgets import AutocompleteSelect
from .models import RouletteSettings, RoulettePrize, RouletteTicketWallet, RouletteTicketLedger, RouletteSpin


@admin.register(RouletteSettings)
class RouletteSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "is_active",
        "grant_tickets_from_level1_purchase",
        "tickets_per_level1_purchase",
        "grant_tickets_from_self_deposit",
        "tickets_per_completed_deposit",
        "ticket_cost",
        "updated_at",
    )
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Konfigurasi",
            {
                "fields": (
                    "is_active",
                    "grant_tickets_from_level1_purchase",
                    "tickets_per_level1_purchase",
                    "grant_tickets_from_self_deposit",
                    "tickets_per_completed_deposit",
                    "min_deposit_amount_for_tickets",
                    "ticket_cost",
                ),
                "description": (
                    "Atur sumber tiket roulette. Bisa dari pembelian downline level-1 (upline dapat tiket) dan/atau dari deposit sendiri (user dapat tiket). "
                    "Biaya spin memakai ticket_cost."
                ),
            },
        ),
        ("Waktu", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return not RouletteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RoulettePrize)
class RoulettePrizeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "prize_type", "amount", "weight", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active", "prize_type")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Hadiah",
            {
                "fields": ("name", "image", "description", "prize_type", "amount"),
                "description": "Jika prize_type=NONE maka ini zonk. Jika BALANCE/BALANCE_DEPOSIT maka amount akan masuk ke wallet terkait.",
            },
        ),
        (
            "Peluang Menang",
            {
                "fields": ("weight", "is_active", "sort_order"),
                "description": "Peluang = weight / total_weight (total_weight = jumlah weight hadiah aktif). Contoh: Zonk=90, Rp1000=10.",
            },
        ),
        ("Waktu", {"fields": ("created_at", "updated_at")}),
    )


class UserPhoneAutocompleteSelect(AutocompleteSelect):
    """AutocompleteSelect yang menampilkan nomor phone user (bukan email)."""

    def get_label(self, value):
        from accounts.models import User
        user = User.objects.filter(pk=value).first()
        if user:
            return f"{user.phone} | {user.username or user.email}"
        return super().get_label(value)


class RouletteTicketWalletAdminForm(forms.ModelForm):
    class Meta:
        model = RouletteTicketWallet
        fields = "__all__"
        widgets = {
            "user": UserPhoneAutocompleteSelect(
                RouletteTicketWallet._meta.get_field("user"),
                admin.site,
            ),
        }


@admin.register(RouletteTicketWallet)
class RouletteTicketWalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user_display", "balance", "updated_at")
    search_fields = ("user__phone", "user__username", "user__email")
    readonly_fields = ("updated_at",)
    autocomplete_fields = ("user",)
    form = RouletteTicketWalletAdminForm
    list_select_related = ("user",)

    @admin.display(description="User", ordering="user__phone")
    def user_display(self, obj):
        return f"{obj.user.phone} | {obj.user.username or obj.user.email}"

    def save_model(self, request, obj, form, change):
        prev_balance = None
        if change and obj.pk:
            prev_balance = (
                RouletteTicketWallet.objects.filter(pk=obj.pk)
                .values_list("balance", flat=True)
                .first()
            )

        super().save_model(request, obj, form, change)

        if prev_balance is None:
            return

        delta = int(obj.balance or 0) - int(prev_balance or 0)
        if delta:
            RouletteTicketLedger.objects.create(
                user=obj.user,
                delta=delta,
                reason="ADMIN_ADJUST",
            )


@admin.register(RouletteTicketLedger)
class RouletteTicketLedgerAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "delta", "reason", "source_user", "source_transaction", "created_at")
    list_filter = ("reason", "created_at")
    search_fields = ("user__phone", "source_user__phone", "source_transaction__trx_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user", "source_user", "source_transaction")


@admin.register(RouletteSpin)
class RouletteSpinAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "prize", "prize_type", "prize_amount", "transaction", "created_at")
    list_filter = ("prize_type", "created_at")
    search_fields = ("user__phone", "transaction__trx_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user", "prize", "transaction")
