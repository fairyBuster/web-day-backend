import threading
import time
import logging
from datetime import datetime, timedelta
from django.core.management import call_command
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

class AutomaticProfitScheduler:
    """
    Background scheduler yang berjalan bersamaan dengan Django server
    untuk memproses profit otomatis setiap 5 menit
    """
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.interval = 300  # 5 menit dalam detik
        
    def start(self):
        """Mulai scheduler dalam background thread"""
        if self.running:
            logger.info("🔄 Automatic Profit Scheduler sudah berjalan")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("🚀 Automatic Profit Scheduler dimulai - interval 5 menit")
        
    def stop(self):
        """Hentikan scheduler"""
        self.running = False
        if self.thread:
            self.thread.join()
        logger.info("⏹️ Automatic Profit Scheduler dihentikan")
        
    def _run_scheduler(self):
        """Loop utama scheduler"""
        logger.info("⏰ Scheduler loop dimulai")
        
        while self.running:
            try:
                current_time = datetime.now()
                logger.info(f"🔍 Menjalankan automatic profit processing - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Jalankan management command untuk process automatic profits
                call_command('process_automatic_profits', quiet=True)
                
                logger.info("✅ Automatic profit processing selesai")
                
            except Exception as e:
                logger.error(f"❌ Error dalam automatic profit processing: {str(e)}")
            finally:
                # Tutup koneksi database untuk mencegah timeout pada proses yang berjalan lama
                connection.close()
                
            # Tunggu 5 menit sebelum eksekusi berikutnya
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)
                
        logger.info("🔚 Scheduler loop berakhir")

# Instance global scheduler
profit_scheduler = AutomaticProfitScheduler()

def start_automatic_profit_scheduler():
    """Function untuk memulai scheduler"""
    profit_scheduler.start()

def stop_automatic_profit_scheduler():
    """Function untuk menghentikan scheduler"""
    profit_scheduler.stop()