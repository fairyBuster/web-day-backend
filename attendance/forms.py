from django import forms
from decimal import Decimal
from .models import AttendanceSettings


DAILY_ATTENDANCE_PROGRAM_DAYS = 7


class AttendanceSettingsAdminForm(forms.ModelForm):
    MAX_RANK_FIELDS = 50

    rank_1 = forms.DecimalField(label='Rank 1 amount', required=False, min_value=0)
    rank_2 = forms.DecimalField(label='Rank 2 amount', required=False, min_value=0)
    rank_3 = forms.DecimalField(label='Rank 3 amount', required=False, min_value=0)
    rank_4 = forms.DecimalField(label='Rank 4 amount', required=False, min_value=0)
    rank_5 = forms.DecimalField(label='Rank 5 amount', required=False, min_value=0)
    rank_6 = forms.DecimalField(label='Rank 6 amount', required=False, min_value=0)
    rank_7 = forms.DecimalField(label='Rank 7 amount', required=False, min_value=0)
    rank_8 = forms.DecimalField(label='Rank 8 amount', required=False, min_value=0)
    rank_9 = forms.DecimalField(label='Rank 9 amount', required=False, min_value=0)
    rank_10 = forms.DecimalField(label='Rank 10 amount', required=False, min_value=0)
    rank_11 = forms.DecimalField(label='Rank 11 amount', required=False, min_value=0)
    rank_12 = forms.DecimalField(label='Rank 12 amount', required=False, min_value=0)
    rank_13 = forms.DecimalField(label='Rank 13 amount', required=False, min_value=0)
    rank_14 = forms.DecimalField(label='Rank 14 amount', required=False, min_value=0)
    rank_15 = forms.DecimalField(label='Rank 15 amount', required=False, min_value=0)
    rank_16 = forms.DecimalField(label='Rank 16 amount', required=False, min_value=0)
    rank_17 = forms.DecimalField(label='Rank 17 amount', required=False, min_value=0)
    rank_18 = forms.DecimalField(label='Rank 18 amount', required=False, min_value=0)
    rank_19 = forms.DecimalField(label='Rank 19 amount', required=False, min_value=0)
    rank_20 = forms.DecimalField(label='Rank 20 amount', required=False, min_value=0)
    rank_21 = forms.DecimalField(label='Rank 21 amount', required=False, min_value=0)
    rank_22 = forms.DecimalField(label='Rank 22 amount', required=False, min_value=0)
    rank_23 = forms.DecimalField(label='Rank 23 amount', required=False, min_value=0)
    rank_24 = forms.DecimalField(label='Rank 24 amount', required=False, min_value=0)
    rank_25 = forms.DecimalField(label='Rank 25 amount', required=False, min_value=0)
    rank_26 = forms.DecimalField(label='Rank 26 amount', required=False, min_value=0)
    rank_27 = forms.DecimalField(label='Rank 27 amount', required=False, min_value=0)
    rank_28 = forms.DecimalField(label='Rank 28 amount', required=False, min_value=0)
    rank_29 = forms.DecimalField(label='Rank 29 amount', required=False, min_value=0)
    rank_30 = forms.DecimalField(label='Rank 30 amount', required=False, min_value=0)
    rank_31 = forms.DecimalField(label='Rank 31 amount', required=False, min_value=0)
    rank_32 = forms.DecimalField(label='Rank 32 amount', required=False, min_value=0)
    rank_33 = forms.DecimalField(label='Rank 33 amount', required=False, min_value=0)
    rank_34 = forms.DecimalField(label='Rank 34 amount', required=False, min_value=0)
    rank_35 = forms.DecimalField(label='Rank 35 amount', required=False, min_value=0)
    rank_36 = forms.DecimalField(label='Rank 36 amount', required=False, min_value=0)
    rank_37 = forms.DecimalField(label='Rank 37 amount', required=False, min_value=0)
    rank_38 = forms.DecimalField(label='Rank 38 amount', required=False, min_value=0)
    rank_39 = forms.DecimalField(label='Rank 39 amount', required=False, min_value=0)
    rank_40 = forms.DecimalField(label='Rank 40 amount', required=False, min_value=0)
    rank_41 = forms.DecimalField(label='Rank 41 amount', required=False, min_value=0)
    rank_42 = forms.DecimalField(label='Rank 42 amount', required=False, min_value=0)
    rank_43 = forms.DecimalField(label='Rank 43 amount', required=False, min_value=0)
    rank_44 = forms.DecimalField(label='Rank 44 amount', required=False, min_value=0)
    rank_45 = forms.DecimalField(label='Rank 45 amount', required=False, min_value=0)
    rank_46 = forms.DecimalField(label='Rank 46 amount', required=False, min_value=0)
    rank_47 = forms.DecimalField(label='Rank 47 amount', required=False, min_value=0)
    rank_48 = forms.DecimalField(label='Rank 48 amount', required=False, min_value=0)
    rank_49 = forms.DecimalField(label='Rank 49 amount', required=False, min_value=0)
    rank_50 = forms.DecimalField(label='Rank 50 amount', required=False, min_value=0)

    # Daily sequence fields
    day_1 = forms.DecimalField(label='Day 1 Reward', required=False, min_value=0)
    day_2 = forms.DecimalField(label='Day 2 Reward', required=False, min_value=0)
    day_3 = forms.DecimalField(label='Day 3 Reward', required=False, min_value=0)
    day_4 = forms.DecimalField(label='Day 4 Reward', required=False, min_value=0)
    day_5 = forms.DecimalField(label='Day 5 Reward', required=False, min_value=0)
    day_6 = forms.DecimalField(label='Day 6 Reward', required=False, min_value=0)
    day_7 = forms.DecimalField(label='Day 7 Reward', required=False, min_value=0)
    day_8 = forms.DecimalField(label='Day 8 Reward', required=False, min_value=0)
    day_9 = forms.DecimalField(label='Day 9 Reward', required=False, min_value=0)
    day_10 = forms.DecimalField(label='Day 10 Reward', required=False, min_value=0)
    day_11 = forms.DecimalField(label='Day 11 Reward', required=False, min_value=0)
    day_12 = forms.DecimalField(label='Day 12 Reward', required=False, min_value=0)
    day_13 = forms.DecimalField(label='Day 13 Reward', required=False, min_value=0)
    day_14 = forms.DecimalField(label='Day 14 Reward', required=False, min_value=0)
    day_15 = forms.DecimalField(label='Day 15 Reward', required=False, min_value=0)
    day_16 = forms.DecimalField(label='Day 16 Reward', required=False, min_value=0)
    day_17 = forms.DecimalField(label='Day 17 Reward', required=False, min_value=0)
    day_18 = forms.DecimalField(label='Day 18 Reward', required=False, min_value=0)
    day_19 = forms.DecimalField(label='Day 19 Reward', required=False, min_value=0)
    day_20 = forms.DecimalField(label='Day 20 Reward', required=False, min_value=0)
    day_21 = forms.DecimalField(label='Day 21 Reward', required=False, min_value=0)
    day_22 = forms.DecimalField(label='Day 22 Reward', required=False, min_value=0)
    day_23 = forms.DecimalField(label='Day 23 Reward', required=False, min_value=0)
    day_24 = forms.DecimalField(label='Day 24 Reward', required=False, min_value=0)
    day_25 = forms.DecimalField(label='Day 25 Reward', required=False, min_value=0)
    day_26 = forms.DecimalField(label='Day 26 Reward', required=False, min_value=0)
    day_27 = forms.DecimalField(label='Day 27 Reward', required=False, min_value=0)
    day_28 = forms.DecimalField(label='Day 28 Reward', required=False, min_value=0)
    day_29 = forms.DecimalField(label='Day 29 Reward', required=False, min_value=0)
    day_30 = forms.DecimalField(label='Day 30 Reward', required=False, min_value=0)
    day_31 = forms.DecimalField(label='Day 31 Reward', required=False, min_value=0)

    class Meta:
        model = AttendanceSettings
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rank_levels = []
        try:
            from accounts.models import RankLevel

            rank_levels = list(RankLevel.objects.order_by("rank").values_list("rank", "title"))
        except Exception:
            rank_levels = []

        rank_numbers = [int(r[0]) for r in rank_levels] if rank_levels else list(range(1, 7))
        self._rank_numbers = rank_numbers

        for i in range(1, self.MAX_RANK_FIELDS + 1):
            field_name = f"rank_{i}"
            if i not in rank_numbers:
                if field_name in self.fields:
                    self.fields.pop(field_name)
                continue

            title = None
            for rn, rt in rank_levels:
                if int(rn) == i:
                    title = rt
                    break
            label = f"Rank {i} amount" if not title else f"Rank {i} ({title}) amount"
            if field_name in self.fields:
                self.fields[field_name].label = label

        cycle_days_raw = None
        if self.data:
            cycle_days_raw = (self.data.get('daily_cycle_days') or '').strip()
        cycle_days = None
        if cycle_days_raw:
            try:
                cycle_days = int(cycle_days_raw)
            except Exception:
                cycle_days = None
        if cycle_days is None:
            cycle_days = int(getattr(self.instance, 'daily_cycle_days', DAILY_ATTENDANCE_PROGRAM_DAYS) or DAILY_ATTENDANCE_PROGRAM_DAYS)
        cycle_days = DAILY_ATTENDANCE_PROGRAM_DAYS

        rr = self.instance.rank_rewards or {}
        for i in self._rank_numbers:
            key = str(int(i))
            if key in rr:
                try:
                    self.fields[f'rank_{i}'].initial = Decimal(str(rr[key]))
                except Exception:
                    self.fields[f'rank_{i}'].initial = rr[key]
        
        dr = self.instance.daily_rewards or {}
        for i in range(1, cycle_days + 1):
            key = str(i)
            if key in dr and f'day_{i}' in self.fields:
                try:
                    self.fields[f'day_{i}'].initial = Decimal(str(dr[key]))
                except Exception:
                    self.fields[f'day_{i}'].initial = dr[key]

        reward_type = None
        if self.data:
            reward_type = (self.data.get('reward_type') or '').strip() or None
        if reward_type is None:
            reward_type = getattr(self.instance, 'reward_type', None)
        if reward_type == 'daily' and 'bonus_7_days' in self.fields:
            self.fields['bonus_7_days'].label = f'Bonus {cycle_days} days'
        if 'daily_cycle_days' in self.fields:
            self.fields['daily_cycle_days'].initial = DAILY_ATTENDANCE_PROGRAM_DAYS
            self.fields['daily_cycle_days'].help_text = (
                'Program attendance daily selalu 7 hari. Setelah hari ke-7 selesai, user tidak bisa klaim lagi '
                'dan hari yang terlewat akan hangus tanpa reset ke hari 1.'
            )

    def clean_daily_cycle_days(self):
        return DAILY_ATTENDANCE_PROGRAM_DAYS

    def save(self, commit=True):
        instance = super().save(commit=False)
        rr = {}
        for i in getattr(self, "_rank_numbers", []):
            i = int(i)
            val = self.cleaned_data.get(f'rank_{i}')
            if val is not None:
                # Store as float to keep JSON simple
                rr[str(i)] = float(val)
        instance.rank_rewards = rr
        
        dr = {}
        instance.daily_cycle_days = DAILY_ATTENDANCE_PROGRAM_DAYS
        cycle_days = DAILY_ATTENDANCE_PROGRAM_DAYS
        for i in range(1, cycle_days + 1):
            val = self.cleaned_data.get(f'day_{i}')
            if val is not None:
                dr[str(i)] = float(val)
        instance.daily_rewards = dr
        
        if commit:
            instance.save()
        return instance
