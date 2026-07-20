# Panduan Integrasi Client ke Tripay Hub

Dokumen ini ditujukan untuk website client yang ingin terhubung ke Tripay Hub agar bisa membuat transaksi Tripay tanpa perlu memiliki akun Tripay sendiri.

## Tujuan

- Website client mengirim request transaksi ke hub.
- Hub membuat transaksi ke Tripay memakai akun merchant milik hub.
- Hub mengembalikan response Tripay ke client.
- Saat Tripay mengirim callback ke hub, hub akan meneruskan callback itu ke server client.

## Alur Integrasi

1. Admin hub membuat akun client dan memberikan `client_id` serta `secret_key`.
2. Client menyimpan `client_id` dan `secret_key` secara aman di server.
3. Client memanggil endpoint `POST /api/client/create-transaction`.
4. Hub memverifikasi header signature client.
5. Jika valid, hub meneruskan request ke Tripay.
6. Hub mengembalikan response Tripay ke client.
7. Saat pembayaran berubah status, Tripay mengirim callback ke hub.
8. Hub meneruskan callback yang sama ke `client_callback_url` milik client.
9. Client memverifikasi header `X-Hub-Signature` sebelum memproses callback.

## Kredensial Yang Diberikan Ke Client

Setelah client didaftarkan oleh admin hub, client akan menerima:

- `client_id`
- `secret_key`

Untuk penggunaan saat ini yang hanya untuk 1 client, pakai kredensial berikut:

- `client_id`: `cli_e0b4fa5d2f2b70cc`
- `secret_key`: `C8Fb6P83tHEWqKsUGahjEAwHMDTdfHHqiv8VytO5S4o`

Catatan:

- `secret_key` hanya ditampilkan sekali saat akun client dibuat.
- Jangan simpan `secret_key` di frontend, mobile app, atau JavaScript publik.
- Simpan `secret_key` hanya di backend server client.

## Base URL

Contoh base URL hub:

```text
https://api.totc.site
```

Endpoint client yang dipakai:

```text
POST /api/client/create-transaction
```

## Autentikasi Request Client ke Hub

Setiap request ke endpoint client hub wajib mengirim header berikut:

- `X-Client-Id`
- `X-Timestamp`
- `X-Signature`

### Format Signature

Signature dihitung dengan rumus:

```text
HMAC_SHA256(secret_key, client_id + timestamp + raw_body_json)
```

Keterangan:

- `secret_key` adalah secret milik client dari hub
- `client_id` adalah id client dari hub
- `timestamp` disarankan unix timestamp dalam detik
- `raw_body_json` harus persis sama dengan body yang dikirim

### Aturan Validasi Di Hub

Hub akan menolak request dengan `401` jika salah satu kondisi ini gagal:

- `client_id` tidak ditemukan
- client dalam keadaan tidak aktif
- `timestamp` lebih dari 5 menit dari waktu server
- `signature` tidak cocok

## Endpoint Buat Transaksi

## [POST] /api/client/create-transaction

- **Deskripsi:** Membuat transaksi Tripay melalui hub
- **Auth:** Ya, wajib `X-Client-Id`, `X-Timestamp`, `X-Signature`
- **Content-Type:** `application/json`

### Header Request

```http
X-Client-Id: cli_e0b4fa5d2f2b70cc
X-Timestamp: 1752912345
X-Signature: <hmac_sha256_hex>
Content-Type: application/json
```

### Body Request

Body yang dikirim pada dasarnya mengikuti payload create transaction Tripay, ditambah 1 field khusus:

- `client_callback_url`: URL callback milik server client yang akan menerima forwarding callback dari hub

Contoh body:

```json
{
  "method": "BRIVA",
  "merchant_ref": "ORDER-10001",
  "amount": 150000,
  "customer_name": "Budi",
  "customer_email": "budi@example.com",
  "customer_phone": "081234567890",
  "order_items": [
    {
      "sku": "SKU-1",
      "name": "Produk A",
      "price": 150000,
      "quantity": 1
    }
  ],
  "return_url": "https://partner.example.com/payment/finish",
  "expired_time": 1784454000,
  "client_callback_url": "https://partner.example.com/api/payment/tripay-callback"
}
```

### Field Penting

- `merchant_ref`
  Nilai ini harus unik per transaksi. Hub memakai nilai ini untuk mencocokkan callback Tripay dengan transaksi client.

- `client_callback_url`
  URL server client yang akan menerima callback dari hub. Harus `http` atau `https` yang valid.

### Response Success

Response yang dikembalikan hub adalah response Tripay apa adanya.

Contoh:

```json
{
  "success": true,
  "message": "Berhasil",
  "data": {
    "reference": "T0001000000000000001",
    "merchant_ref": "ORDER-10001",
    "payment_selection_type": "static",
    "payment_name": "BRI Virtual Account",
    "payment_method": "BRIVA",
    "pay_code": "1234567890123456",
    "checkout_url": "https://tripay.co.id/payment/T0001000000000000001",
    "status": "UNPAID",
    "expired_time": "2026-07-20 14:00:00",
    "amount": 150000
  }
}
```

### Response Error

Contoh error yang mungkin diterima:

```json
{
  "detail": "Autentikasi client tidak valid"
}
```

```json
{
  "detail": "merchant_ref sudah digunakan"
}
```

```json
{
  "detail": "client_callback_url wajib diisi"
}
```

```json
{
  "detail": "Gagal membuat transaksi Tripay: Invalid API Key"
}
```

## Contoh Hitung Signature

### Bash

```bash
CLIENT_ID="cli_e0b4fa5d2f2b70cc"
SECRET_KEY="C8Fb6P83tHEWqKsUGahjEAwHMDTdfHHqiv8VytO5S4o"
TIMESTAMP="$(date +%s)"

BODY='{"method":"BRIVA","merchant_ref":"ORDER-10001","amount":150000,"customer_name":"Budi","customer_email":"budi@example.com","customer_phone":"081234567890","order_items":[{"sku":"SKU-1","name":"Produk A","price":150000,"quantity":1}],"return_url":"https://partner.example.com/payment/finish","expired_time":1784454000,"client_callback_url":"https://partner.example.com/api/payment/tripay-callback"}'

SIGNATURE="$(printf '%s%s%s' "$CLIENT_ID" "$TIMESTAMP" "$BODY" | openssl dgst -sha256 -hmac "$SECRET_KEY" -hex | sed 's/^.* //')"
```

### Python

```python
import hashlib
import hmac
import json
import time

client_id = "cli_e0b4fa5d2f2b70cc"
secret_key = "C8Fb6P83tHEWqKsUGahjEAwHMDTdfHHqiv8VytO5S4o"
timestamp = str(int(time.time()))

payload = {
    "method": "BRIVA",
    "merchant_ref": "ORDER-10001",
    "amount": 150000,
    "customer_name": "Budi",
    "customer_email": "budi@example.com",
    "customer_phone": "081234567890",
    "order_items": [
        {
            "sku": "SKU-1",
            "name": "Produk A",
            "price": 150000,
            "quantity": 1,
        }
    ],
    "return_url": "https://partner.example.com/payment/finish",
    "expired_time": 1784454000,
    "client_callback_url": "https://partner.example.com/api/payment/tripay-callback",
}

raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
message = client_id.encode("utf-8") + timestamp.encode("utf-8") + raw_body
signature = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
```

## Contoh Request Lengkap

### cURL

```bash
CLIENT_ID="cli_e0b4fa5d2f2b70cc"
SECRET_KEY="C8Fb6P83tHEWqKsUGahjEAwHMDTdfHHqiv8VytO5S4o"
TIMESTAMP="$(date +%s)"

BODY='{"method":"BRIVA","merchant_ref":"ORDER-10001","amount":150000,"customer_name":"Budi","customer_email":"budi@example.com","customer_phone":"081234567890","order_items":[{"sku":"SKU-1","name":"Produk A","price":150000,"quantity":1}],"return_url":"https://partner.example.com/payment/finish","expired_time":1784454000,"client_callback_url":"https://partner.example.com/api/payment/tripay-callback"}'

SIGNATURE="$(printf '%s%s%s' "$CLIENT_ID" "$TIMESTAMP" "$BODY" | openssl dgst -sha256 -hmac "$SECRET_KEY" -hex | sed 's/^.* //')"

curl -X POST "https://api.totc.site/api/client/create-transaction" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $CLIENT_ID" \
  -H "X-Timestamp: $TIMESTAMP" \
  -H "X-Signature: $SIGNATURE" \
  --data "$BODY"
```

### JavaScript Node.js

```javascript
import crypto from "crypto";
import fetch from "node-fetch";

const clientId = "cli_e0b4fa5d2f2b70cc";
const secretKey = "C8Fb6P83tHEWqKsUGahjEAwHMDTdfHHqiv8VytO5S4o";
const timestamp = Math.floor(Date.now() / 1000).toString();

const payload = {
  method: "BRIVA",
  merchant_ref: "ORDER-10001",
  amount: 150000,
  customer_name: "Budi",
  customer_email: "budi@example.com",
  customer_phone: "081234567890",
  order_items: [
    {
      sku: "SKU-1",
      name: "Produk A",
      price: 150000,
      quantity: 1
    }
  ],
  return_url: "https://partner.example.com/payment/finish",
  expired_time: 1784454000,
  client_callback_url: "https://partner.example.com/api/payment/tripay-callback"
};

const body = JSON.stringify(payload);
const signature = crypto
  .createHmac("sha256", secretKey)
  .update(clientId + timestamp + body)
  .digest("hex");

const response = await fetch("https://api.totc.site/api/client/create-transaction", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Client-Id": clientId,
    "X-Timestamp": timestamp,
    "X-Signature": signature
  },
  body
});

const data = await response.json();
console.log(data);
```

## Callback Dari Hub Ke Client

Setelah Tripay mengirim callback ke hub, hub akan meneruskan payload callback ke `client_callback_url` yang dikirim saat create transaction.

### Header Callback Dari Hub

```http
Content-Type: application/json
X-Hub-Signature: <hmac_sha256_hex>
```

### Cara Hitung `X-Hub-Signature`

Header `X-Hub-Signature` dihitung dengan rumus:

```text
HMAC_SHA256(secret_key_client, raw_body_callback)
```

Catatan:

- `secret_key_client` adalah secret yang sama dengan yang dipakai saat create transaction
- `raw_body_callback` adalah body callback mentah persis seperti yang diterima client

### Contoh Payload Callback

Payload yang diteruskan adalah payload callback Tripay asli.

```json
{
  "reference": "T0001000000000000001",
  "merchant_ref": "ORDER-10001",
  "payment_method": "BRIVA",
  "payment_name": "BRI Virtual Account",
  "amount_received": "150000",
  "total_fee": "4250",
  "status": "PAID",
  "paid_at": "2026-07-19 14:05:00"
}
```

## Verifikasi Callback Di Sisi Client

Client wajib memverifikasi header `X-Hub-Signature` sebelum memproses callback.

### Contoh Python

```python
import hashlib
import hmac


def verify_hub_signature(secret_key: str, raw_body: bytes, signature: str) -> bool:
    expected = hmac.new(secret_key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature.strip())
```

Contoh pemakaian:

```python
raw_body = await request.body()
signature = request.headers.get("X-Hub-Signature", "")

if not verify_hub_signature(CLIENT_SECRET_KEY, raw_body, signature):
    raise HTTPException(status_code=401, detail="Signature hub tidak valid")
```

### Contoh Node.js

```javascript
import crypto from "crypto";

function verifyHubSignature(secretKey, rawBody, signature) {
  const expected = crypto
    .createHmac("sha256", secretKey)
    .update(rawBody)
    .digest("hex");

  return signature && crypto.timingSafeEqual(
    Buffer.from(expected, "utf8"),
    Buffer.from(signature.trim(), "utf8")
  );
}
```

## Response Yang Harus Diberikan Oleh Server Client

Saat menerima callback dari hub, server client sebaiknya:

1. Verifikasi `X-Hub-Signature`
2. Cocokkan `merchant_ref` dengan transaksi internal
3. Update status pembayaran di database client
4. Balas HTTP `200` atau status `2xx` jika berhasil

Contoh response:

```json
{
  "ok": true
}
```

## Retry Callback

Jika callback dari hub ke server client gagal terkirim, hub akan menyimpan retry dan mencoba kirim ulang otomatis.

Aturan retry:

- dicoba ulang setiap beberapa menit
- interval default `180` detik
- maksimal `5` kali percobaan
- jika server client membalas `2xx`, retry dianggap selesai

Agar retry tidak menimbulkan data dobel, handler callback di sisi client sebaiknya idempotent.

## Rekomendasi Implementasi Di Sisi Client

- Simpan transaksi internal dengan `merchant_ref` unik
- Anggap `merchant_ref` sebagai kunci utama pencocokan callback
- Simpan response Tripay seperti `reference`, `checkout_url`, `pay_code`, `status`
- Jangan pernah expose `secret_key` ke browser
- Sinkronkan jam server client dengan NTP agar validasi timestamp tidak gagal
- Gunakan body JSON yang konsisten saat menghitung signature dan saat mengirim request

## Troubleshooting

### 401 Autentikasi client tidak valid

Penyebab umum:

- `X-Client-Id` salah
- `X-Signature` salah
- `X-Timestamp` terlalu lama
- body yang ditandatangani berbeda dengan body yang dikirim

Checklist:

- pastikan string JSON yang dipakai menghitung signature sama persis dengan body HTTP
- pastikan `timestamp` dikirim dalam detik dan tidak lebih dari 5 menit
- pastikan secret yang dipakai adalah secret aktif terbaru

### 400 merchant_ref sudah digunakan

Penyebab:

- client mengirim `merchant_ref` yang pernah dipakai sebelumnya

Solusi:

- buat `merchant_ref` unik untuk setiap transaksi

### Callback tidak masuk ke server client

Checklist:

- pastikan `client_callback_url` bisa diakses publik
- pastikan firewall/server menerima request POST
- pastikan endpoint callback client membalas `2xx`
- cek log server client untuk timeout atau error 4xx/5xx

## Ringkasan Cepat

- Buat signature: `HMAC_SHA256(secret_key, client_id + timestamp + raw_body_json)`
- Kirim request ke `POST /api/client/create-transaction`
- Simpan `merchant_ref` dan response Tripay
- Terima callback dari hub di `client_callback_url`
- Verifikasi `X-Hub-Signature`
- Update transaksi internal berdasarkan `merchant_ref`
