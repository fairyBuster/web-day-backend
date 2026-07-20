# Dokumentasi Integrasi API ATPAY

## 1. Informasi Endpoint

**Base URL (Request Address):**
```
https://test.wowpay.biz
```

## 2. Tujuan Dokumen

Dokumen ini digunakan sebagai panduan bagi merchant untuk melakukan integrasi dengan sistem payment gateway ATPAY. Mohon agar tim development terkait membaca dokumen ini secara detail.

## 3. Target Pembaca

Perancang sistem merchant, programmer, dan tim tester/QA.

## 4. Catatan Keamanan (Penting!)

Beberapa hal yang **wajib diperhatikan** karena berpotensi menimbulkan kerugian selama proses integrasi:

1. **Jaga kerahasiaan Secret Key.** Jika key bocor, pihak tidak bertanggung jawab dapat memalsukan notifikasi asinkron (async notification), sehingga order yang sebenarnya belum dibayar bisa lolos validasi tanda tangan dan diproses seolah-olah sudah dibayar — ini berpotensi menimbulkan kerugian.
2. Setelah order berhasil dibayar, sistem akan mengirimkan hasil transaksi ke `notify_url` (notifikasi asinkron). Setelah signature tervalidasi, **pastikan jumlah pembayaran pada notifikasi sesuai dengan jumlah yang benar-benar dibayarkan user**.
3. `result_url` adalah URL redirect untuk user (notifikasi sinkron). Setelah pembayaran selesai, atau saat user klik tombol kembali/cek status, browser akan diarahkan ke URL ini, dan sistem juga akan otomatis memanggil endpoint query untuk mengecek status order. **Namun, redirect ini tidak dapat dijadikan bukti/acuan resmi status pembayaran** — tidak semua metode pembayaran mendukung redirect otomatis.
4. IP server callback adalah:
   - IPv4: `86.38.247.84`
   - IPv6: `fe80::be24:11ff:feb8:ed4c`
   
   Jika sistem merchant menerapkan IP whitelist, **wajib menambahkan IP di atas ke dalam whitelist**.

## 5. Alur Proses Pembayaran

1. Merchant membuat order berdasarkan aktivitas pembayaran pelanggan (berisi nomor merchant, nomor order, jumlah, dan parameter pembayaran lain), lalu mengirimkan request pembayaran (create deposit).
2. Sistem ATPAY memproses data request tersebut — melakukan validasi keamanan dan verifikasi lainnya. Setelah semua validasi lolos, request akan diproses.
3. Setelah user menyelesaikan pembayaran, sistem akan mengirim hasil pembayaran melalui **notifikasi asinkron** — server ATPAY akan secara aktif memanggil URL yang telah ditentukan merchant di parameter `notify_url` (jika parameter ini tidak diisi, notifikasi ini tidak akan dikirim).
4. Setelah merchant menerima notifikasi asinkron sukses, merchant wajib mengembalikan response konfirmasi ke ATPAY dan menyelesaikan proses bisnis terkait (misalnya update status order, kirim barang, dsb).
5. Setelah langkah ke-4 selesai, sistem akan melakukan **notifikasi sinkron** — user akan otomatis di-redirect kembali ke halaman yang ditentukan merchant melalui parameter `result_url` (jika parameter `result_url` kosong, redirect ini tidak akan dilakukan).

## 6. Protokol Komunikasi & Format Data

| Item | Ketentuan |
|---|---|
| Metode request | `POST` |
| Content-Type | `application/json; charset=utf-8` |
| Format data | JSON (baik request maupun response) |
| Encoding karakter | UTF-8 |
| Algoritma signature | `MD5withRsa` atau `MD5` |
| Validasi signature | Request maupun response wajib diverifikasi signature-nya (lihat bagian Digital Signature) |
| Urutan pengecekan | 1) field status protokol → 2) status bisnis → 3) status transaksi |

## 7. Algoritma Digital Signature

### 7.1 Metode Signature

Platform mendukung dua metode signature: `MD5withRsa` dan `MD5`. Callback juga akan menggunakan metode signature yang sama dengan metode saat request dikirim.

### 7.2 Cara Penggunaan Key

**MD5withRsa:**
- **ATPAY → Merchant (callback):** ATPAY menandatangani (sign) menggunakan **private key ATPAY**; merchant memverifikasi signature menggunakan **public key ATPAY**.
- **Merchant → ATPAY (request):** Merchant menandatangani menggunakan **private key merchant**; ATPAY memverifikasi signature menggunakan **public key merchant**.

**MD5:**
- **ATPAY → Merchant (callback):** ATPAY mengenkripsi parameter menggunakan **secret key merchant**; merchant memverifikasi menggunakan secret key yang sama.
- **Merchant → ATPAY (request):** Merchant menandatangani menggunakan **secret key merchant**; ATPAY memverifikasi menggunakan secret key yang sama.

### 7.3 Aturan Penyusunan String (String Concatenation)

Aturan berikut berlaku baik untuk merchant maupun untuk ATPAY.

**Langkah 1:**
Misalkan seluruh parameter yang dikirim membentuk kumpulan **M**. Ambil semua parameter dalam **M** yang nilainya **tidak kosong**, urutkan berdasarkan nama parameter secara **ASCII ascending (dictionary order)**, lalu gabungkan dalam format URL key-value (`key1=value1&key2=value2...`) menjadi string **stringA**.

Aturan penting yang wajib diperhatikan:
1. Nama parameter diurutkan ASCII ascending (dictionary order).
2. Parameter dengan nilai kosong **tidak** diikutsertakan dalam signature.
3. Nama parameter bersifat **case-sensitive**.
4. Parameter `sign` **tidak** diikutsertakan dalam proses signing.

**MD5withRsa:**
- Langkah 2: Lakukan enkripsi RSA terhadap `stringA`, hasilnya adalah nilai `signValue`.

**MD5:**
- Langkah 2: Tambahkan `&key=secretkey` di akhir `stringA` untuk membentuk `stringB`, lalu lakukan hashing MD5 terhadap `stringB` untuk mendapatkan string 32 karakter sebagai `signValue`. Terakhir, ubah `signValue` menjadi huruf **kapital (uppercase)**.

---

## 8. Endpoint: Create Deposit (Inisiasi Pembayaran/Deposit)

**URL:**
```
POST https://{request_address}/gw-api/deposit/create
```

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant yang diberikan oleh sistem pembayaran |
| `out_trade_sn` | Ya | string, maks 50 karakter | Nomor order dari merchant |
| `title` | Tidak | string, maks 200 karakter | Nama produk, boleh kosong |
| `amount` | Ya | string, 2 desimal | Jumlah pembayaran |
| `user_name` | Tidak | string | Nama pembayar — **wajib untuk Thailand**, opsional negara lain |
| `bank_card_no` | Tidak | string | Nomor kartu/rekening pembayar — **wajib untuk Thailand**, opsional negara lain |
| `attach` | Tidak | string, maks 255 karakter | Informasi tambahan, dikembalikan apa adanya, boleh kosong |
| `return_url` | Tidak | string, maks 255 karakter | Opsional — halaman redirect setelah pembayaran sukses |
| `notify_url` | Ya | string, maks 255 karakter | URL callback |
| `sign_type` | Ya | string | Metode signature: `MD5withRsa` atau `MD5` |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | Status request — `100` = sukses, selain itu = gagal |
| `message` | Ya | string | Pesan informasi request |
| `data` | Ya | object | Body data (lihat di bawah) |
| `data.order_sn` | Ya | string | Nomor order sistem (ATPAY) |
| `data.trade_url` | Ya | string | URL halaman cashier/checkout |

### Contoh Request

```
merchant_no   : xxIKjgDUwmxsqEtu
out_trade_sn  : 20260720014126
title         : Test Product
amount        : 100
attach        : Test Product
return_url    : http://127.0.0.1:8000
notify_url    : http://127.0.0.1:8000
sign_type     : MD5withRsa
sign          : jVCDFmb+c2XCEWGOKhw3LJID6XOye9lmQGh/sZcP5nrNu+RiBt2bwxSRONcblen8sYBlz/Ut98RvriT2QR32L7+yQ3sszk1Jg8NcyOvN++sI8mOyjwu2puBfesOFUOT0cUAVOf6UB462FBl8ncsYwgxuQINkB+pNJOqjlWHZzWMFb2t25BE/zHeG+xxkKhEJTBtSnOdLFATIoFaeQU8BmC9V1i84AUYn4OXgPs2zy6Gjn7Cwi7MTTg5nap/BnkackmqgtXizLsS0TEYR+Q+PIO3RLSE9NQtqKDKvh9XrBOCA2t1WXjhmz84oAphCyeA3Pdi8WZyHf4ogYbZSaolOSQ==
```

---

## 9. Callback: Notifikasi Deposit (Payment Callback)

### Parameter Notifikasi

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `out_trade_sn` | Ya | string, maks 50 karakter | Nomor order dari merchant |
| `order_sn` | Ya | string, maks 50 karakter | Nomor order sistem |
| `amount` | Ya | string | Jumlah pembayaran |
| `payment_time` | Ya | string | Waktu pembayaran, format `yyyy-MM-dd HH:mm:ss` |
| `attach` | Tidak | string | Informasi tambahan |
| `trade_status` | Ya | string | Status transaksi: `pending` (belum dibayar), `success` (sukses), `timeout` (kedaluwarsa/belum dibayar), `failed` (gagal) |
| `sign_type` | Ya | string | Metode signature: `MD5withRsa` atau `MD5` |
| `sign` | Ya | string | Signature (parameter ini sendiri tidak diikutsertakan dalam proses signing) |

### Contoh Simulasi Callback

```
merchant_no   : xxIKjgDUwmxsqEtu
out_trade_sn  : 20260720014126
order_sn      : 20260720014126
amount        : 100
payment_time  : 2026-07-20 01:41:26
trade_status  : success
attach        : Test Callback
sign_type     : MD5withRsa
```

---

## 10. Endpoint: Query Deposit (Cek Status Pembayaran)

**URL:**
```
POST https://{request_address}/gw-api/deposit/query
```

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `out_trade_sn` | Ya | string, maks 50 karakter | Nomor order dari merchant |
| `order_sn` | Ya | string, maks 50 karakter | Nomor order sistem |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | `100` = sukses |
| `message` | Ya | string | Pesan informasi |
| `data` | Ya | object | Body data |
| `data.merchant_no` | Ya | string | Nomor merchant |
| `data.out_trade_sn` | Ya | string, maks 50 | Nomor order merchant |
| `data.order_sn` | Ya | string, maks 50 | Nomor order sistem |
| `data.amount` | Ya | decimal, 2 desimal | Jumlah pembayaran |
| `data.payment_time` | Ya | string | Waktu pembayaran, `yyyy-MM-dd HH:mm:ss` |
| `data.trade_status` | Ya | string | `pending`, `success`, `expired`, `failed` |

---

## 11. Endpoint: Create Payout (Inisiasi Pencairan/Withdraw)

**URL:**
```
POST https://{request_address}/gw-api/payout/create
```

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `out_trade_sn` | Ya | string, maks 50 | Nomor order dari merchant |
| `amount` | Ya | string, 2 desimal | Jumlah pencairan |
| `trade_account` | Ya | string, maks 50 | Nama pemilik rekening penerima |
| `trade_number` | Ya | string, maks 50 | Nomor rekening bank / akun penerima |
| `attach` | Tidak | string, maks 255 | Informasi tambahan, dikembalikan apa adanya |
| `pix` | Tidak | string, maks 255 | **Wajib untuk pembayaran Brasil** |
| `pix_type` | Tidak | string, maks 255 | **Wajib untuk Brasil**, nilai harus salah satu dari: `CPF`, `PHONE`, `EMAIL`, `CNP`, `EVP` |
| `ifsc` | Tidak | string, maks 255 | **Wajib untuk pembayaran India** |
| `bank_code` | Tidak | string, maks 255 | **Wajib untuk Indonesia, Nigeria, Pakistan** (kode bank/e-wallet: OVO, GOPAY, GOPAYDRIVER, SHOPEEPAY, LINKAJA, DANA); **wajib juga untuk Filipina, Thailand, Meksiko** (kode bank) |
| `notify_url` | Ya | string, maks 255 | URL callback |
| `mobile` | Tidak | string, maks 255 | Nomor HP — memengaruhi kecepatan pencairan; **wajib untuk Kolombia** |
| `email` | Tidak | string, maks 255 | Email — memengaruhi kecepatan pencairan; **wajib untuk Kolombia** |
| `identity` | Tidak | string, maks 255 | Nomor identitas — memengaruhi kecepatan pencairan; **wajib untuk Kolombia dan Pakistan** |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | `100` = sukses |
| `message` | Ya | string | Pesan informasi |
| `data` | Ya | object | Body data |
| `data.order_sn` | Ya | string | Nomor order sistem |

---

## 12. Callback: Notifikasi Payout (Payout Callback)

### Parameter Notifikasi

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `out_trade_sn` | Ya | string, maks 50 | Nomor order dari merchant |
| `order_sn` | Ya | string, maks 50 | Nomor order sistem |
| `amount` | Ya | string | Jumlah pencairan |
| `pay_time` | Ya | string | Waktu pembayaran, `yyyy-MM-dd HH:mm:ss` |
| `attach` | Tidak | string | Informasi tambahan |
| `trade_status` | Ya | string | `pending`, `success`, `rejected` (ditolak), `failed` |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature (tidak diikutsertakan dalam proses signing) |

---

## 13. Endpoint: Query Payout (Cek Status Pencairan)

**URL:**
```
POST https://{request_address}/gw-api/payout/query
```

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `out_trade_sn` | Ya | string, maks 50 | Nomor order dari merchant |
| `order_sn` | Ya | string, maks 50 | Nomor order sistem |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | `100` = sukses |
| `message` | Ya | string | Pesan informasi |
| `data` | Ya | object | Body data |
| `data.merchant_no` | Ya | string | Nomor merchant |
| `data.out_trade_sn` | Ya | string, maks 50 | Nomor order merchant |
| `data.order_sn` | Ya | string, maks 50 | Nomor order sistem |
| `data.amount` | Ya | decimal, 2 desimal | Jumlah pencairan |
| `data.payment_time` | Ya | string | Waktu pembayaran |
| `data.trade_status` | Ya | string | `pending`, `success`, `rejected` (ditolak), `failed` |

---

## 14. Endpoint: Query Bank Code (Daftar Kode Bank)

**URL:**
```
POST https://{request_address}/gw-api/bank-code
```

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | `100` = sukses |
| `message` | Ya | string | Pesan informasi |
| `data` | Ya | array | Daftar kode bank |
| `data[].bank_code` | Ya | string | Kode bank |
| `data[].bank_name` | Ya | string, maks 50 | Nama bank |

---

## 15. Endpoint: Query Balance (Cek Saldo Merchant)

**URL:**
```
POST https://{request_address}/gw-api/balance/query
```

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | `100` = sukses |
| `message` | Ya | string | Pesan informasi |
| `data` | Ya | object | Body data |
| `data.currency` | Ya | string | Mata uang |
| `data.balance` | Ya | string | Total saldo |
| `data.usable_balance` | Ya | string | Saldo yang dapat digunakan |

---

## 16. Endpoint: Query by UTR (Cek Order via UTR)

**URL:**
```
POST https://{request_address}/gw-api/utr/query
```

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `utr` | Ya | int | Kode UTR (12 digit) |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | `100` = sukses |
| `message` | Ya | string | Pesan informasi |
| `data` | Ya (hanya jika `code`=100) | object | Body data |
| `data.status` | Ya | string | Status order: `success` (sudah selesai/complete), `pending` (dapat dilakukan proses "补单" / manual match order) |
| `data.order_sn` | Ya (jika `status`=`success`) | string, maks 50 | Nomor order sistem (platform) |
| `data.amount` | Ya | decimal, 2 desimal | Jumlah pembayaran |

---

## 17. Endpoint: Confirm by UTR (Manual Match Order via UTR)

**URL:**
```
POST https://{request_address}/gw-api/utr/confirm
```

Endpoint ini digunakan untuk mencocokkan (memasangkan) pembayaran dengan order secara manual menggunakan kode UTR, misalnya jika ada pembayaran yang masuk namun belum otomatis ter-link ke order manapun.

### Request Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `merchant_no` | Ya | string | Nomor merchant |
| `utr` | Ya | int | Kode UTR (12 digit) |
| `order_sn` | Tidak* | string, maks 50 | Nomor order sistem — *salah satu dari `order_sn` atau `out_trade_sn` wajib diisi |
| `out_trade_sn` | Tidak* | string, maks 50 | Nomor order merchant — *salah satu dari `order_sn` atau `out_trade_sn` wajib diisi |
| `sign_type` | Ya | string | Metode signature |
| `sign` | Ya | string | Signature |

### Response Parameters

| Parameter | Wajib | Tipe | Keterangan |
|---|---|---|---|
| `code` | Ya | string | `100` = sukses |
| `message` | Ya | string | Pesan informasi |

---

## Catatan Kredensial Merchant Testing

> ⚠️ **Perhatian:** Terdapat perbedaan antara kredensial yang Anda berikan sebelumnya dan yang tertera di pesan asli dari pihak ATPAY. Mohon dikonfirmasi ulang mana yang aktif digunakan.

| Item | Dari Anda | Dari Pesan ATPAY |
|---|---|---|
| URL Backend | `https://test.wowpay.biz` | `https://test.wowpay.biz/` |
| Username | `ampli` | `ampli` |
| Password | `fairyBuster555` | `aa123123` |

**Langkah lanjutan yang disarankan:**
1. Login ke `https://test.wowpay.biz/` untuk mengecek dokumen resmi di menu **Manajemen Sistem (System Management)** — dokumen di backend biasanya lebih update dibanding versi teks ini.
2. Tambahkan IP server Anda ke **whitelist IP** melalui menu **Manajemen Sistem → Whitelist IP**.
3. Ambil **public key ATPAY** (jika pakai `MD5withRsa`) atau **secret key** (jika pakai `MD5`) dari backend, lalu simpan private key Anda sendiri dengan aman.
4. Lakukan uji coba (testing) end-to-end di environment testing, lalu kirim nomor order ke tim ATPAY untuk pengujian callback.
5. Setelah lolos testing, minta pembukaan merchant resmi (production).

**Jam operasional support:**
- Tim teknis: 11:30 – 01:00 (Waktu Beijing/China Standard Time)
- Customer service: 24/7
