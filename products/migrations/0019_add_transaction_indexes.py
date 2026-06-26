from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0018_investment_profit_random_max_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['user', 'type', 'status', 'created_at'], name='trx_user_type_stat_cr_idx'),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['upline_user', 'type'], name='trx_upline_type_idx'),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['type'], name='trx_type_idx'),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['wallet_type'], name='trx_wallet_type_idx'),
        ),
    ]
