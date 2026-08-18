# PRD — Jayapay Deposit Signature (RSA)

> Product Requirements Document untuk integrasi tanda tangan (signature) deposit Jayapay.
> Skema: **RSA Signature** (private key sign, public key verify) dengan padding **PKCS#1 v1.5 block type 1**.

---

## 1. Ringkasan

Jayapay menggunakan tanda tangan RSA untuk mengamankan request deposit (prepaid order) dan callback pembayaran. Bukan MD5/HMAC — melainkan RSA dengan operasi `c = m^d mod n` (sign) dan `m = c^e mod n` (verify).

### Alur

```
Initiate Deposit (client -> backend)
        │
        ▼
Backend susun params -> sort key -> concat nilai -> RSA sign (private key)
        │
        ▼
POST prepaidOrder -> Jayapay -> kembalikan payment_url
        │
        ▼
User bayar -> Jayapay kirim callback ke backend
        │
        ▼
Backend: RSA verify (public key) -> cocok? -> credit saldo
```

---

## 2. Scope

- **In scope**: fungsi sign, fungsi verify, format key, format nilai, alur initiate + callback, fail-safe saat public key kosong.
- **Out of scope**: enkripsi payload, withdrawal/cash request (pakai fungsi sama tapi endpoint beda).

---

## 3. Konfigurasi (GatewaySettings)

| Field | Tipe | Keterangan |
|---|---|---|
| `jayapay_enabled` | bool | Aktifkan gateway |
| `jayapay_merchant_code` | string | Merchant code dari Jayapay |
| `jayapay_private_key` | text | Body private key **PKCS#8** (tanpa header `BEGIN/END`) |
| `jayapay_public_key` | text | Body public key platform untuk verify callback |
| `jayapay_api_url` | string | Endpoint prepaidOrder |
| `app_domain` | string | Domain untuk `notifyUrl` callback |

> **PENTING**: `jayapay_private_key` dan `jayapay_public_key` disimpan **body saja** (tanpa `-----BEGIN/END-----`). Fungsi otomatis menambahkan header.

---

## 4. Spesifikasi Signature

### 4.1 Aturan Stringify Nilai

```python
def _stringify(v):
    if isinstance(v, float):
        return "{:.2f}".format(v)   # float -> 2 desimal
    if v is None:
        return ""                    # None -> kosong
    return str(v)                    # sisanya -> str()
```

### 4.2 Alur Sign (request)

1. `sorted_keys = sorted(params.keys())` — urutkan key alfabetis.
2. `params_str = "".join(_stringify(params[k]) for k in sorted_keys)` — concat nilai tanpa separator.
3. Encode UTF-8.
4. Pecah data jadi chunk `key_size - 11` bytes.
5. Setiap chunk di-padding **PKCS#1 v1.5 block type 1**: `00 01 FF...FF 00 + data`.
6. `c = pow(m, d, n)` (private key).
7. Gabung chunk -> base64 encode.

### 4.3 Alur Verify (callback)

1. Ambil field signature (`platSign` / `sign`).
2. Buang field signature dari dict, sort key, concat nilai (stringify sama).
3. Base64 decode signature, pecah per `key_size` bytes.
4. `m = pow(c, e, n)` (public key).
5. Buang padding block type 1 (cari separator `00` setelah 2 byte awal).
6. Gabung hasil decrypt, bandingkan dengan `params_str`.

---

## 5. Kode Lengkap

### 5.1 Sign (withdrawal/integrations/jayapay.py)

```python
import base64
from typing import Dict

try:
    from Crypto.PublicKey import RSA
    from Crypto.Util.number import bytes_to_long, long_to_bytes
except Exception:
    RSA = None
    bytes_to_long = None
    long_to_bytes = None


def _format_pem_body(body: str) -> str:
    """Hapus whitespace lalu wrap 64 karakter per baris (format PEM)."""
    cleaned = "".join(ch for ch in body.strip() if ch not in "\r\n ")
    return "\n".join(cleaned[i:i+64] for i in range(0, len(cleaned), 64))


def sign_params_legacy(params: Dict[str, str], private_key_pem_body: str) -> str:
    if RSA is None or bytes_to_long is None or long_to_bytes is None:
        raise RuntimeError("PyCryptodome is required: pip install pycryptodome")

    sorted_keys = sorted(params.keys())

    def _stringify(v):
        if isinstance(v, float):
            return "{:.2f}".format(v)
        if v is None:
            return ""
        return str(v)

    concat_values = "".join(_stringify(params[k]) for k in sorted_keys)
    data = concat_values.encode("utf-8")

    pem = f"-----BEGIN PRIVATE KEY-----\n{_format_pem_body(private_key_pem_body)}\n-----END PRIVATE KEY-----"
    key = RSA.import_key(pem)

    key_size_bytes = key.size_in_bytes()
    chunk_size = key_size_bytes - 11
    if chunk_size <= 0:
        chunk_size = 117

    encrypted_bytes_parts = []
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        padding_length = key_size_bytes - len(chunk) - 3
        if padding_length < 8:
            raise ValueError("Message chunk too long for RSA key size")
        padded_chunk = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + chunk
        m = bytes_to_long(padded_chunk)
        c = pow(m, key.d, key.n)
        encrypted_bytes_parts.append(long_to_bytes(c, key_size_bytes))

    full_encrypted = b"".join(encrypted_bytes_parts)
    return base64.b64encode(full_encrypted).decode("ascii")
```

### 5.2 Verify (deposits/utils.py)

```python
import base64
from Crypto.PublicKey import RSA
from Crypto.Util.number import bytes_to_long, long_to_bytes


def verify_jayapay_signature(data_dict, public_key_pem, signature_field: str = "platSign"):
    try:
        plat_sign = data_dict.get(signature_field)
        if not plat_sign:
            return False

        params = data_dict.copy()
        params.pop(signature_field, None)
        sorted_keys = sorted(params.keys())

        def _stringify(v):
            if isinstance(v, float):
                return "{:.2f}".format(v)
            if v is None:
                return ""
            return str(v)

        params_str = "".join(_stringify(params[k]) for k in sorted_keys)

        if "-----BEGIN PUBLIC KEY-----" not in public_key_pem:
            public_key_pem = (
                f"-----BEGIN PUBLIC KEY-----\n{public_key_pem.strip()}\n-----END PUBLIC KEY-----"
            )

        key = RSA.import_key(public_key_pem)
        encrypted_data = base64.b64decode(plat_sign)
        key_size_bytes = key.size_in_bytes()
        chunk_size = key_size_bytes

        decrypted_parts = []
        for i in range(0, len(encrypted_data), chunk_size):
            chunk = encrypted_data[i:i + chunk_size]
            c = bytes_to_long(chunk)
            m = pow(c, key.e, key.n)
            decrypted_chunk_padded = long_to_bytes(m, key_size_bytes)

            # Buang padding PKCS#1 v1.5 block type 1 (cari 0x00 setelah 2 byte awal)
            sep_idx = -1
            for idx, byte in enumerate(decrypted_chunk_padded):
                if idx > 2 and byte == 0:
                    sep_idx = idx
                    break

            if sep_idx != -1:
                decrypted_parts.append(decrypted_chunk_padded[sep_idx + 1:])
            else:
                decrypted_parts.append(decrypted_chunk_padded)

        decrypted_str = b"".join(decrypted_parts).decode("utf-8")
        return decrypted_str == params_str
    except Exception:
        return False
```

---

## 6. Alur Initiate Deposit (contoh potongan)

Endpoint: `POST /api/deposits/jayapay/initiate/`

```python
# Susun payload prepaid order
params = {
    'merchantCode': merchant_code,
    'orderType': '0',
    'method': '',
    'orderNum': order_num,
    'payMoney': pay_money,          # string integer, tanpa desimal
    'name': user.full_name or user.username,
    'email': user.email or '',
    'phone': user.phone or '',
    'notifyUrl': notify_url,
    'dateTime': format_datetime(now),
    'expiryPeriod': '1000',
    'productDetail': 'Top Up Saldo',
}

# Tanda tangan
params['sign'] = sign_params_legacy(params, private_key)

# Kirim ke Jayapay
resp = requests.post(api_url, json=params, timeout=30)
data = resp.json()

if data.get('platRespCode') == 'SUCCESS':
    payment_url = data.get('url')
```

---

## 7. Alur Callback (contoh potongan)

Endpoint: `POST /api/deposits/jayapay/callback/`

```python
callback = request.data
code = callback.get('code')
msg = callback.get('msg')
order_num = callback.get('orderNum')

# Jayapay selalu expect 'SUCCESS' sebagai response
if not order_num:
    return Response('SUCCESS')

trx = Transaction.objects.get(trx_id=order_num)

if code == '00' and msg == 'SUCCESS':
    is_valid = False
    public_key = (gs.jayapay_public_key or '').strip()

    if public_key:
        is_valid = verify_jayapay_signature(callback, public_key)

    if not is_valid:
        # Fail safe: jangan credit, tandai FAILED
        trx.status = 'FAILED'
        trx.save(update_fields=['status'])
        return Response('SUCCESS')

    # Signature valid -> credit saldo
    with db_transaction.atomic():
        user = trx.user
        wallet_field = 'balance' if trx.wallet_type == 'BALANCE' else 'balance_deposit'
        setattr(user, wallet_field, getattr(user, wallet_field) + trx.amount)
        user.save(update_fields=[wallet_field])
        trx.status = 'COMPLETED'
        trx.save(update_fields=['status'])
    return Response('SUCCESS')
```

---

## 8. Field Signature per Endpoint

| Endpoint | Field signature di callback | Default |
|---|---|---|
| Jayapay (deposit) | `platSign` | `platSign` |
| Jayapay PH | `sign` | `sign` (dipanggil dengan `signature_field="sign"`) |

---

## 9. Error Handling & Fail-Safe

| Kasus | Perilaku |
|---|---|
| `jayapay_public_key` kosong | `is_valid = False` -> tidak credit, tandai FAILED |
| Signature tidak cocok | FAILED + `[Invalid Callback Signature]` |
| `order_num` tidak dikenal | return `SUCCESS` (hindari retry storm) |
| Format key salah | exception -> `is_valid = False` |
| Transaction sudah COMPLETED | abaikan, return `SUCCESS` |

---

## 10. Checkpoint Troubleshooting

Jika signature gagal cocok saat callback, cek berurutan:

1. **Format key** — harus PKCS#8 (`BEGIN PRIVATE KEY` / `BEGIN PUBLIC KEY`).
2. **Field signature** — `platSign` untuk Jayapay biasa, `sign` untuk Jayapay PH.
3. **Format nilai** — float harus 2 desimal, `None` -> `""`.
4. **Urutan key** — sudah di-`sorted()` di sign dan verify (konsisten).
5. **Chunk size** — sign pakai `key_size - 11`, verify pakai `key_size`.

---

## 11. Endpoint Terkait

| Method | Path | Keterangan |
|---|---|---|
| POST | `/api/deposits/jayapay/initiate/` | Buat deposit + sign request |
| GET | `/api/deposits/jayapay/order-detail/` | Ambil detail order |
| POST | `/api/deposits/jayapay/callback/` | Callback pembayaran (verify sign) |
| POST | `/api/deposits/jayapay-ph/initiate/` | Jayapay PH initiate |
| POST | `/api/deposits/jayapay-ph/callback/` | Jayapay PH callback (field `sign`) |
