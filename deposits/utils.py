import logging
import base64
from Crypto.PublicKey import RSA
from Crypto.Util.number import bytes_to_long, long_to_bytes

logger = logging.getLogger(__name__)

def verify_jayapay_signature(data_dict, public_key_pem, signature_field: str = "platSign"):
    """
    Verify Jayapay callback signature.
    
    Logic based on PHP example:
    1. Extract 'platSign'.
    2. Decrypt 'platSign' using Platform Public Key (RSA Public Decrypt).
    3. Construct params string: ksort params, concatenate values.
    4. Compare decrypted sign with constructed string.
    """
    try:
        plat_sign = data_dict.get(signature_field)
        if not plat_sign:
            logger.warning("verify_jayapay_signature: No signature found (%s)", signature_field)
            return False
            
        # Construct expected string
        # Filter out platSign and empty keys? (PHP example: unset($res['platSign']))
        # PHP example uses json_decode which gives dict.
        params = data_dict.copy()
        params.pop(signature_field, None)
        
        sorted_keys = sorted(params.keys())
        
        # Helper to format values for signature string
        def _stringify(v):
            if isinstance(v, float):
                return "{:.2f}".format(v)
            if v is None:
                return ""
            return str(v)

        params_str = "".join(_stringify(params[k]) for k in sorted_keys)
        
        # Decrypt platSign
        # Format PEM if needed
        if "-----BEGIN PUBLIC KEY-----" not in public_key_pem:
            public_key_pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_pem.strip()}\n-----END PUBLIC KEY-----"
            
        key = RSA.import_key(public_key_pem)
        
        # RSA Public Decrypt (m = c^e mod n)
        # PHP code splits data into 128 byte chunks
        encrypted_data = base64.b64decode(plat_sign)
        
        key_size_bytes = key.size_in_bytes()
        chunk_size = key_size_bytes
        
        decrypted_parts = []
        
        for i in range(0, len(encrypted_data), chunk_size):
            chunk = encrypted_data[i:i+chunk_size]
            if len(chunk) != key_size_bytes:
                # If chunk is smaller (last one?), standard RSA math handles it if converted to int
                pass
                
            c = bytes_to_long(chunk)
            m = pow(c, key.e, key.n)
            
            # Convert back to bytes
            # Note: PHP openssl_public_decrypt handles padding removal (PKCS#1 v1.5 padding)
            # When using raw RSA math (pow), we get the PADDED message.
            # We need to remove padding manually.
            # PKCS#1 v1.5 Block type 1 (for signatures): 00 01 FF ... FF 00 DATA
            
            decrypted_chunk_padded = long_to_bytes(m, key_size_bytes)
            
            # Remove padding
            # Look for 00 separator
            try:
                # First byte should be 0x00 or 0x01? 
                # OpenSSL public decrypt usually expects the data was private encrypted.
                # If private encrypted (signed), it's block type 1.
                # Structure: 00 01 PS 00 D
                
                # Check for 00 separator after the first few bytes
                sep_idx = -1
                for idx, byte in enumerate(decrypted_chunk_padded):
                    if idx > 2 and byte == 0:
                        sep_idx = idx
                        break
                
                if sep_idx != -1:
                    decrypted_chunk = decrypted_chunk_padded[sep_idx+1:]
                    decrypted_parts.append(decrypted_chunk)
                else:
                    logger.warning(f"verify_jayapay_signature: Could not find padding separator in chunk {i}")
                    # Fallback: maybe raw?
                    decrypted_parts.append(decrypted_chunk_padded)
                    
            except Exception as e:
                logger.error(f"verify_jayapay_signature: Error processing chunk: {e}")
                return False

        decrypted_str = b"".join(decrypted_parts).decode('utf-8')
        
        if decrypted_str == params_str:
            return True
        else:
            logger.warning(f"verify_jayapay_signature: Mismatch. Expected: {params_str[:50]}... Got: {decrypted_str[:50]}...")
            return False
            
    except Exception as e:
        logger.error(f"verify_jayapay_signature: Exception: {e}")
        return False
