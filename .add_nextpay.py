# -*- coding: utf-8 -*-
"""Add NextPay provider by cloning the BatPay integration blocks."""
import io

D = "/home/ubuntu/web-day-backend/"

def read(p):
    with io.open(D + p, "r", encoding="utf-8") as f:
        return f.read()

def write(p, s):
    with io.open(D + p, "w", encoding="utf-8") as f:
        f.write(s)

def xform(t, extra=()):
    for a, b in [("batpay", "nextpay"), ("BatPay", "NextPay"), ("BATPAY", "NEXTPAY"),
                 ("wayrooou.online", "nextcdn.online")] + list(extra):
        t = t.replace(a, b)
    return t

def insert_after(haystack, anchor, new_block):
    assert haystack.count(anchor) == 1, "anchor not unique / missing: %r" % anchor[:80]
    return haystack.replace(anchor, anchor + new_block)

def extract_between(text, start_marker, end_marker, start_idx=0):
    i = text.index(start_marker, start_idx)
    j = text.index(end_marker, i + len(start_marker))
    return text[i:j], j

def main():
    changed = []

    # ---------- 1. deposits/models.py ----------
    p = "deposits/models.py"
    s = read(p)
    anchor = "    batpay_return_url = models.CharField(max_length=512, blank=True, default='', help_text='URL redirect setelah pembayaran selesai (opsional)')"
    block = "\n\n    # NextPay pay-in (api.nextcdn.online, skema HMAC-SHA256 sama seperti Reepay)\n" + xform(
        "    batpay_enabled = models.BooleanField(default=False)\n"
        "    batpay_api_url = models.CharField(max_length=255, blank=True, default='https://api.wayrooou.online', help_text='Base URL BatPay')\n"
        "    batpay_api_key = models.CharField(max_length=255, blank=True, default='', help_text='X-API-Key merchant (ak_...)')\n"
        "    batpay_secret_key = models.TextField(blank=True, default='', help_text='Secret key HMAC-SHA256 (347 karakter - jangan VARCHAR(255))')\n"
        "    batpay_return_url = models.CharField(max_length=512, blank=True, default='', help_text='URL redirect setelah pembayaran selesai (opsional)')"
    )
    s = insert_after(s, anchor, block)
    s = s.replace("        ('BATPAY', 'BatPay'),\n", "        ('BATPAY', 'BatPay'),\n        ('NEXTPAY', 'NextPay'),\n")
    write(p, s); changed.append(p)

    # ---------- 2. withdrawal/models.py ----------
    p = "withdrawal/models.py"
    s = read(p)
    anchor = "    batpay_payout_secret_key = models.TextField(blank=True, default='', help_text='Secret key HMAC-SHA256 payout (347 karakter - jangan VARCHAR(255))')"
    block = "\n\n" + xform(
        "    batpay_payout_enabled = models.BooleanField(default=False)\n"
        "    batpay_payout_api_url = models.CharField(max_length=255, blank=True, default='https://api.wayrooou.online', help_text='Base URL BatPay')\n"
        "    batpay_payout_api_key = models.CharField(max_length=255, blank=True, default='', help_text='X-API-Key merchant (ak_...)')\n"
        "    batpay_payout_secret_key = models.TextField(blank=True, default='', help_text='Secret key HMAC-SHA256 payout (347 karakter - jangan VARCHAR(255))')"
    )
    s = insert_after(s, anchor, block)
    anchor = '        return f"BatPay payout for Withdrawal #{self.withdrawal.pk}"'
    cls = xform(
        "\n\nclass BatPayWithdrawal(models.Model):\n"
        "    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='batpay_withdrawal')\n"
        "    request_params = models.JSONField(default=dict)\n"
        "    response_payload = models.JSONField(default=dict)\n"
        "    created_at = models.DateTimeField(auto_now_add=True)\n"
        "    updated_at = models.DateTimeField(auto_now=True)\n"
        "\n"
        "    class Meta:\n"
        "        db_table = 'withdrawal_batpay'\n"
        "        ordering = ['-created_at']\n"
        "\n"
        "    def __str__(self):\n"
        '        return f"BatPay payout for Withdrawal #{self.withdrawal.pk}"'
    )
    s = insert_after(s, anchor, cls)
    write(p, s); changed.append(p)

    # ---------- 3. deposits/integrations/nextpay.py (new file) ----------
    src = read("deposits/integrations/batpay.py")
    write("deposits/integrations/nextpay.py", xform(src))
    changed.append("deposits/integrations/nextpay.py (new)")

    # ---------- 4. deposits/views.py ----------
    p = "deposits/views.py"
    s = read(p)
    anchor = ("from .integrations.batpay import (\n"
              "    post_json as batpay_post_json,\n"
              "    verify_callback_signature as batpay_verify_callback_signature,\n"
              "    extract_callback_field as batpay_extract_callback_field,\n"
              ")\n")
    block = ("from .integrations.nextpay import (\n"
             "    post_json as nextpay_post_json,\n"
             "    verify_callback_signature as nextpay_verify_callback_signature,\n"
             "    extract_callback_field as nextpay_extract_callback_field,\n"
             ")\n")
    s = insert_after(s, anchor, block)
    # append cloned BatPay helpers+views at EOF (BatPay block is at end of file)
    marker = "\ndef _batpay_raw_body(request) -> str:"
    i = s.index(marker)
    tail = xform(s[i:], extra=[("DBP", "DNP")])
    s = s[:i].rstrip("\n") + tail
    write(p, s); changed.append(p)

    # ---------- 5. deposits/urls.py ----------
    p = "deposits/urls.py"
    s = read(p)
    anchor = "    BatPayDepositInitiateView,\n    BatPayDepositCallbackView,\n    BatPayDepositSelectMethodView,\n"
    block = "    NextPayDepositInitiateView,\n    NextPayDepositCallbackView,\n    NextPayDepositSelectMethodView,\n"
    s = insert_after(s, anchor, block)
    anchor = ("    path('batpay/initiate/', BatPayDepositInitiateView.as_view(), name='deposit-batpay-initiate'),\n"
              "    path('batpay/select-method/', BatPayDepositSelectMethodView.as_view(), name='deposit-batpay-select-method'),\n"
              "    path('batpay/callback/', BatPayDepositCallbackView.as_view(), name='deposit-batpay-callback'),\n")
    block = ("    path('nextpay/initiate/', NextPayDepositInitiateView.as_view(), name='deposit-nextpay-initiate'),\n"
             "    path('nextpay/select-method/', NextPayDepositSelectMethodView.as_view(), name='deposit-nextpay-select-method'),\n"
             "    path('nextpay/callback/', NextPayDepositCallbackView.as_view(), name='deposit-nextpay-callback'),\n")
    s = insert_after(s, anchor, block)
    write(p, s); changed.append(p)

    # ---------- 6. deposits/admin.py ----------
    p = "deposits/admin.py"
    s = read(p)
    s = s.replace("'batpay_enabled', 'updated_at'", "'batpay_enabled', 'nextpay_enabled', 'updated_at'")
    s = s.replace("'reepay_enabled', 'batpay_enabled')", "'reepay_enabled', 'batpay_enabled', 'nextpay_enabled')")
    anchor = ("        ('BatPay', {\n"
              "            'fields': (\n"
              "                'batpay_api_url',\n"
              "                'batpay_api_key',\n"
              "                'batpay_secret_key',\n"
              "                'batpay_return_url',\n"
              "            ),\n"
              "            'description': 'Konfigurasi BatPay (api.wayrooou.online). Auth HMAC-SHA256 via header X-API-Key, X-Timestamp, X-Signature (sama seperti Reepay). Secret key panjang (347 karakter).',\n"
              "        }),\n")
    fs = xform("        ('BatPay', {\n"
               "            'fields': (\n"
               "                'batpay_api_url',\n"
               "                'batpay_api_key',\n"
               "                'batpay_secret_key',\n"
               "                'batpay_return_url',\n"
               "            ),\n"
               "            'description': 'Konfigurasi BatPay (api.wayrooou.online). Auth HMAC-SHA256 via header X-API-Key, X-Timestamp, X-Signature (sama seperti Reepay). Secret key panjang (347 karakter).',\n"
               "        }),\n")
    s = insert_after(s, anchor, fs)
    write(p, s); changed.append(p)

    # ---------- 7. withdrawal/views.py ----------
    p = "withdrawal/views.py"
    s = read(p)
    s = s.replace(", ReepayWithdrawal, BatPayWithdrawal", ", ReepayWithdrawal, BatPayWithdrawal, NextPayWithdrawal")
    anchor = ("from deposits.integrations.batpay import (\n"
              "    post_json as batpay_post_json,\n"
              "    verify_callback_signature as batpay_verify_callback_signature,\n"
              "    extract_callback_field as batpay_extract_callback_field,\n"
              ")\n")
    block = ("from deposits.integrations.nextpay import (\n"
             "    post_json as nextpay_post_json,\n"
             "    verify_callback_signature as nextpay_verify_callback_signature,\n"
             "    extract_callback_field as nextpay_extract_callback_field,\n"
             ")\n")
    s = insert_after(s, anchor, block)
    marker = "\ndef _batpay_withdraw_raw_body(request) -> str:"
    i = s.index(marker)
    tail = xform(s[i:], extra=[("WBP", "WNP")])
    s = s[:i].rstrip("\n") + tail
    write(p, s); changed.append(p)

    # ---------- 8. withdrawal/urls.py ----------
    p = "withdrawal/urls.py"
    s = read(p)
    s = s.replace("    BatPayPayoutInitiateView,\n    BatPayPayoutCallbackView,\n",
                  "    BatPayPayoutInitiateView,\n    BatPayPayoutCallbackView,\n    NextPayPayoutInitiateView,\n    NextPayPayoutCallbackView,\n")
    anchor = ("    path('batpay/initiate/<int:pk>/', BatPayPayoutInitiateView.as_view(), name='withdrawal-batpay-initiate'),\n"
              "    path('batpay/callback/', BatPayPayoutCallbackView.as_view(), name='withdrawal-batpay-callback'),\n")
    block = ("    path('nextpay/initiate/<int:pk>/', NextPayPayoutInitiateView.as_view(), name='withdrawal-nextpay-initiate'),\n"
             "    path('nextpay/callback/', NextPayPayoutCallbackView.as_view(), name='withdrawal-nextpay-callback'),\n")
    s = insert_after(s, anchor, block)
    write(p, s); changed.append(p)

    # ---------- 9. withdrawal/admin.py ----------
    p = "withdrawal/admin.py"
    s = read(p)
    # 9a. model import + helper import
    s = s.replace("BankPayWithdrawal, ReepayWithdrawal, BatPayWithdrawal",
                  "BankPayWithdrawal, ReepayWithdrawal, BatPayWithdrawal, NextPayWithdrawal")
    s = s.replace("from deposits.integrations.batpay import post_json as batpay_post_json, get_json as batpay_get_json\n",
                  "from deposits.integrations.batpay import post_json as batpay_post_json, get_json as batpay_get_json\n"
                  "from deposits.integrations.nextpay import post_json as nextpay_post_json, get_json as nextpay_get_json\n")
    # 9b. actions tuple
    s = s.replace("'process_withdrawal_reepay', 'process_withdrawal_batpay'",
                  "'process_withdrawal_reepay', 'process_withdrawal_batpay', 'process_withdrawal_nextpay'")
    # 9c. get_urls route
    anchor = ("            path(\n"
              "                '<int:pk>/process-batpay/',\n"
              "                self.admin_site.admin_view(self.process_batpay_view),\n"
              "                name='withdrawal_withdrawal_process_batpay',\n"
              "            ),\n")
    block = ("            path(\n"
             "                '<int:pk>/process-nextpay/',\n"
             "                self.admin_site.admin_view(self.process_nextpay_view),\n"
             "                name='withdrawal_withdrawal_process_nextpay',\n"
             "            ),\n")
    s = insert_after(s, anchor, block)
    # 9d. process_batpay_view method -> clone process_nextpay_view before render_change_form
    start_marker = "    def process_batpay_view(self, request, pk: int):\n"
    end_marker = "\n    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):\n"
    body, j = extract_between(s, start_marker, end_marker)
    clone = xform(body, extra=[("WBP", "WNP")])
    s = s[:j] + clone + s[j:]
    # 9e. bank fetch block clone inside render_change_form
    anchor = ("            if not batpay_bank_codes:\n"
              "                batpay_bank_codes = [\n"
              "                    {\"bank_code\": c, \"bank_name\": n}\n"
              "                    for c, n in REEPAY_FALLBACK_BANK_CODES\n"
              "                ]\n")
    fetch = xform(anchor)
    s = insert_after(s, anchor, fetch)
    # 9f. context keys clone
    anchor = ("                'process_batpay_url': reverse('admin:withdrawal_withdrawal_process_batpay', args=(obj.id,)),\n"
              "            })\n")
    ctx = xform("                'batpay_payout_enabled': bool(gs and gs.batpay_payout_enabled),\n"
                "                'batpay_bank_codes': batpay_bank_codes,\n"
                "                'batpay_bank_codes_error': batpay_bank_codes_error,\n"
                "                'batpay_payout_initial': {\n"
                "                    'bank_code': getattr(getattr(obj.bank_account, 'bank', None), 'code', '') or '',\n"
                "                    'destination_account': obj.bank_account.account_number if obj.bank_account else '',\n"
                "                    'account_holder_name': obj.bank_account.account_name if obj.bank_account else '',\n"
                "                    'amount': str(obj.net_amount or obj.amount),\n"
                "                },\n"
                "                'process_batpay_url': reverse('admin:withdrawal_withdrawal_process_batpay', args=(obj.id,)),\n"
                "            })\n")
    s = insert_after(s, anchor, ctx)
    # 9g. bulk action clone
    start_marker = "    def process_withdrawal_batpay(self, request, queryset):\n"
    end_marker = "    process_withdrawal_batpay.short_description = 'Process via BatPay'\n"
    body, j = extract_between(s, start_marker, end_marker)
    clone = xform(body, extra=[("WBP", "WNP")])
    s = s[:j] + clone + s[j:]
    # 9h. WithdrawalSettings admin list_display + fieldset
    s = s.replace("'batpay_payout_enabled',\n        'updated_at',",
                  "'batpay_payout_enabled',\n        'nextpay_payout_enabled',\n        'updated_at',")
    anchor = ("        ('BatPay Payout', {\n"
              "            'fields': (\n"
              "                'batpay_payout_enabled',\n"
              "                'batpay_payout_api_url',\n"
              "                'batpay_payout_api_key',\n"
              "                'batpay_payout_secret_key',\n"
              "            )\n"
              "        }),\n"
              "    )\n")
    fs = xform("        ('BatPay Payout', {\n"
               "            'fields': (\n"
               "                'batpay_payout_enabled',\n"
               "                'batpay_payout_api_url',\n"
               "                'batpay_payout_api_key',\n"
               "                'batpay_payout_secret_key',\n"
               "            )\n"
               "        }),\n")
    s = insert_after(s, anchor, fs)
    write(p, s); changed.append(p)

    # ---------- 10. template change_form.html ----------
    p = "withdrawal/templates/admin/withdrawal/change_form.html"
    s = read(p)
    start_marker = "  <!-- BatPay Payout Section -->\n"
    end_marker = "{% endblock %}"
    body, j = extract_between(s, start_marker, end_marker, 0)
    body_x = xform(body).replace("id_bp_", "id_np_")
    s = s[:j] + body_x + s[j:]
    write(p, s); changed.append(p)

    print("DONE. Changed files:")
    for c in changed:
        print("  -", c)

if __name__ == "__main__":
    main()
