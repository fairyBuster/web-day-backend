from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0003_gatewaysettings_min_deposit_amount'),
    ]

    operations = [
        migrations.AddField(
            model_name='gatewaysettings',
            name='max_deposit_amount',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Maksimal nominal deposit (0 = tidak dibatasi)', max_digits=15),
        ),
    ]

