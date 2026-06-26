from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('news', '0002_news_image'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "SELECT setval(\n"
                "  pg_get_serial_sequence('news_news','id'),\n"
                "  COALESCE((SELECT MAX(id) FROM news_news), 1),\n"
                "  true\n"
                ");"
            ),
            reverse_sql=migrations.RunSQL.noop,
        )
    ]