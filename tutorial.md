🔹 Update dulu
sudo apt update && sudo apt upgrade -y
🔹 Install Docker
sudo apt install -y docker.io
🔹 Aktifkan Docker
sudo systemctl enable docker
sudo systemctl start docker

🔹 Install Docker Compose
# Install prerequisites
apt install -y ca-certificates curl gnupg lsb-release

# Add Docker's GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

# Add the Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Update and install
apt update
apt install -y docker-compose-plugin


## 3) Clone Repository
```bash
git clone <REPO_URL> SentotBackend
cd SentotBackend
```

## 4) Siapkan .env di VPS
Buat file `.env` (gunakan nilai Anda sendiri). Minimal:
```env
SECRET_KEY=ubah_ke_secret_produksi
DEBUG=False

# Database
DATABASE_NAME=database
DATABASE_USER=postgres
DATABASE_PASSWORD=ubah_password_db
DATABASE_HOST=db
DATABASE_PORT=5432
DATABASE_SSLMODE=disable

# Domain (opsional)
APP_DOMAIN=example.com
ACME_EMAIL=admin@example.com
```
Catatan:
- Service web akan memakai PgBouncer dari docker-compose (DATABASE_HOST dan PORT untuk web sudah dioverride menjadi `pgbouncer:6432`). Nilai di .env untuk host/port tetap dibutuhkan Postgres/PgBouncer.

## 5) Booting Layanan (Pertama Kali)
Jika ini pertama kali (volume DB belum ada) cukup jalankan:
```bash
docker compose up -d --build
```

Jika sebelumnya sudah pernah menjalankan versi lain dan ingin inisialisasi ulang (PostgreSQL 18 + import `backup.sql`), lakukan reset volume:
```bash
docker compose down
docker volume rm sentotbackend_postgres_data
docker compose up -d --build
```

## 6) Inisialisasi Django
```bash
docker compose exec web python manage.py migrate --noinput
docker compose exec web python manage.py collectstatic --noinput
```

## 7) Verifikasi
```bash
docker compose ps
docker compose logs -f db
docker compose logs -f pgbouncer
docker compose logs -f web
```
Tes endpoint health (jika akses langsung ke port 8000):
```bash
curl -I http://SERVER_IP:8000/health
```
Atau jika sudah di‑proxy/dipasang domain:
```bash
curl -I https://APP_DOMAIN/health
```

## 8) Manajemen Layanan
- Start/Stop/Restart
```bash
docker compose up -d
docker compose down
docker compose restart
```

- Logs
```bash
docker compose logs -f
docker compose logs -f web
docker compose logs -f pgbouncer
docker compose logs -f db
```

- Status proses & resource
```bash
docker compose ps
docker compose top web
docker stats
```

## 9) Pengaturan Gunicorn (via Environment)
Service web menjalankan Gunicorn di background. Anda bisa mengubah perilaku lewat env (sudah diset di `docker-compose.yml`, bisa ditimpa lewat `.env` jika mau):
```env
WORKERS=3
THREADS=2
TIMEOUT=120
KEEP_ALIVE=65
MAX_REQUESTS=1000
MAX_REQUESTS_JITTER=50
LOG_LEVEL=info
```
Terapkan perubahan:
```bash
docker compose up -d
```

## 10) PostgreSQL 18 + PgBouncer
- Postgres 18 memakai mount `/var/lib/postgresql` di compose (sudah disiapkan).
- `backup.sql` otomatis di‑import saat inisialisasi pertama volume.
- PgBouncer aktif (pool mode: transaction). Service web diarahkan ke `pgbouncer:6432` dan `DB_CONN_MAX_AGE=0` sudah diatur.

## 11) Update Kode
```bash
git pull
docker compose up -d --build
```

## 12) Caddy + SSL Otomatis (Opsional)
- Pastikan DNS APP_DOMAIN mengarah ke IP VPS dan port 80/443 terbuka.
- Isi `.env`:
```env
APP_DOMAIN=example.com
ACME_EMAIL=admin@example.com
# Whitelist domain frontend untuk CORS API (regex)
CORS_ORIGIN_REGEX=^https?://(your-frontend\.com|www\.your-frontend\.com)(:\d+)?$
```
- Jalankan/Restart Caddy:
```bash
docker compose up -d caddy
docker compose logs -f caddy
```
- Caddy akan:
  - Mengambil sertifikat otomatis (Let's Encrypt) untuk APP_DOMAIN
  - Serve /static dan /media dari folder project
  - Mem‑proxy request ke backend di web:8000
  - Mengizinkan Origin sesuai `CORS_ORIGIN_REGEX` untuk path `/api/*` (preflight dijawab 204)

## 13) Tips & Troubleshooting
- Jika ganti kredensial DB di `.env`, dan ingin diterapkan dari awal + re‑import:
```bash
docker compose down
docker volume rm sentotbackend_postgres_data
docker compose up -d --build
```
- Jika web tidak bisa konek DB dan error `could not translate host name "db"` atau `pgbouncer`: pastikan semua service dijalankan via `docker compose up -d` (jangan `docker run` terpisah).
- Jika build error terkait dependency native: gunakan base image Python slim atau pastikan paket build (gcc, libpq-dev) sudah terinstall (sudah disiapkan di Dockerfile).
