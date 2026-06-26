from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0016_remove_product_custom_fields_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='require_upline_ownership_for_commissions',
            field=models.BooleanField(
                default=False,
                help_text='Jika ON, upline harus memiliki produk ini (investment ACTIVE) untuk menerima purchase/profit commission'
            ),
        ),
    ]