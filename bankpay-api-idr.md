# BankPay API — IDR Integration Guide

> Base URL: `https://pay.bankpay.cfd`  
> Protocol: `POST` | Content-Type: `application/x-www-form-urlencoded;charset=utf-8`  
> Response: JSON | Callback Response: plain `OK`

---

## 🔐 Signature (MD5)

**Rules:**
1. Ambil semua parameter **yang nilainya tidak kosong** (kecuali `sign`/`pay_md5sign`)
2. Urutkan berdasarkan nama parameter **ASCII ascending** (a → z)
3. Concat dengan format `key1=value1&key2=value2&...`
4. Tambahkan `&key=MERCHANT_KEY` di akhir
5. MD5 hash → **UPPERCASE**

**Python:**
```python
import hashlib
from urllib.parse import urlencode

def generate_sign(params: dict, key: str) -> str:
    # filter non-empty, exclude sign
    filtered = [(k, v) for k, v in params.items() if v and k not in ("sign", "pay_md5sign")]
    # sort by key ASCII
    filtered.sort(key=lambda x: x[0])
    # concat + append key
    raw = urlencode(filtered) + f"&key={key}"
    # MD5 uppercase
    return hashlib.md5(raw.encode()).hexdigest().upper()

# verify callback
def verify_callback(params: dict, key: str) -> bool:
    received_sign = params.pop("sign", "")
    return generate_sign(params, key) == received_sign
```

**PHP:**
```php
function generateSign(array $params, string $key): string {
    unset($params['sign'], $params['pay_md5sign']);
    $params = array_filter($params, fn($v) => $v !== '' && $v !== null);
    ksort($params);
    $raw = http_build_query($params) . '&key=' . $key;
    return strtoupper(md5($raw));
}
```

**Node.js:**
```js
const crypto = require('crypto');

function generateSign(params, key) {
  delete params.sign;
  delete params.pay_md5sign;
  const sorted = Object.keys(params)
    .filter(k => params[k] !== '' && params[k] != null)
    .sort()
    .map(k => `${k}=${encodeURIComponent(params[k])}`)
    .join('&');
  return crypto.createHash('md5').update(`${sorted}&key=${key}`).digest('hex').toUpperCase();
}
```

---

## 💰 Topup (Deposit)

### Request
```
POST https://pay.bankpay.cfd/Pay-payment.aspx
```

| Parameter | Wajib | Sign | Keterangan |
|---|---|---|---|
| `pay_memberid` | ✅ | ✅ | Merchant ID dari platform |
| `pay_orderid` | ✅ | ✅ | Order ID unik, **16-32 karakter** |
| `pay_applydate` | ✅ | ✅ | Format: `2026-08-03 14:30:00` (UTC+8) |
| `pay_bankcode` | ✅ | ✅ | `bank` (cek halaman doc untuk IDR) |
| `pay_currency` | ✅ | ✅ | `IDR` |
| `pay_notifyurl` | ✅ | ✅ | URL callback server (urlencode jika ada `?`/`&`) |
| `pay_callbackurl` | ✅ | ✅ | URL redirect setelah user bayar |
| `pay_amount` | ✅ | ✅ | Nominal, 2 desimal. Contoh: `50000.00` |
| `pay_md5sign` | ✅ | ❌ | Hasil generate sign |
| `return_type` | ❌ | ❌ | `json` → return `payurl`, kosong → redirect ke cashier |

### Response (return_type=json)
```json
{
  "returncode": "200",
  "payurl": "https://pay.bankpay.cfd/xxx",
  "qrCode": "...",
  "qrcode": "...",
  "sign": "..."
}
```
> `qrCode` / `qrcode` = isi QR (jika ada). Redirect user ke `payurl` atau render QR.

---

## 📩 Callback (Notifikasi)

BankPay akan POST notifikasi ke `pay_notifyurl` lo begitu pembayaran sukses/gagal.

### Parameter yang dikirim BankPay
| Parameter | Keterangan |
|---|---|
| `memId` | Merchant ID |
| `orderNo` | Order ID lo |
| `transId` | Transaction ID platform |
| `payAmount` | **Nominal aktual dibayar user** (patokan!) |
| `datetime` | Format: `20260803143000` |
| `code` | **`1` = sukses**, lainnya = gagal |
| `msg` | Pesan error (jika gagal) |
| `attach` | Data dari `pay_attach` (jika dikirim) |
| `sign` | Tanda tangan — **WAJIB diverifikasi!** |

### ⚡ Yang harus lo lakukan:
1. **Verifikasi `sign`** — generate ulang dengan parameter callback + key, bandingkan
2. Kalau `sign` valid dan `code == "1"` → update status order di DB jadi **PAID**
3. **Return `OK`** (plain text, bukan JSON/HTML)

```
HTTP/1.1 200 OK
Content-Type: text/plain

OK
```

> ⚠️ Kalau lo gak return `OK`, BankPay retry notifikasi **3x**.

---

## 💸 Withdraw (Payout)

### Request
```
POST https://pay.bankpay.cfd/Pay-payment-draw.aspx
```
> Rate limit: **5 req/detik**

| Parameter | Wajib | Sign | Keterangan |
|---|---|---|---|
| `memberid` | ✅ | ✅ | Merchant ID |
| `orderid` | ✅ | ✅ | Withdraw ID unik, **16-32 karakter** |
| `bankcode` | ✅ | ✅ | `bank` |
| `notifyurl` | ✅ | ✅ | URL callback |
| `amount` | ✅ | ✅ | Nominal, 2 desimal |
| `mobile` | ✅ | ✅ | Nomor HP penerima |
| `email` | ✅ | ✅ | Email penerima |
| `pay_currency` | ✅ | ✅ | `IDR` |
| `sign` | ✅ | ❌ | Hasil generate sign |

### Pilih metode (salah satu):

**A. Bank Transfer — tambahkan:**
| Parameter | Keterangan |
|---|---|
| `bankname` | Nama bank (jangan pakai Chinese chars) |
| `cardnumber` | Nomor rekening |
| `accountname` | Nama pemilik rekening |
| `bankno` | Kode bank |

**B. UPI / E-Wallet — tambahkan:**
| Parameter | Keterangan |
|---|---|
| `accountname` | Nama penerima |
| `vpa` | UPI ID / nomor e-wallet |

### Response
**Sukses:**
```json
{
  "status": 1,
  "msg": {
    "memberid": "10002",
    "transaction_id": "20210101104300485bf84f7b",
    "orderid": "WD20260803...",
    "amount": "50000",
    "trade_state": "SUCCESS"
  }
}
```

**Gagal:**
```json
{
  "status": 0,
  "msg": "Error 99, The withdrawal amount is too small"
}
```

### Callback Withdraw
Sama seperti callback topup, parameter yang dikirim:
| Parameter | Keterangan |
|---|---|
| `memberid` | Merchant ID |
| `orderid` | Order ID lo |
| `transaction_id` | Transaction ID platform |
| `amount` | Nominal aktual |
| `datetime` | `20260803143000` |
| `returncode` | **`00` = sukses**, lainnya gagal |
| `msg` | Pesan error |
| `sign` | Verifikasi! |

Return `OK` setelah verifikasi.

---

## 🏦 Bank List

### Request
```
POST https://pay.bankpay.cfd/Pay-payment.aspx
```

| Parameter | Keterangan |
|---|---|
| `memberid` | Merchant ID |
| `handle_type` | **`getBankList`** |
| `currency` | `IDR` |
| `sign` | Generate sign |

### Response
```json
{
  "status": "200",
  "bankList": [
    {"bankCode": "BCA", "bankName": "Bank Central Asia"},
    {"bankCode": "BNI", "bankName": "Bank Negara Indonesia"},
    ...
  ]
}
```

---

## 🧾 Query (Opsional)

### Query Order
```
POST https://pay.bankpay.cfd/Pay-Trade-query.aspx
```
Params: `memberid`, `orderid`, `sign`

### Response
```json
{
  "returncode": "00",
  "trade_state": "SUCCESS",
  "memberid": "10002",
  "orderid": "IDR...",
  "amount": "50000.00",
  "act_amount": "50000.00",
  "transaction_id": "xxx",
  "success_time": "2026-08-03 14:35:00"
}
```

### Query Withdraw
```
POST https://pay.bankpay.cfd/Pay-Trade-dfquery.aspx
```
Params: `memberid`, `orderid`, `sign`

### Response
```json
{
  "returncode": "00",
  "trade_state": "SUCCESS",
  "memberid": "10002",
  "orderid": "WD...",
  "amount": "50000.00",
  "fee": "2500.00",
  "cldatetime": "2026-08-03 14:35:00"
}
```
> `trade_state`: `WAIT PAY` (pending) | `SUCCESS` | `REFUSE`

---

## 🔑 Credential (Dari Platform)

| Item | Ket |
|---|---|
| Merchant ID (`pay_memberid`) | Dapat dari BankPay |
| Key (`MERCHANT_KEY`) | Dapat dari BankPay |

---

## ⚠️ Important Notes
- **Verifikasi `sign` callback** — jangan pernah percaya notifikasi tanpa verifikasi
- Return `OK` ke callback — polos, tanpa kutip, tanpa spasi
- `pay_amount` satuan IDR, 2 desimal: `50000.00` = Rp 50.000
- `pay_orderid` harus unik per transaksi, 16-32 karakter
- Callback URL: urlencode kalau ada query params (`?` / `&`)
- Timezone: pakai **UTC+8** (WITA)
- Testing HTTPS error? Pakai `http://pay.bankpay.cfd` (non-SSL)
