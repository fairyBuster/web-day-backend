from django import forms
from decimal import Decimal
from .models import Voucher


class VoucherAdminForm(forms.ModelForm):
    rank_1 = forms.DecimalField(label='Rank 1 amount', required=False, min_value=0)
    rank_2 = forms.DecimalField(label='Rank 2 amount', required=False, min_value=0)
    rank_3 = forms.DecimalField(label='Rank 3 amount', required=False, min_value=0)
    rank_4 = forms.DecimalField(label='Rank 4 amount', required=False, min_value=0)
    rank_5 = forms.DecimalField(label='Rank 5 amount', required=False, min_value=0)
    rank_6 = forms.DecimalField(label='Rank 6 amount', required=False, min_value=0)

    class Meta:
        model = Voucher
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rr = self.instance.rank_rewards or {}
        for i in range(1, 7):
            key = str(i)
            if key in rr:
                try:
                    self.fields[f'rank_{i}'].initial = Decimal(str(rr[key]))
                except Exception:
                    self.fields[f'rank_{i}'].initial = rr[key]

    def save(self, commit=True):
        instance = super().save(commit=False)
        rr = {}
        for i in range(1, 7):
            val = self.cleaned_data.get(f'rank_{i}')
            if val is not None:
                rr[str(i)] = float(val)
        instance.rank_rewards = rr
        if commit:
            instance.save()
        return instance