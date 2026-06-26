from django import forms
from .models import Mission


class MissionAdminForm(forms.ModelForm):
    referral_levels_field = forms.MultipleChoiceField(
        choices=[('1', 'Level 1'), ('2', 'Level 2'), ('3', 'Level 3')],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Pilih level downline yang dihitung dalam misi referral/purchase/service.'
    )

    class Meta:
        model = Mission
        fields = [
            'title', 'description', 'type', 'is_active', 'is_repeatable', 'level',
            'requirement', 'reward', 'reward_balance_type'
        ]
        labels = {
            'title': 'Judul Misi',
            'description': 'Deskripsi',
            'type': 'Jenis Misi',
            'is_active': 'Aktif',
            'is_repeatable': 'Dapat diklaim berulang',
            'level': 'Level (opsional)',
            'requirement': 'Ambang Progres',
            'reward': 'Nominal Hadiah',
            'reward_balance_type': 'Dompet Hadiah',
        }
        help_texts = {
            'title': 'Judul singkat misi untuk tampil di admin dan aplikasi.',
            'description': 'Deskripsi singkat misi yang akan tampil di aplikasi.',
            'type': 'Jenis misi: referral (jumlah downline), purchase (downline punya investasi), purchase_self (pembelian/aktivasi oleh user sendiri), service (downline pernah klaim profit), service_self (klaim profit oleh user sendiri), deposit (downline memiliki deposit), deposit_self (total nominal deposit oleh user sendiri), withdrawal (jumlah penarikan selesai oleh user).',
            'is_active': 'Jika aktif, misi akan muncul dan bisa dihitung progresnya.',
            'is_repeatable': 'Jika diaktifkan, misi dapat diklaim berkali-kali setiap kelipatan requirement tercapai.',
            'level': 'Level kesulitan/tingkat misi (opsional). Tidak memengaruhi perhitungan.',
            'requirement': 'Ambang batas progres (contoh: 20 berarti perlu 20 orang/progress sesuai tipe misi).',
            'reward': 'Nominal hadiah per klaim. Untuk misi repeatable dikali jumlah klaim (times).',
            'reward_balance_type': 'Dompet tujuan hadiah: balance atau balance_deposit.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Inisialisasi nilai awal checkbox dari referral_levels
        levels = []
        try:
            levels = self.instance.referral_levels or []
        except Exception:
            levels = []
        # Set initial sebagai string agar cocok dengan choices
        self.fields['referral_levels_field'].initial = [str(l) for l in levels]
        self.fields['referral_levels_field'].label = 'Level downline yang dihitung'
        self.fields['referral_levels_field'].help_text = (
            'Centang level downline yang masuk perhitungan progres misi: Level 1, Level 2, Level 3. '
            'Hanya berlaku untuk tipe referral/purchase/service/deposit (downline). Tidak berlaku untuk withdrawal, service_self, purchase_self, atau deposit_self.'
        )

    def clean_requirement(self):
        req = self.cleaned_data.get('requirement')
        if req is None or req <= 0:
            raise forms.ValidationError('Requirement harus lebih dari 0.')
        return req

    def clean_reward(self):
        reward = self.cleaned_data.get('reward')
        if reward is None or reward <= 0:
            raise forms.ValidationError('Reward harus lebih dari 0.')
        return reward

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Konversi pilihan checkbox ke list integer [1,2,3]
        selected = self.cleaned_data.get('referral_levels_field') or []
        try:
            instance.referral_levels = sorted([int(s) for s in selected if s in {'1', '2', '3'}])
        except Exception:
            instance.referral_levels = []
        if commit:
            instance.save()
        return instance
