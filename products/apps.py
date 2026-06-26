from django.apps import AppConfig
import logging
import importlib
import os

logger = logging.getLogger(__name__)

class ProductsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'products'
    
    def ready(self):
        """
        Method yang dipanggil ketika Django app siap
        Digunakan untuk memulai automatic profit scheduler
        """
        # Import di sini untuk menghindari circular import
        from .scheduler import start_automatic_profit_scheduler
        
        # Hanya jalankan scheduler jika bukan dalam mode testing atau migration
        import sys
        if 'runserver' in sys.argv or 'gunicorn' in sys.argv[0]:
            # Avoid starting scheduler twice under Django's autoreload
            if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
                return
            try:
                # Pre-import Django SQL compiler to avoid race condition in multithreaded workers
                importlib.import_module('django.db.models.sql.compiler')
                start_automatic_profit_scheduler()
                logger.info("🎯 Automatic Profit Scheduler berhasil dimulai dengan Django server")
            except Exception as e:
                logger.error(f"❌ Gagal memulai Automatic Profit Scheduler: {str(e)}")
        else:
            logger.info("⏭️ Melewati scheduler startup (bukan runserver/gunicorn)")
