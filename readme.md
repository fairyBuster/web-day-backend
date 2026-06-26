🚀 Deploy Django + Gunicorn + Caddy + Cloudflare (Ubuntu 22.04)

Panduan ini menggunakan:

Django (Gunicorn di localhost:8000)

Caddy sebagai reverse proxy

Cloudflare SSL (Origin Certificate)

Mode SSL Cloudflare: Full (Strict)

1️⃣ Arsitektur Singkat
Internet
   ↓
Cloudflare (HTTPS)
   ↓
Caddy (HTTPS, Origin Cert)
   ↓
Gunicorn (HTTP)
   ↓
Django App (localhost:8000)

2️⃣ Install Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
 | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
 | sudo tee /etc/apt/sources.list.d/caddy-stable.list

sudo apt update
sudo apt install caddy

3️⃣ Buat Cloudflare Origin Certificate

Di Cloudflare Dashboard:

SSL/TLS → Origin Server

Create Certificate

Hostname:

appgoldare.online
*.appgoldare.online


Key Type: RSA

Validity: 15 years

4️⃣ Simpan Sertifikat di Server
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/cert.pem
sudo nano /etc/ssl/cloudflare/key.pem

🔐 Permission WAJIB
sudo chown -R root:caddy /etc/ssl/cloudflare
sudo chmod 750 /etc/ssl/cloudflare
sudo chmod 640 /etc/ssl/cloudflare/*.pem


⚠️ Ini penting supaya service caddy bisa membaca cert.
sudo mkdir -p /var/log/caddy
sudo chown -R caddy:caddy /var/log/caddy
sudo chmod 750 /var/log/caddy
5️⃣ Konfigurasi Caddyfile
sudo nano /etc/caddy/Caddyfile

appgoldare.online www.appgoldare.online {

    tls /etc/ssl/cloudflare/cert.pem /etc/ssl/cloudflare/key.pem

    reverse_proxy localhost:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-Proto https
    }
}

6️⃣ Validasi & Jalankan Caddy
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo systemctl status caddy


Pastikan status:

Active: active (running)

7️⃣ Cek Port
sudo ss -tulpn | grep caddy


Harus muncul:

*:80
*:443

8️⃣ Cloudflare Setting

Di Cloudflare:

SSL/TLS mode: Full (Strict) ✅

Proxy status DNS: ON (orange cloud)

9️⃣ Error yang Umum & Solusinya
❌ Cloudflare 521

Penyebab:

Caddy tidak listen di port 443

Permission cert salah

Solusi:

sudo chown -R root:caddy /etc/ssl/cloudflare
sudo chmod 640 /etc/ssl/cloudflare/*.pem

❌ Caddy loading tls app module

Penyebab:

User caddy tidak bisa baca file cert

Solusi:
→ Fix permission (lihat step 4)

10️⃣ Catatan Penting

Cloudflare Origin Certificate tidak perlu renew

OCSP warning di Caddy NORMAL

Jangan expose Gunicorn ke publik

Caddy hanya reverse proxy

11️⃣ Checklist Deploy

✅ Gunicorn jalan di localhost:8000
✅ Caddy active & listen 80/443
✅ Cloudflare Full (Strict)
✅ HTTPS aktif tanpa error

Kalau mau, next:

🔧 systemd service Gunicorn

🔐 Setting Django (SECURE_PROXY_SSL_HEADER)

🚀 Optimasi Caddy (gzip, header security)