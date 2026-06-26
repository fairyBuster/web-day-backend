from django import forms
from .models import Product
from accounts.models import RankLevel

class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'image': forms.FileInput(attrs={'accept': 'image/*'}),
            'description': forms.Textarea(attrs={'rows': 4}),
            'specifications': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Clarify duration unit as days
        if 'duration' in self.fields:
            self.fields['duration'].label = 'Duration (days)'
            self.fields['duration'].help_text = 'Isi dalam hari. Contoh: 24 = 24 hari (klaim harian sebanyak 24x).'
        # Clarify claim reset hours usage
        if 'claim_reset_hours' in self.fields:
            self.fields['claim_reset_hours'].help_text = 'Interval jam untuk mode Reset after purchase (opsional).'
        if 'min_required_rank' in self.fields:
            levels = RankLevel.objects.all().order_by('rank')
            choices = [('', '— pilih rank —')] + [(str(l.rank), f"{l.rank} - {l.title} (≥ {l.missions_required_total})") for l in levels]
            self.fields['min_required_rank'].widget = forms.Select(choices=choices)
            self.fields['min_required_rank'].label = 'Minimum Rank'
            self.fields['min_required_rank'].help_text = 'Pilih dari RankLevel agar konsisten'

    def clean(self):
        cleaned = super().clean()
        required_product = cleaned.get('required_product')
        if required_product and self.instance and self.instance.pk and required_product.pk == self.instance.pk:
            raise forms.ValidationError('Required product tidak boleh sama dengan produk ini.')
        return cleaned
