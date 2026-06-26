from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0030_profit_holiday_extend_duration_flag"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="required_product",
            field=models.ForeignKey(
                blank=True,
                help_text="Jika diisi, user wajib sudah pernah memiliki produk ini sebelum bisa membeli produk ini",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="unlocks_products",
                to="products.product",
            ),
        ),
    ]

