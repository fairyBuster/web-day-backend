# CI/CD

Dokumen ini menjelaskan alur CI/CD project menggunakan GitHub Actions.

## Ringkasan

Project ini memakai 2 workflow:

- `CI`: validasi code setiap ada perubahan
- `CD`: deploy otomatis ke server via SSH

File workflow:

- [ci.yml](file:///c:/Project/fish_backend/ampli-backend-/.github/workflows/ci.yml)
- [deploy.yml](file:///c:/Project/fish_backend/ampli-backend-/.github/workflows/deploy.yml)

## CI

Workflow `CI` berjalan saat:

- `push` ke branch `main`
- `push` ke branch `master`
- `pull_request`

Hal yang dijalankan:

1. checkout source code
2. setup Python `3.11`
3. install dependency dari `requirements.txt`
4. jalankan PostgreSQL service untuk testing
5. cek migration belum ada yang tertinggal
6. jalankan `python manage.py check`
7. jalankan test Django
8. verifikasi `collectstatic`

Environment CI yang dipakai:

- database PostgreSQL temporary di GitHub Actions
- `DEBUG=False`
- `RESPONSE_ENCODE_ENABLED=False`
- host database `127.0.0.1`

Tujuan CI:

- memastikan project masih bisa jalan
- mencegah error syntax/setting/test sebelum di-merge
- mendeteksi migration yang lupa dibuat

## CD

Workflow `CD` berjalan saat:

- `push` ke branch `main`
- `push` ke branch `master`
- manual dari tab `Actions` lewat `workflow_dispatch`

Workflow ini deploy ke server menggunakan SSH, lalu menjalankan:

```bash
cd <DEPLOY_PATH>
git fetch --all --prune
git checkout <branch>
git pull --ff-only origin <branch>
docker compose up -d --build
docker compose ps
```

Alur ini disesuaikan dengan pola deploy project yang sudah dipakai di repo:

```bash
git pull
docker compose up -d --build
```

## Secret GitHub Actions

Masuk ke:

`GitHub Repository > Settings > Secrets and variables > Actions`

Lalu tambahkan secret berikut:

- `SERVER_HOST`
  - IP atau domain VPS
- `SERVER_PORT`
  - port SSH, biasanya `22`
- `SERVER_USER`
  - user SSH untuk deploy
- `SERVER_SSH_KEY`
  - private key SSH milik user deploy
- `DEPLOY_PATH`
  - folder project di server
  - contoh: `/home/deploy/ampli-backend-`

## Persiapan Server

Server target deploy harus memenuhi syarat berikut:

- repository ini sudah di-clone di server
- remote `origin` sudah mengarah ke repo GitHub yang benar
- Docker dan Docker Compose sudah terpasang
- user SSH punya izin menjalankan `docker compose`
- file `.env` produksi sudah ada di folder project server

Contoh struktur di server:

```bash
/home/deploy/ampli-backend-/
  .env
  docker-compose.yml
  Dockerfile
  manage.py
```

## Cara Kerja Deploy

Saat workflow `CD` jalan:

1. GitHub Actions login ke server via SSH
2. masuk ke folder project (`DEPLOY_PATH`)
3. fetch branch terbaru
4. checkout branch target
5. pull update terbaru
6. rebuild dan restart service dengan Docker Compose
7. tampilkan status container

Karena `Dockerfile` project ini sudah menjalankan:

- wait database
- `migrate --noinput --fake-initial`
- `collectstatic --noinput`
- start `gunicorn`

maka deploy cukup dengan:

```bash
docker compose up -d --build
```

## Deploy Manual Dari GitHub

Kalau mau deploy manual:

1. buka tab `Actions`
2. pilih workflow `CD`
3. klik `Run workflow`
4. isi branch yang ingin di-deploy
5. jalankan workflow

Ini berguna kalau:

- branch utama bukan `main`
- mau redeploy tanpa commit baru
- mau deploy branch tertentu

## Troubleshooting

### 1. Deploy gagal connect SSH

Cek hal berikut:

- `SERVER_HOST`, `SERVER_PORT`, `SERVER_USER` benar
- `SERVER_SSH_KEY` cocok dengan public key yang sudah dipasang di server
- firewall server mengizinkan akses SSH

### 2. Deploy gagal karena `git pull`

Cek:

- remote `origin` benar
- branch target ada di server dan di GitHub
- working tree server tidak konflik

### 3. Deploy gagal saat `docker compose`

Cek di server:

```bash
docker compose ps
docker compose logs -f
docker compose logs -f web
docker compose logs -f db
docker compose logs -f pgbouncer
```

### 4. Aplikasi gagal start setelah deploy

Cek:

- isi `.env` produksi
- koneksi database
- domain / CORS / APP_DOMAIN
- migration atau dependency yang bermasalah

## Catatan Penting

- File `.env` produksi tidak disimpan di GitHub dan tidak disentuh workflow
- Workflow `CD` tidak membuat backup database otomatis sebelum deploy
- Workflow `CD` saat ini deploy langsung ke server production tanpa staging
- Trigger deploy masih menerima `main` dan `master`

## Saran Lanjutan

Kalau mau ditingkatkan lagi, next step yang bagus:

- tambah staging environment
- tambah backup database otomatis sebelum deploy
- tambah notifikasi deploy ke Telegram/Discord
- tambah health check setelah deploy
- build image ke registry seperti `ghcr.io`


sudo usermod -aG sudo ubuntu