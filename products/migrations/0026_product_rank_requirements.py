from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0025_product_qualify_as_active_investment"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="require_min_rank_enabled",
            field=models.BooleanField(default=False, help_text="Jika ON, user harus memiliki rank minimum untuk membeli produk ini"),
        ),
        migrations.AddField(
            model_name="product",
            name="min_required_rank",
            field=models.PositiveSmallIntegerField(null=True, blank=True, help_text="Rank minimum yang dibutuhkan untuk membeli (contoh: 2 untuk Rank 2)"),
        ),
    ]
