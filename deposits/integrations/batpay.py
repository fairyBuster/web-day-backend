"""BatPay Payment Gateway (api.wayrooou.online).

Skema auth HMAC-SHA256 identik dengan Reepay, jadi helper di sini di-re-export
dari deposits/integrations/reepay.py (single source of truth):
- Signature request: HMAC_SHA256(secret, timestamp_ms + method + path + body) -> hex lowercase
- Header: X-API-Key (ak_...), X-Timestamp (epoch ms), X-Signature
- Webhook:  HMAC_SHA256(secret, timestamp + "POST" + webhook_path + raw_body)

Endpoint BatPay (dipakai views di deposits/ dan withdrawal/):
- POST /gateway/charge/create            buat deposit (method kosong -> pilih method)
- POST /gateway/charge/{ref_id}/method   pilih metode: QRIS/BRI/PERMATA/MANDIRI
- GET  /gateway/charge/{ref_id}          status deposit
- POST /gateway/charge/{ref_id}/void     batal deposit
- POST /gateway/payout/create            buat payout
- GET  /gateway/payout/{ref_id}          status payout
- GET  /gateway/payout/banks             daftar bank payout
- GET  /gateway/wallet/balance           saldo wallet
- GET  /gateway/wallet/transactions      transaksi
- GET  /gateway/wallet/mutations         mutasi

Event webhook: payment.paid (deposit lunas), disbursement.processing/success/failed (payout).
Deposit expired/failed TIDAK dikirim webhook -> poll status via GET /gateway/charge/{ref_id}.
"""
from .reepay import (
    build_signature,
    verify_callback_signature,
    post_json,
    get_json,
    extract_callback_field,
)

DEFAULT_API_URL = "https://api.wayrooou.online"
