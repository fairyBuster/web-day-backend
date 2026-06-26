from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0032_alter_transaction_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="required_golongan",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Jika diisi, user wajib sudah pernah membeli produk dengan golongan ini sebelum bisa membeli produk ini",
                max_length=20,
                null=True,
            ),
        ),
    ]

