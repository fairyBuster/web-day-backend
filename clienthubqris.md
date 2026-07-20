# Panduan Integrasi Client ke SiTransfer Hub

Dokumen ini ditujukan untuk website client yang ingin terhubung ke SiTransfer Hub agar bisa membuat transaksi SiTransfer tanpa perlu memiliki akun SiTransfer sendiri.

## Tujuan

- Website client mengirim request transaksi ke hub.
- Hub membuat transaksi ke SiTransfer memakai akun merchant milik hub.
- Hub mengembalikan response SiTransfer ke client.
- Saat SiTransfer mengirim callback ke hub, hub akan meneruskan callback itu ke server client.

## Alur Integrasi

1. Admin hub membuat akun client dan memberikan `client_id` serta `secret_key`.
2. Client menyimpan `client_id` dan `secret_key` secara aman di server.
3. Client memanggil endpoint `POST /api/client/create-transaction-sitranfer`.
4. Hub memverifikasi header signature client.
5. Jika valid, hub meneruskan request ke SiTransfer.
6. Hub mengembalikan response SiTransfer ke client.
7. Saat pembayaran berubah status, SiTransfer mengirim callback ke hub.
8. Hub mencocokkan `transaction_id` SiTransfer ke transaksi client di hub.
9. Hub meneruskan callback ke `client_callback_url` milik client.
10. Client memverifikasi header `X-Hub-Signature` sebelum memproses callback.

## Kredensial Yang Diberikan Ke Client

Setelah client didaftarkan oleh admin hub, client akan menerima:

- `client_id`
- `secret_key`

Untuk penggunaan saat ini yang hanya untuk 1 client, pakai kredensial berikut:

- `client_id`: `cli_e9007394f7f28e05`
- `secret_key`: `4yoruG1gj2F4aa642kw1FwMuO2yuy03ijbOZfq3i0-w`

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
POST /api/client/create-transaction-sitranfer
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

## [POST] /api/client/create-transaction-sitranfer

- **Deskripsi:** Membuat transaksi SiTransfer melalui hub
- **Auth:** Ya, wajib `X-Client-Id`, `X-Timestamp`, `X-Signature`
- **Content-Type:** `application/json`

### Header Request

```http
X-Client-Id: cli_e9007394f7f28e05
X-Timestamp: 1752912345
X-Signature: <hmac_sha256_hex>
Content-Type: application/json
```

### Body Request

Body yang dikirim mengikuti payload generate payment SiTransfer, ditambah 2 field khusus hub:

- `merchant_ref`: referensi internal transaksi milik client
- `client_callback_url`: URL callback milik server client yang akan menerima forwarding callback dari hub

Contoh body:

```json
{
  "merchant_ref": "INV-CUST-10001",
  "channel": "QRIS",
  "amount": 150000,
  "player_username": "budi",
  "client_callback_url": "https://partner.example.com/api/payment/sitranfer-callback"
}
```

### Field Penting

- `merchant_ref`
  Nilai ini harus unik per transaksi. Hub memakai nilai ini untuk mencocokkan transaksi internal client dengan callback yang diteruskan dari hub.

- `channel`
  Saat ini hub mendukung:
  - `QRIS`
  - `DANA`

- `player_username`
  Identifier user/client milik sistem partner yang akan diteruskan ke SiTransfer.

- `client_callback_url`
  URL server client yang akan menerima callback dari hub. Harus `http` atau `https` yang valid.

### Response Success

Response yang dikembalikan hub adalah response SiTransfer apa adanya.

Contoh response channel `QRIS`:

```json
{
  "success": true,
  "message": "Payment generated successfully",
  "data": {
    "store_name": "Toko Elektronik A",
    "type": "QRIS",
    "currency": "IDR",
    "username": "budi",
    "transaction_id": "TRXQR1ZCB0DS5L",
    "amount": "150000",
    "fee_mdr": "3000",
    "nett_amount": "147000",
    "expired_at": "2026-01-11 08:27:31",
    "instruction": "Silakan selesaikan pembayaran sebelum waktu kedaluwarsa.",
    "qris_image": "https://rest.sitranfer.com/qris/TRXQR1ZCB0DS5L.png",
    "qris_data": "0002010102122...."
  }
}
```

Contoh response channel `DANA`:

```json
{
  "success": true,
  "message": "Payment generated successfully",
  "data": {
    "store_name": "Toko Elektronik A",
    "type": "DANA",
    "currency": "IDR",
    "username": "budi",
    "transaction_id": "TRXDN9G410U7BV",
    "amount": "150000",
    "fee_mdr": "3000",
    "nett_amount": "147000",
    "expired_at": "2026-01-11 08:28:48",
    "instruction": "Silakan selesaikan pembayaran sebelum waktu kedaluwarsa.",
    "payment_url": "https://m.dana.id/n/link/minta?full_url=000201010...."
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
  "detail": "channel harus QRIS atau DANA"
}
```

```json
{
  "detail": "Gagal membuat transaksi SiTransfer: <error dari SiTransfer>"
}
```

## Contoh Hitung Signature

### Bash

```bash
CLIENT_ID="cli_e9007394f7f28e05"
SECRET_KEY="4yoruG1gj2F4aa642kw1FwMuO2yuy03ijbOZfq3i0-w"
TIMESTAMP="$(date +%s)"

BODY='{"merchant_ref":"INV-CUST-10001","channel":"QRIS","amount":150000,"player_username":"budi","client_callback_url":"https://partner.example.com/api/payment/sitranfer-callback"}'

SIGNATURE="$(printf '%s%s%s' "$CLIENT_ID" "$TIMESTAMP" "$BODY" | openssl dgst -sha256 -hmac "$SECRET_KEY" -hex | sed 's/^.* //')"
```

### Python

```python
import hashlib
import hmac
import json
import time

client_id = "cli_e9007394f7f28e05"
secret_key = "4yoruG1gj2F4aa642kw1FwMuO2yuy03ijbOZfq3i0-w"
timestamp = str(int(time.time()))

payload = {
    "merchant_ref": "INV-CUST-10001",
    "channel": "QRIS",
    "amount": 150000,
    "player_username": "budi",
    "client_callback_url": "https://partner.example.com/api/payment/sitranfer-callback",
}

raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
message = client_id.encode("utf-8") + timestamp.encode("utf-8") + raw_body
signature = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
```

## Contoh Request Lengkap

### cURL

```bash
CLIENT_ID="cli_e9007394f7f28e05"
SECRET_KEY="4yoruG1gj2F4aa642kw1FwMuO2yuy03ijbOZfq3i0-w"
TIMESTAMP="$(date +%s)"

BODY='{"merchant_ref":"INV-CUST-10001","channel":"QRIS","amount":150000,"player_username":"budi","client_callback_url":"https://partner.example.com/api/payment/sitranfer-callback"}'

SIGNATURE="$(printf '%s%s%s' "$CLIENT_ID" "$TIMESTAMP" "$BODY" | openssl dgst -sha256 -hmac "$SECRET_KEY" -hex | sed 's/^.* //')"

curl -X POST "https://api.totc.site/api/client/create-transaction-sitranfer" \
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

const clientId = "cli_e9007394f7f28e05";
const secretKey = "4yoruG1gj2F4aa642kw1FwMuO2yuy03ijbOZfq3i0-w";
const timestamp = Math.floor(Date.now() / 1000).toString();

const payload = {
  merchant_ref: "INV-CUST-10001",
  channel: "QRIS",
  amount: 150000,
  player_username: "budi",
  client_callback_url: "https://partner.example.com/api/payment/sitranfer-callback"
};

const body = JSON.stringify(payload);
const signature = crypto
  .createHmac("sha256", secretKey)
  .update(clientId + timestamp + body)
  .digest("hex");

const response = await fetch("https://api.totc.site/api/client/create-transaction-sitranfer", {
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

Setelah SiTransfer mengirim callback ke hub, hub akan meneruskan payload callback yang sudah diperkaya ke `client_callback_url` yang dikirim saat create transaction.

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

Payload yang diteruskan oleh hub ke client berbentuk seperti ini:

```json
{
  "success": true,
  "provider": "sitranfer",
  "merchant_ref": "INV-CUST-10001",
  "data": {
    "type": "QRIS",
    "username": "budi",
    "transaction_id": "TRXQR1ZCB0DS5L",
    "amount": "150000",
    "status": "success",
    "created_at": "2026-01-11 08:17:49"
  },
  "gateway_callback": {
    "success": true,
    "data": {
      "type": "QRIS",
      "username": "budi",
      "transaction_id": "TRXQR1ZCB0DS5L",
      "amount": "150000",
      "status": "success"
    }
  },
  "gateway_status": {
    "success": true,
    "message": "Transaction status fetched",
    "data": {
      "store_name": "Toko Elektronik A",
      "transaction_id": "TRXQR1ZCB0DS5L",
      "player": "budi",
      "amount": "150000",
      "status": "success",
      "created_at": "2026-01-11 08:17:49",
      "type": "QRIS"
    }
  }
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
- Simpan juga `transaction_id` dari response SiTransfer
- Anggap `merchant_ref` sebagai kunci internal utama pencocokan transaksi
- Simpan response SiTransfer seperti `transaction_id`, `qris_image`, `payment_url`, `status`
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

### 400 channel harus QRIS atau DANA

Penyebab:

- client mengirim channel selain yang didukung hub

Solusi:

- gunakan salah satu channel berikut:
  - `QRIS`
  - `DANA`

### Callback tidak masuk ke server client

Checklist:

- pastikan `client_callback_url` bisa diakses publik
- pastikan firewall/server menerima request POST
- pastikan endpoint callback client membalas `2xx`
- cek log server client untuk timeout atau error 4xx/5xx

## Ringkasan Cepat

- Buat signature: `HMAC_SHA256(secret_key, client_id + timestamp + raw_body_json)`
- Kirim request ke `POST /api/client/create-transaction-sitranfer`
- Simpan `merchant_ref` dan response SiTransfer
- Terima callback dari hub di `client_callback_url`
- Verifikasi `X-Hub-Signature`
- Update transaksi internal berdasarkan `merchant_ref`
