from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0002_gateway_extra_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='gatewaysettings',
            name='min_deposit_amount',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Minimal nominal deposit (0 = tidak dibatasi)', max_digits=15),
        ),
    ]

