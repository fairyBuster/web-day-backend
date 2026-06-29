from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    Transaction = apps.get_model("products", "Transaction")
    Transaction.objects.filter(type="RETURN", amount__lt=0).update(amount=-F("amount"))


def backwards(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0038_transaction_cashback_deposit_type_and_wallet_choice"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

