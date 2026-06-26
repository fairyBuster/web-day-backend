from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0036_alter_transaction_type_add_transfer"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="require_withdraw_pin_on_purchase",
            field=models.BooleanField(
                default=False,
                help_text="Jika ON, pembelian produk ini wajib input withdraw PIN",
            ),
        ),
    ]
