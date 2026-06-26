from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0020_generalsetting_rank_use_deposit_self_total"),
        ("accounts", "0020_generalsetting_require_withdraw_pin_on_purchase"),
    ]

    operations = []
