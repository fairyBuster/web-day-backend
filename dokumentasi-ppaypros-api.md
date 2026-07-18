# Dokumentasi Integrasi API PPay Pros

## 1. Informasi Umum

| Item | Nilai |
|---|---|
| Domain API | `https://pay.ppaypros.com` |
| IP unik platform (untuk whitelist) | `3.1.16.96` |
| Metode transmisi | HTTPS |
| Metode submit | POST / GET |
| Content-Type | `application/json` |
| Encoding | UTF-8 |
| Algoritma signature | MD5 |
| Format nominal | Integer, satuan **sen/poin** (bukan desimal). Contoh: Rp100 dikirim sebagai `10000` (x100) |

> Catatan: Tidak boleh ada nilai desimal pada parameter nominal.

---

## 2. Format Response Standar

Semua endpoint mengembalikan struktur berikut:

| Parameter | Wajib | Tipe | Contoh | Keterangan |
|---|---|---|---|---|
| `code` | ya | int | `0` | `0` = sukses, selain itu = gagal |
| `msg` | tidak | String(128) | `Signature failed` | Alasan error (signature gagal, format parameter salah, dll) |
| `sign` | tidak | String(32) | `1F0A241B...` | Signature dari isi `data`. Jika `data` kosong, `sign` tidak dikirim |
| `data` | tidak | String(512) JSON | `{}` | Data hasil, dalam format JSON |

### Kode Error Umum

| code | msg | Keterangan |
|---|---|---|
| `0` | success | Berhasil |
| `9999` | abnormal | Cek detail di field `msg` |

---

## 3. Algoritma Signature (Sangat Penting)

**Langkah 1** — Ambil semua parameter yang dikirim/diterima (set M), buang parameter yang nilainya kosong, lalu urutkan **ascending berdasarkan ASCII nama parameter** (urut abjad). Gabungkan jadi string `key1=value1&key2=value2...` (disebut `stringA`).

Aturan penting:
- Parameter kosong **tidak** ikut ditandatangani.
- Nama parameter **case-sensitive**.
- Saat verifikasi response/callback, parameter `sign` yang diterima **tidak** ikut dihitung ulang — dibandingkan saja dengan hasil hitung kamu.
- Jika API menambah field baru di masa depan, proses sorting harus tetap dinamis (jangan hardcode urutan field).

**Langkah 2** — Tambahkan private key di akhir: `stringA + "&key=" + PRIVATE_KEY` → hasilnya `stringSignTemp`. MD5-kan, lalu **uppercase semua** → itulah `sign`.

### Contoh (dari dokumentasi resmi)

Body request:
```json
{
  "mchNo": "M1678608801",
  "appId": "640d89a158b4461f100cca20",
  "mchOrderNo": "20230313142102367372",
  "amount": "50000",
  "customerName": "Joey",
  "customerEmail": "13800138000@gmail.com",
  "customerPhone": "13800138000",
  "notifyUrl": "https://ppaypro.ccom/pay"
}
```

String sebelum MD5 (`stringSignTemp`):
```
amount=50000&appId=640d89a158b4461f100cca20&customerEmail=13800138000@gmail.com&customerName=Joey&customerPhone=13800138000&mchNo=M123454545&mchOrderNo=20230313142102367372&notifyUrl=https://3qpay.cc/pay/notify&key=PRIVATE_KEY
```

Hasil MD5 uppercase → `sign`:
```
5B9B18CECEF621EF221ABE687DA904B0
```

### Contoh kode (Node.js)

```javascript
const crypto = require('crypto');

function generateSign(params, privateKey) {
  // 1. Buang parameter kosong/null, buang field 'sign' itu sendiri
  const filtered = Object.entries(params)
    .filter(([k, v]) => v !== undefined && v !== null && v !== '' && k !== 'sign');

  // 2. Urutkan ascending berdasarkan nama key
  filtered.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));

  // 3. Gabung jadi key1=value1&key2=value2...
  const stringA = filtered.map(([k, v]) => `${k}=${v}`).join('&');

  // 4. Tambahkan private key
  const stringSignTemp = `${stringA}&key=${privateKey}`;

  // 5. MD5 lalu uppercase
  return crypto.createHash('md5').update(stringSignTemp, 'utf8').digest('hex').toUpperCase();
}

module.exports = { generateSign };
```

---

## 4. Daftar Kode Metode Pembayaran (`wayCode`)

Opsional — hanya diperlukan kalau satu negara punya lebih dari satu metode pembayaran.

| Kode | Metode |
|---|---|
| 801 | India - UPI |
| 802 | India - PAYTM |
| 803 | Malaysia - Online Banking |
| 804 | Malaysia - Wallet QR Code |
| 805 | Brazil - PIX |
| 806 | Filipina - GCash |
| 807 | Filipina - MAYA |
| 808 | **Indonesia - Online Banking (B2C)** |
| 809 | **Indonesia - E-Wallet** |

---

## 5. Endpoint: Payin (Terima Pembayaran)

### `POST /api/pay/pay`

Membuat order penagihan/pembayaran dari customer.

**Request:**

| Parameter | Wajib | Tipe | Contoh | Keterangan |
|---|---|---|---|---|
| `mchNo` | ya | String(32) | `M1234567890` | Merchant ID |
| `appId` | ya | String(32) | `60cc09bce4b0f1c0b83761c9` | Application ID |
| `mchOrderNo` | ya | String(32) | `202205101000000000` | Nomor order unik dari sistem kamu |
| `amount` | ya | int | `10000` | Nominal (satuan poin, x100) |
| `customerName` | ya | String(64) | `Budi` | Nama customer |
| `customerEmail` | ya | String(64) | `budi@gmail.com` | Email customer |
| `customerPhone` | ya | String(64) | `081234567890` | No. HP customer |
| `wayCode` | tidak | String(32) | `808` atau `809` | Wajib diisi jika Indonesia butuh spesifik online banking (808) atau e-wallet (809) |
| `extParam` | tidak | String(32) | `BRI` | **Indonesia (opsional):** untuk pembayaran via VA bank, isi kode bank: `BRI`, `BNI`, `PERMATA`, `CIMB`, `MANDIRI` |
| `notifyUrl` | tidak | String(128) | `https://domainmu.com/notify` | URL callback asynchronous. Kalau tidak diisi, kamu **tidak akan** menerima notifikasi otomatis |
| `returnUrl` | tidak | String(128) | `https://domainmu.com/return` | URL redirect setelah pembayaran (untuk customer) |
| `sign` | ya | String(32) | — | Lihat bagian Signature |

**Response — `data`:**

| Parameter | Tipe | Keterangan |
|---|---|---|
| `payOrderId` | String(32) | Nomor order dari sistem PPay |
| `mchOrderNo` | String(32) | Nomor order dari sistem kamu |
| `orderState` | int | `0`=dibuat, `1`=diproses, `2`=**sukses**, `3`=gagal, `4`=dibatalkan, `5`=refund diterima, `6`=ditutup, `7`=menunggu settlement |
| `payDataType` | String | Tipe data pembayaran: `payUrl` (link redirect), `form`, `codeUrl` (link QR), `codeImgUrl` (gambar QR), `none` |
| `payData` | String | Data pembayaran (isi tergantung `payDataType`) |
| `upiData` | String | Khusus channel UPI |
| `errCode` / `errMsg` | String | Kode/pesan error dari upstream, jika ada |

---

## 6. Endpoint: Query Status Payin

### `POST /api/pay/query`

Cek status order penagihan.

**Request:**

| Parameter | Wajib | Keterangan |
|---|---|---|
| `mchNo`, `appId` | ya | Sama seperti di atas |
| `payOrderId` **atau** `mchOrderNo` | ya | Cukup kirim salah satu (boleh dua-duanya) |
| `sign` | ya | Signature |

**Response — `data`:**

| Parameter | Keterangan |
|---|---|
| `payOrderId`, `mchOrderNo`, `mchNo`, `appId` | Identitas order |
| `amount` | Nominal (poin) |
| `currency` | Kode mata uang (`INR`, `BRL`, dst) |
| `state` | `1`=diproses, `2`=sukses, `3`=gagal, `6`=ditutup, `7`=menunggu settlement |
| `errCode` / `errMsg` | Error dari channel, jika ada |
| `extParam` | Dikembalikan sama seperti saat dikirim |
| `createdAt` | Timestamp 13-digit, waktu order dibuat |
| `successTime` | Timestamp 13-digit, waktu sukses (jika ada) |

---

## 7. Endpoint: Supply UTR (Reissue/Susulan Notifikasi)

### `POST /api/pay/supply`

Digunakan merchant untuk mengirim ulang bukti transaksi bank (UTR) jika order belum ter-update otomatis.

> ⚠️ Disarankan tidak langsung mengubah status order manual segera setelah order dibuat — tunggu callback asli terlebih dahulu.

**Request:**

| Parameter | Wajib | Keterangan |
|---|---|---|
| `mchNo`, `appId` | ya | Identitas merchant |
| `utrCode` | ya | Nomor UTR dari bank |
| `mchOrderNo` | ya | Nomor order kamu |
| `sign` | ya | Signature |

**Response — `data`:** `payOrderId`, `mchOrderNo`, `state` (`1`=proses, `2`=sukses, `3`=gagal, `6`=ditutup), `errMsg`.

---

## 8. Endpoint: Payout (Kirim Dana / Transfer)

### `POST /api/payout/pay`

**Request:**

| Parameter | Wajib | Tipe | Contoh | Keterangan |
|---|---|---|---|---|
| `mchNo`, `appId` | ya | — | — | Identitas merchant |
| `mchOrderNo` | ya | String(32) | — | Nomor order kamu |
| `amount` | ya | int | `10000` | Nominal (poin) |
| `entryType` | ya | String(10) | `BANK_CARD` | Metode terima dana. **Indonesia menggunakan `BANK_CARD`** (negara lain punya opsi lain seperti IMPS/UPI untuk India, EVP/CPF/CNPJ/PHONE/EMAIL untuk Brazil, GCASH/MAYA untuk Filipina) |
| `accountNo` | ya | String(64) | — | Nomor rekening/kartu penerima |
| `accountCode` | ya | String(64) | `BRI` | Untuk `BANK_CARD`: **kode bank Indonesia** (lihat Lampiran A) |
| `bankName` | tidak | String(64) | — | Nama/kode bank tambahan (opsional untuk Indonesia karena sudah diwakili `accountCode`) |
| `accountName` | ya | String(64) | `Budi Santoso` | Nama pemilik rekening |
| `accountEmail` | ya | String(64) | — | Email penerima |
| `accountPhone` | ya | String(16) | — | No. HP penerima |
| `channelExtra` | tidak | String(512) | — | Tidak wajib untuk Indonesia (dipakai negara lain seperti Peru/Kolombia/Pakistan) |
| `notifyUrl` | tidak | String(128) | — | URL callback saat transfer selesai |
| `extParam` | tidak | String(512) | — | Dikembalikan sama saat callback |
| `sign` | ya | — | — | Signature |

**Response — `data`:**

| Parameter | Keterangan |
|---|---|
| `transferId` | Nomor transfer dari sistem PPay |
| `mchOrderNo` | Nomor order kamu |
| `amount` | Jumlah diterima (setelah potong fee) |
| `mchFeeAmount` | Biaya transfer |
| `amountTo` | Total termasuk fee |
| `accountNo`, `accountName` | Data rekening tujuan |
| `state` | `0`=dibuat, `1`=diproses, `2`=**sukses**, `3`=gagal, `4`=ditutup |
| `errCode` / `errMsg` | Error dari channel, jika ada |

> ⚠️ Jika request timeout / tidak ada response, **jangan langsung anggap gagal** — wajib cek ulang lewat endpoint Query Payout.

---

## 9. Endpoint: Query Status Payout

### `POST /api/payout/query`

**Request:** `mchNo`, `appId`, (`transferId` **atau** `mchOrderNo`), `sign`.

**Response — `data`:** sama seperti response Payout di atas, ditambah:

| Parameter | Keterangan |
|---|---|
| `entryType` | Metode transfer yang dipakai |
| `bankName` | Nama bank tujuan (khusus catatan) |
| `transferDesc` | Catatan transfer |
| `voucher` | Bukti pembayaran (India → UTR, Brazil → link voucher) |
| `createdAt` / `successTime` | Timestamp 13-digit |

---

## 10. Endpoint: Cek Saldo

### `POST /api/payout/balance`

**Request:** `mchNo`, `appId`, `sign`.

**Response — `data`:**

| Parameter | Keterangan |
|---|---|
| `balance` | Saldo akun penerimaan (payin), satuan poin |
| `payoutBalance` | Saldo akun pengiriman (payout), satuan poin |
| `agentBalance` | Saldo akun yang dibekukan/freeze |
| `errCode` / `errMsg` | Jika ada |

---

## 11. Callback / Webhook

### 11.1 Callback Payin

- **URL**: sesuai `notifyUrl` yang kamu kirim di endpoint Payin.
- **Method**: `POST`
- **Content-Type**: `application/x-www-form-urlencoded`
- Parameter dikirim sebagai query string di URL: `?payOrderId=...&mchOrderNo=...&sign=...&channelOrderNo=...&customerName=...&createdAt=...&customerPhone=...&appId=...&clientIp=...&customerEmail=...&currency=...&state=...&mchNo=...`

**Parameter penting:**

| Parameter | Keterangan |
|---|---|
| `payOrderId`, `mchOrderNo`, `mchNo`, `appId` | Identitas order |
| `amount` | Nominal (poin) |
| `currency` | Kode mata uang |
| `state` | `2` = **sukses & settlement selesai**, `3` = gagal |
| `sign` | Signature — **wajib diverifikasi** sebelum diproses |

**Contoh URL callback:**
```
https://domainmu.com/notify?amount=5000&payOrderId=P1529007840911642626&mchOrderNo=10010803437_405f8_239c2_1002&sign=806BC4A76358747B2D32B39A2907A5D2&customerName=Budi&customerPhone=6281234567890&appId=62307697e4b01bee45a8e9c3&customerEmail=budi@gmail.com&state=2&mchNo=M1647343255
```

### 11.2 Callback Payout

Sama seperti Payin, tapi untuk transfer keluar. Parameter tambahan: `transferId`, `voucher` (bukti transfer).

### 11.3 Cara Merespons Callback (WAJIB)

Server kamu **harus** membalas dengan body **plain text**:

```
success
```

Aturan ketat:
- Huruf **kecil semua**, tanpa spasi/baris baru sebelum atau sesudahnya.
- Kalau tidak membalas `success`, platform akan mengulang notifikasi sampai **6 kali**, dengan jeda: `0 / 30 / 60 / 90 / 120 / 150` detik.
- Selalu **verifikasi ulang `sign`** dari data callback sebelum mengubah status order di database kamu — jangan percaya begitu saja isi callback.

### Contoh handler callback (Node.js/Express)

```javascript
const express = require('express');
const { generateSign } = require('./sign'); // fungsi dari Bab 3
const router = express.Router();

router.post('/notify/payin', (req, res) => {
  const params = { ...req.query }; // parameter callback dikirim via query string
  const receivedSign = params.sign;

  const expectedSign = generateSign(params, process.env.PPAY_PRIVATE_KEY);

  if (receivedSign !== expectedSign) {
    console.error('Signature callback tidak valid');
    return res.status(400).send('fail');
  }

  if (params.state === '2') {
    // TODO: update order jadi sukses di database
  } else if (params.state === '3') {
    // TODO: update order jadi gagal
  }

  // WAJIB: balas 'success' lowercase, tanpa spasi/newline
  res.send('success');
});

module.exports = router;
```

---

## Lampiran A — Kode Bank & E-Wallet Indonesia (`accountCode` / `extParam`)

### E-Wallet

| Kode | Nama |
|---|---|
| `dana` | DANA |
| `gopay` | GoPay |
| `linkaja` | LinkAja |
| `OV` | OVO |
| `shopeepay` | ShopeePay |

### Bank Umum (paling sering dipakai)

| Kode | Nama Bank |
|---|---|
| `BCA` | Bank BCA |
| `BNI` | Bank BNI |
| `BRI` | Bank BRI |
| `MANDIRI` | Bank Mandiri |
| `PERMATA` | Bank Permata |
| `CIMB` | CIMB Niaga |
| `DANAMON` | Bank Danamon |
| `BTN` | Bank BTN |
| `BUKOPIN` | Bank Bukopin |
| `MEGA` | Bank Mega |
| `OCBC` | Bank OCBC NISP |
| `PANIN` (`I PUT`*) | Bank Panin |
| `MAYBANK` | Bank Maybank |
| `BANK_JAGO` | Bank Jago |
| `BANK_NEO_COMMERCE` | Bank Neo Commerce (BNC) |
| `SEABANK_INDONESIA` | SeaBank |
| `BANK_SYARIAH_INDONESIA` | Bank Syariah Indonesia (BSI) |
| `BANK_BJB` | Bank BJB |
| `DKI` | Bank DKI |
| `NATIONALNOBU` | Bank Nobu |
| `ALLO_BANK_INDONESIA` | Allo Bank |
| `HSBC` | Bank HSBC |
| `CITIBANK` | Citibank |
| `STANDARD_CHARTERED` | Standard Chartered |
| `UOB` (`BANK_UOB`) | Bank UOB Indonesia |
| `DBS` | Bank DBS Indonesia |

> ⚠️ **Catatan penting**: daftar kode bank di dokumentasi asli sepertinya sudah melalui proses terjemahan otomatis dan beberapa kode terlihat janggal (misal `I PUT` untuk Bank Panin, `pocket` untuk DANA versi lama, `WATER` untuk Jabar Banten). **Sebelum go-live, sebaiknya konfirmasi ulang daftar kode bank yang valid langsung ke tim support PPay Pros**, karena kesalahan kode bank akan menyebabkan payout gagal/salah kirim.

Bank daerah (BPD) dan bank syariah lainnya juga didukung — silakan cek daftar lengkap di dokumentasi asli jika bank tujuan tidak ada di atas.

---

## Lampiran B — Checklist Sebelum Integrasi

- [ ] Dapatkan `mchNo`, `appId`, dan **private key** dari PPay Pros.
- [ ] Pastikan server/VPS kamu **whitelist IP `3.1.16.96`** kalau ada firewall ketat.
- [ ] Siapkan endpoint `notifyUrl` publik (HTTPS, bisa diakses dari luar) untuk payin & payout.
- [ ] Endpoint callback **wajib** membalas `success` (lowercase, tanpa spasi) setelah verifikasi `sign`.
- [ ] Uji signature generator kamu dengan contoh dari Bab 3 sebelum dipakai produksi.
- [ ] Selalu simpan `mchOrderNo` unik per transaksi untuk keperluan Query/Supply.
- [ ] Jangan langsung anggap order gagal kalau request timeout — panggil endpoint Query untuk konfirmasi.
- [ ] Untuk Indonesia: tentukan mau pakai `wayCode 808` (online banking) atau `809` (e-wallet), dan isi `extParam`/`accountCode` sesuai bank/wallet tujuan.
