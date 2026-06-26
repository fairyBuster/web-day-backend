import os
from django.core.management.base import BaseCommand

from support.models import SupportLink


DEFAULTS = [
    {
        'title': 'Group WA Support',
        'url_env': 'SUPPORT_WA_URL',
        'url_default': 'https://chat.whatsapp.com/support',
        'platform': 'whatsapp',
        'description': 'Grup WhatsApp resmi untuk dukungan pelanggan',
        'is_active': True,
    },
    {
        'title': 'Telegram Support Channel',
        'url_env': 'SUPPORT_TELEGRAM_URL',
        'url_default': 'https://t.me/support_channel',
        'platform': 'telegram',
        'description': 'Channel Telegram untuk pengumuman dan bantuan',
        'is_active': True,
    },
    {
        'title': 'Website Help Center',
        'url_env': 'SUPPORT_WEBSITE_URL',
        'url_default': 'https://example.com/support',
        'platform': 'website',
        'description': 'Pusat bantuan dan FAQ di website',
        'is_active': True,
    },
]


class Command(BaseCommand):
    help = 'Seed default support links (WhatsApp, Telegram, Website)'

    def add_arguments(self, parser):
        parser.add_argument('--overwrite', action='store_true', help='Overwrite existing links with defaults/env values')

    def handle(self, *args, **options):
        overwrite = options.get('overwrite', False)
        created, updated, skipped = 0, 0, 0

        for item in DEFAULTS:
            url = os.environ.get(item['url_env']) or item['url_default']
            defaults = {
                'platform': item['platform'],
                'description': item['description'],
                'is_active': item['is_active'],
                'url': url,
            }

            try:
                link = SupportLink.objects.filter(title=item['title']).first()
                if not link:
                    SupportLink.objects.create(title=item['title'], **defaults)
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"Created: {item['title']} -> {url}"))
                else:
                    if overwrite:
                        for k, v in defaults.items():
                            setattr(link, k, v)
                        link.save()
                        updated += 1
                        self.stdout.write(self.style.WARNING(f"Updated: {item['title']} -> {url}"))
                    else:
                        skipped += 1
                        self.stdout.write(self.style.NOTICE(f"Skipped (exists): {item['title']}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {item['title']}: {e}"))

        total = SupportLink.objects.count()
        self.stdout.write(self.style.SUCCESS(f"Seeding done. created={created}, updated={updated}, skipped={skipped}, total={total}"))