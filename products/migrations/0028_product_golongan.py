from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0027_alter_product_profit_method_alter_transaction_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="golongan",
            field=models.CharField(blank=True, db_index=True, max_length=20, null=True),
        ),
    ]
