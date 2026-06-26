import os
from urllib.request import urlopen
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.core.files.base import ContentFile
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from news.models import News


DEFAULT_NEWS = [
    {
        'title': 'Pengumuman Fitur Baru',
        'slug': 'pengumuman-fitur-baru',
        'body': 'Kami merilis fitur baru untuk meningkatkan pengalaman Anda.',
        'image_url': 'https://via.placeholder.com/800x400.png?text=Fitur+Baru',
        'is_published': True,
    },
    {
        'title': 'Perawatan Sistem Terjadwal',
        'slug': 'perawatan-sistem-terjadwal',
        'body': 'Akan ada perawatan sistem pada akhir pekan ini.',
        'image_url': 'https://via.placeholder.com/800x400.png?text=Maintenance',
        'is_published': True,
    },
    {
        'title': 'Promo Spesial Bulan Ini',
        'slug': 'promo-spesial-bulan-ini',
        'body': 'Nikmati promo spesial untuk pengguna aktif sepanjang bulan ini.',
        'image_url': 'https://via.placeholder.com/800x400.png?text=Promo',
        'is_published': True,
    },
]


class Command(BaseCommand):
    help = 'Seed default news articles with optional placeholder images.'

    def add_arguments(self, parser):
        parser.add_argument('--overwrite', action='store_true', help='Overwrite existing news with same slug')

    def handle(self, *args, **options):
        overwrite = options.get('overwrite', False)
        created_count = 0
        updated_count = 0

        for item in DEFAULT_NEWS:
            title = item['title']
            slug = item['slug'] or slugify(title)
            body = item['body']
            is_published = item.get('is_published', True)
            image_url = item.get('image_url')

            obj, created = News.objects.get_or_create(
                slug=slug,
                defaults={
                    'title': title,
                    'body': body,
                    'is_published': is_published,
                }
            )

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created news: {slug}"))
            else:
                if overwrite:
                    obj.title = title
                    obj.body = body
                    obj.is_published = is_published
                    obj.save()
                    updated_count += 1
                    self.stdout.write(self.style.WARNING(f"Updated news: {slug}"))
                else:
                    self.stdout.write(self.style.NOTICE(f"Skipped existing news: {slug}"))

            # Attach image if not present or overwrite requested
            if created or overwrite or not obj.image:
                saved = False
                # Try remote placeholder first
                if image_url:
                    try:
                        with urlopen(image_url, timeout=5) as resp:
                            data = resp.read()
                            filename = f"{slug}.png"
                            obj.image.save(filename, ContentFile(data), save=True)
                            self.stdout.write(self.style.SUCCESS(f"Attached remote image for: {slug}"))
                            saved = True
                    except Exception:
                        pass

                if not saved:
                    # Generate local placeholder image
                    try:
                        img = Image.new('RGB', (800, 400), color=(30, 144, 255))
                        draw = ImageDraw.Draw(img)
                        text = title[:40]
                        font = ImageFont.load_default()
                        # Compute text bounding box for centering
                        bbox = draw.textbbox((0, 0), text, font=font)
                        w = bbox[2] - bbox[0]
                        h = bbox[3] - bbox[1]
                        draw.text(((800 - w) / 2, (400 - h) / 2), text, fill=(255, 255, 255), font=font)
                        buffer = BytesIO()
                        img.save(buffer, format='PNG')
                        buffer.seek(0)
                        filename = f"{slug}.png"
                        obj.image.save(filename, ContentFile(buffer.read()), save=True)
                        self.stdout.write(self.style.SUCCESS(f"Attached generated image for: {slug}"))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Failed to generate image for {slug}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Seed complete. Created: {created_count}, Updated: {updated_count}"))