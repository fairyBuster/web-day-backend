from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_phoneotp_generalsetting_otp_enabled_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="whatsapp_check_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Jika ON, verifikasi nomor WA aktif saat register (backup/alternatif OTP)",
            ),
        ),
        migrations.AddField(
            model_name="generalsetting",
            name="checknumber_api_key",
            field=models.CharField(
                max_length=255,
                blank=True,
                help_text="API Key untuk checknumber.ai (pemeriksa nomor WhatsApp)",
            ),
        ),
    ]

