from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0024_alter_transaction_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="qualify_as_active_investment",
            field=models.BooleanField(
                default=True,
                help_text="Jika OFF, pembelian produk ini tidak membuat user dihitung sebagai member aktif (rank, missions, dsb)",
            ),
        ),
    ]

