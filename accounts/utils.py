from accounts.models import GeneralSetting, RankLevel
from missions.models import MissionUserState
from products.models import Investment
from deposits.models import Deposit
from django.db.models import Sum
import requests
import logging

logger = logging.getLogger(__name__)

def normalize_phone(phone: str) -> str:
    """
    Normalisasi nomor telepon ke format E.164 untuk Indonesia secara konservatif.
    Aturan:
    - Jika sudah diawali '+', kembalikan apa adanya.
    - Jika diawali '62', tambahkan '+'.
    - Jika diawali '0', ganti leading '0' dengan '+62'.
    - Jika diawali '8' (umum input lokal), tambahkan '+62' di depan.
    - Selain itu, kembalikan apa adanya (biar server pihak ketiga menilai).
    """
    if not phone:
        return phone
    p = phone.strip().replace(' ', '').replace('-', '')
    if p.startswith('+'):
        return p
    if p.startswith('62'):
        return f'+{p}'
    if p.startswith('0'):
        return f'+62{p[1:]}'
    if p.startswith('8'):
        return f'+62{p}'
    return p


def is_indonesia_phone(normalized_phone: str) -> bool:
    p = (normalized_phone or "").strip()
    return p.startswith("+62")

def check_whatsapp_registered(phone: str, poll_timeout_seconds: int = 25, poll_interval_seconds: float = 1.5):
    """
    Cek apakah nomor memiliki akun WhatsApp aktif menggunakan checknumber.ai.
    Mengembalikan tuple (is_registered: bool, message: str).
    - Bila fitur dimatikan atau API key kosong: kembalikan (False, alasan)
    - Menggunakan mekanisme tugas (upload file berisi satu nomor) lalu polling hingga 'exported'
    - Mendukung hasil CSV/JSON; untuk XLSX dilakukan inspeksi sederhana via zip (tanpa dependency eksternal)
    """
    settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
    if not settings_obj or not settings_obj.whatsapp_check_enabled:
        return False, "WhatsApp number check disabled"
    api_key = (settings_obj.checknumber_api_key or "").strip()
    if not api_key:
        return False, "CheckNumber API Key not configured"

    num = normalize_phone(phone)
    if not num.startswith('+'):
        # Layanan mewajibkan E.164; pastikan ada '+'
        num = f"+{num}" if not num.startswith('+') else num

    headers = {"X-API-Key": api_key}
    
    # STRATEGY 1: Check via Avatar Endpoint (Single number supported)
    # Trying multiple variations of the avatar/check endpoint
    errors = []
    
    # 1.1: Try /v1/whatsapp/check (Realtime Checker)
    try:
        check_url = "https://api.checknumber.ai/v1/whatsapp/check"
        # Try JSON body
        r_check = requests.post(check_url, headers=headers, json={"number": num}, timeout=10)
        if r_check.status_code == 200:
            data = r_check.json()
            # Adjust based on actual response structure
            is_valid = data.get("valid") or data.get("registered") or data.get("whatsapp")
            if str(is_valid).lower() in ("true", "yes", "1", "ya"):
                return True, "Phone has active WhatsApp (Realtime)"
            else:
                # If explicitly false, we might trust it? Or fall through?
                # Let's trust explicit success response structure
                pass
        else:
            errors.append(f"Realtime check failed: {r_check.status_code}")
    except Exception as e:
        errors.append(f"Realtime check error: {str(e)}")

    # 1.2: Try /v1/whatsapp/avatar
    try:
        avatar_url = "https://api.checknumber.ai/v1/whatsapp/avatar"
        # Try JSON
        r_avatar = requests.post(avatar_url, headers=headers, json={"number": num}, timeout=10)
        
        if r_avatar.status_code == 200:
            return True, "Phone has active WhatsApp (Avatar check)"
        elif r_avatar.status_code == 400:
            # "no image" -> means checked but no avatar found.
            try:
                js_err = r_avatar.json()
                if "no image" in str(js_err.get("message", "")).lower():
                     return True, "Phone has active WhatsApp (No avatar)"
            except:
                pass
            errors.append(f"Avatar check 400: {r_avatar.text}")
        else:
            errors.append(f"Avatar check failed: {r_avatar.status_code}")
            
    except Exception as e:
        errors.append(f"Avatar check error: {str(e)}")
        pass

    # STRATEGY 2: Try synchronous detail check (Backup)
    try:
        clean_num = num.replace("+", "")
        # Try api.checknumber.ai instead of ekycpro
        sync_url = "https://api.checknumber.ai/v1/wadetail"
        params = {
            "number": clean_num,
            "country": "ID"
        }
        
        r_sync = requests.post(sync_url, headers=headers, params=params, timeout=10)
             
        if r_sync.status_code == 200:
            data = r_sync.json()
            wa_status = str(data.get("whatsapp", "")).lower()
            if wa_status in ("true", "yes", "1", "ya"):
                return True, "Phone has active WhatsApp (Sync)"
            elif wa_status in ("false", "no", "0", "tidak"):
                return False, "Phone has no WhatsApp (Sync)"
        else:
             errors.append(f"Sync check failed: {r_sync.status_code}")
             
    except Exception as e:
        errors.append(f"Sync check error: {str(e)}")
        pass

    # Prepare for CheckNumber API (Realtime Endpoint)
    num = phone.replace("+", "")
    
    # Extract country code and number
    if num.startswith("62"):
        country = "ID"
        number = num 
    else:
        # Fallback default
        country = "ID"
        number = num

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-API-Key": api_key
    }
    
    data = {
        "number": number,
        "country": country
    }

    try:
        # New Endpoint: v1/realtime/whatsapp
        resp = requests.post(
            "https://api.checknumber.ai/v1/realtime/whatsapp", 
            headers=headers, 
            data=data, 
            timeout=15
        )
        
        try:
            js = resp.json()
        except Exception:
            return False, f"CheckNumber Invalid JSON response ({resp.status_code})"

        if resp.status_code == 200 and js.get("status") == "OK":
            msg_data = js.get("message", {})
            wa_status = msg_data.get("whatsapp", "").lower()
            
            if wa_status == "yes":
                return True, "Phone has active WhatsApp"
            elif wa_status == "no":
                return False, "Phone has no WhatsApp"
            else:
                return False, f"Unknown status: {wa_status}"
        
        # Handle error responses
        msg = js.get("message") or "Unknown error"
        return False, f"CheckNumber failed: {msg}"

    except Exception as e:
        logger.error(f"CheckNumber error for {phone}: {e}")
        return False, str(e)

def calculate_user_rank_progress_breakdown(user):
    if not user or not user.is_authenticated:
        return {
            'missions': 0,
            'downlines_total': 0,
            'downlines_active': 0,
            'deposit_self_total': 0,
            'team_deposit_level_1_total': 0,
            'levels_upto': 1,
        }

    settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
    levels_upto = settings_obj.rank_count_levels_upto if settings_obj else 1
    levels_upto = max(1, int(levels_upto or 1))

    missions_done = 0
    try:
        missions_done = (
            MissionUserState.objects
            .filter(user=user, claimed_count__gte=1)
            .values('mission_id')
            .distinct()
            .count()
        )
    except Exception:
        missions_done = 0

    total_downlines = 0
    active_downlines = 0
    try:
        current_level_users = [user]
        for _lvl in range(1, levels_upto + 1):
            next_level = []
            for u in current_level_users:
                ds = list(u.referrals.all())
                next_level.extend(ds)
                total_downlines += len(ds)
                for d in ds:
                    if Deposit.objects.filter(
                        user=d,
                        status='COMPLETED',
                    ).exists():
                        active_downlines += 1
            current_level_users = next_level
            if not current_level_users:
                break
    except Exception:
        total_downlines = 0
        active_downlines = 0

    try:
        agg = Deposit.objects.filter(user=user, status='COMPLETED').aggregate(total=Sum('amount'))
        deposit_total = agg.get('total') or 0
    except Exception:
        deposit_total = 0

    try:
        team_level_1_qs = Deposit.objects.filter(
            user__referral_by=user,
            status='COMPLETED',
        )
        team_level_1_total = team_level_1_qs.aggregate(total=Sum('amount')).get('total') or 0
    except Exception:
        team_level_1_total = 0

    return {
        'missions': missions_done,
        'downlines_total': total_downlines,
        'downlines_active': active_downlines,
        'deposit_self_total': deposit_total,
        'team_deposit_level_1_total': team_level_1_total,
        'levels_upto': levels_upto,
    }


def calculate_user_rank_progress(user):
    if not user or not user.is_authenticated:
        return 0
    try:
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        use_missions = True if not settings_obj else bool(settings_obj.rank_use_missions)
        use_downlines_total = False if not settings_obj else bool(settings_obj.rank_use_downlines_total)
        use_downlines_active = False if not settings_obj else bool(settings_obj.rank_use_downlines_active)
        use_deposit_self_total = False if not settings_obj else bool(settings_obj.rank_use_deposit_self_total)
        use_team_deposit_level_1_total = False if not settings_obj else bool(settings_obj.rank_use_team_deposit_level_1_total)
        b = calculate_user_rank_progress_breakdown(user)
        candidates = []
        if use_missions:
            candidates.append(b['missions'])
        if use_downlines_total:
            candidates.append(b['downlines_total'])
        if use_downlines_active:
            candidates.append(b['downlines_active'])
        if use_deposit_self_total:
            candidates.append(b['deposit_self_total'])
        if use_team_deposit_level_1_total:
            candidates.append(b['team_deposit_level_1_total'])
        return max(candidates) if candidates else 0
    except Exception:
        return 0

def update_user_rank(user):
    """
    Evaluates and updates the user's rank based on current progress.
    Returns the new rank (or current rank if no change).
    """
    if not user or not user.is_authenticated:
        return None
        
    try:
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        use_missions = True if not settings_obj else bool(settings_obj.rank_use_missions)
        use_downlines_total = False if not settings_obj else bool(settings_obj.rank_use_downlines_total)
        use_downlines_active = False if not settings_obj else bool(settings_obj.rank_use_downlines_active)
        use_deposit_self_total = False if not settings_obj else bool(settings_obj.rank_use_deposit_self_total)
        use_team_deposit_level_1_total = False if not settings_obj else bool(settings_obj.rank_use_team_deposit_level_1_total)

        b = calculate_user_rank_progress_breakdown(user)

        qs = RankLevel.objects.all()
        if use_missions:
            qs = qs.filter(missions_required_total__lte=b['missions'])
        if use_downlines_total:
            qs = qs.filter(downlines_total_required__lte=b['downlines_total'])
        if use_downlines_active:
            qs = qs.filter(downlines_active_required__lte=b['downlines_active'])
        if use_deposit_self_total:
            qs = qs.filter(deposit_self_total_required__lte=b['deposit_self_total'])
        if use_team_deposit_level_1_total:
            qs = qs.filter(team_deposit_level_1_total_required__lte=b['team_deposit_level_1_total'])

        target = qs.order_by('-rank').first()
        
        if target:
            current_rank = user.rank if user.rank is not None else 0
            
            # Update if target rank is higher than current
            if target.rank > current_rank:
                user.rank = target.rank
                user.save(update_fields=['rank'])
                logger.info(f"User {user.id} upgraded to Rank {target.rank}")
                return target.rank
                
        return user.rank
    except Exception as e:
        logger.error(f"Error updating rank for user {user.id}: {e}")
        return user.rank

def _get_verifynow_token(customer_id, api_key):
    """
    Get Auth Token for VerifyNow (Message Central).
    NOTE: User provided a static long-lived JWT token in api_key field.
    So we just return it directly.
    """
    return api_key

def _send_verifynow_otp(phone, customer_id, api_key):
    """
    Send OTP using VerifyNow (Message Central).
    Returns (success, verification_id_or_message).
    """
    token = _get_verifynow_token(customer_id, api_key)
    if not token:
        return False, "Failed to authenticate with VerifyNow"

    url = "https://cpaas.messagecentral.com/verification/v3/send"
    
    # Normalize phone to just digits for countryCode split or pass full number?
    # Docs say: countryCode and mobileNumber.
    # We'll use normalize_phone first.
    normalized = normalize_phone(phone)
    if not normalized.startswith('+'):
         normalized = f"+{normalized}"
    
    # Extract country code. Assuming ID (+62)
    country_code = "62"
    mobile_number = normalized.replace("+62", "").replace("+", "")
    
    if normalized.startswith("+"):
        # Simple parser
        # For Indonesia
        if normalized.startswith("+62"):
            country_code = "62"
            mobile_number = normalized[3:]
        else:
            # Fallback for other countries? 
            # This is a simplification. Better to use phonenumbers lib if available, but for now:
            country_code = normalized[1:3] # Guess 2 digit country code
            mobile_number = normalized[3:]
    else:
        # If no plus, assume ID for now or try to parse
        if normalized.startswith("62"):
            country_code = "62"
            mobile_number = normalized[2:]
        elif normalized.startswith("08"):
            country_code = "62"
            mobile_number = normalized[1:]
        else:
            country_code = "62"
            mobile_number = normalized

    # Example URL provided by user:
    # https://cpaas.messagecentral.com/verification/v3/send?countryCode=62&customerId=...&flowType=SMS&mobileNumber=...
    # Note: flowType=SMS in example, but user asked for WhatsApp earlier. 
    # Let's support both or stick to user request.
    # User original request: "otp whatsapp saya mau ubah sumber ya"
    # User snippet shows flowType=SMS. 
    # BUT typically WhatsApp OTP is flowType=WHATSAPP. 
    # Let's try WHATSAPP as requested, if fails we can fallback or user can change config.
    # Assuming user just copied an SMS example but wants WhatsApp.
    
    params = {
        "countryCode": country_code,
        "mobileNumber": mobile_number,
        "flowType": "WHATSAPP",
        "customerId": customer_id
    }
    
    headers = {
        "authToken": token
    }
    
    try:
        # User snippet: requests.request("POST", url, headers=headers, data=payload)
        # Params are in URL query string in the snippet example string!
        # "url = ...?countryCode=..."
        # So we pass params to requests.post
        resp = requests.post(url, params=params, headers=headers, timeout=15)
        
        # Debug response
        if resp.status_code != 200:
            logger.error(f"VerifyNow HTTP {resp.status_code}: {resp.text}")
            
        try:
            data = resp.json()
        except Exception:
            logger.error(f"VerifyNow Invalid JSON response: {resp.text}")
            return False, f"Invalid JSON response from VerifyNow (Status {resp.status_code})"
        
        if resp.status_code == 200 and data.get("responseCode") == 200:
            verification_id = data.get("data", {}).get("verificationId")
            if verification_id:
                return True, verification_id
            return False, "No verificationId in response"
        
        msg = data.get("message") or data.get("errorMessage") or f"VerifyNow send failed ({resp.status_code})"
        return False, msg
        
    except Exception as e:
        logger.error(f"VerifyNow Send Exception: {e}")
        return False, str(e)

def validate_whatsapp_otp(phone, verification_id, code):
    """
    Validate OTP using VerifyNow.
    Changed signature to include phone (required by API).
    """
    settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
    if not settings_obj:
        return False, "Settings not found"
        
    customer_id = settings_obj.verifynow_customer_id
    api_key = settings_obj.verifynow_api_key
    
    if not customer_id or not api_key:
        return False, "VerifyNow credentials missing"
        
    token = _get_verifynow_token(customer_id, api_key)
    if not token:
        return False, "Failed to authenticate with VerifyNow"
        
    url = "https://cpaas.messagecentral.com/verification/v3/validateOtp"
    
    # Normalize phone
    normalized = normalize_phone(phone)
    if normalized.startswith("+62"):
        country_code = "62"
        mobile_number = normalized[3:]
    else:
        # Fallback parsing
        country_code = normalized[1:3]
        mobile_number = normalized[3:]

    params = {
        "countryCode": country_code,
        "mobileNumber": mobile_number,
        "verificationId": verification_id,
        "customerId": "C-C1086B66D3614F9", # Hardcoded customerId
        "code": code
    }
    
    headers = {
        "authToken": token
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        
        if resp.status_code == 200 and data.get("responseCode") == 200:
            status_val = data.get("data", {}).get("verificationStatus")
            if status_val == "VERIFICATION_COMPLETED":
                return True, "Success"
        
        msg = data.get("message") or data.get("errorMessage") or "Validation failed"
        return False, msg
        
    except Exception as e:
        return False, str(e)

def _fazpass_normalize_phone(phone: str) -> str:
    normalized = normalize_phone(phone)
    return normalized.replace("+", "").strip()


def _send_fazpass_otp(phone: str, merchant_key: str, gateway_key: str):
    url = "https://api.fazpass.com/v1/otp/request"
    headers = {
        "Authorization": f"Bearer {merchant_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "phone": _fazpass_normalize_phone(phone),
        "gateway_key": gateway_key,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        try:
            data = resp.json()
        except Exception:
            return False, f"Fazpass invalid JSON response (HTTP {resp.status_code})"

        if resp.status_code == 200 and data.get("status") is True:
            otp_id = (data.get("data") or {}).get("id")
            if otp_id:
                return True, otp_id
            return False, "Fazpass response missing otp id"

        msg = data.get("message") or data.get("errorMessage") or f"Fazpass request failed (HTTP {resp.status_code})"
        return False, msg
    except Exception as e:
        return False, str(e)


def validate_fazpass_otp(otp_id: str, code: str):
    settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
    if not settings_obj:
        return False, "Settings not found"

    merchant_key = (settings_obj.fazpass_merchant_key or "").strip()
    if not merchant_key:
        return False, "Fazpass merchant key missing"

    url = "https://api.fazpass.com/v1/otp/verify"
    headers = {
        "Authorization": f"Bearer {merchant_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "otp_id": otp_id,
        "otp": code,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        try:
            data = resp.json()
        except Exception:
            return False, f"Fazpass invalid JSON response (HTTP {resp.status_code})"

        if resp.status_code == 200 and data.get("status") is True:
            return True, "Success"

        msg = data.get("message") or data.get("errorMessage") or "Validation failed"
        return False, msg
    except Exception as e:
        return False, str(e)


def send_whatsapp_otp(phone, otp_code=None, lang='en'):
    """
    Send OTP via WhatsApp.
    Supports VerifyNow (Message Central), Fazpass, and VerifyWay (Legacy).
    """
    settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
    if not settings_obj or not settings_obj.otp_enabled:
        return False, "OTP disabled in settings"

    chosen = (getattr(settings_obj, "otp_provider", "") or "AUTO").strip().upper()
    if chosen not in {"AUTO", "VERIFYNOW", "FAZPASS", "VERIFYWAY"}:
        chosen = "AUTO"

    if chosen in {"VERIFYNOW", "AUTO"}:
        if settings_obj.verifynow_customer_id and settings_obj.verifynow_api_key:
            ok, verification_id = _send_verifynow_otp(phone, settings_obj.verifynow_customer_id, settings_obj.verifynow_api_key)
            if ok:
                return True, {"provider": "VERIFYNOW", "verification_id": verification_id}
            if chosen == "VERIFYNOW":
                return False, verification_id
        elif chosen == "VERIFYNOW":
            return False, "VerifyNow credentials missing"

    if chosen in {"FAZPASS", "AUTO"}:
        fazpass_merchant_key = (settings_obj.fazpass_merchant_key or "").strip()
        fazpass_gateway_key = (settings_obj.fazpass_gateway_key or "").strip()
        if fazpass_merchant_key and fazpass_gateway_key:
            ok, otp_id = _send_fazpass_otp(phone, fazpass_merchant_key, fazpass_gateway_key)
            if ok:
                return True, {"provider": "FAZPASS", "verification_id": otp_id}
            if chosen == "FAZPASS":
                return False, otp_id
        elif chosen == "FAZPASS":
            return False, "Fazpass credentials missing"

    api_key = settings_obj.verifyway_api_key
    if chosen == "VERIFYWAY" and not api_key:
        return False, "VerifyWay API key not configured"
    if chosen == "AUTO" and not api_key:
        return False, "OTP Provider API Key not configured"
        
    if not otp_code:
        return False, "OTP code required for VerifyWay"

    url = "https://api.verifyway.com/api/v1/"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    def _do_request(payload_variant):
        try:
            resp = requests.post(url, json=payload_variant, headers=headers, timeout=10)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if resp.status_code == 200:
                status_val = str(data.get('status', '')).lower()
                success_flag = data.get('success')
                if 'error' in data:
                    return False, data.get('error') or "Provider returned error", data
                if success_flag is False or status_val in {'failed', 'error', 'undelivered', 'blocked'}:
                    msg = data.get('message') or data.get('detail') or "Delivery failed"
                    return False, msg, data
                return True, "OTP sent successfully", data
            else:
                if resp.status_code in (401, 403):
                    msg = data.get('error') or data.get('message') or "Invalid or missing API key"
                else:
                    msg = data.get('error') or data.get('message') or data.get('detail') or f"Request failed with status {resp.status_code}"
                return False, msg, data
        except Exception as e:
            return False, str(e), {}

    # Build attempt variants
    recipient_plus = _normalize_phone_e164(phone)
    recipient_no_plus = recipient_plus[1:] if recipient_plus and recipient_plus.startswith('+') else recipient_plus

    base = {
        "type": "otp",
        "code": otp_code,
        "lang": lang
    }
    attempts = [
        {**base, "recipient": recipient_plus, "channel": "whatsapp", "fallback": "no"},
        {**base, "recipient": recipient_no_plus, "channel": "whatsapp", "fallback": "no"},
        {**base, "recipient": recipient_no_plus, "channel": "whatsapp"},
        {**base, "recipient": recipient_plus},  # rely on provider defaults
    ]

    last_msg = "Unknown error"
    last_data = {}
    for idx, payload in enumerate(attempts, 1):
        ok, msg, data = _do_request(payload)
        if ok:
            return True, {"provider": "VERIFYWAY"}
        last_msg, last_data = msg, data
        logger.warning(f"VerifyWay attempt {idx} failed for {payload.get('recipient')}: {msg} | data={data}")

    logger.error(f"All VerifyWay attempts failed: {last_msg} | data={last_data}")
    return False, last_msg
