# agent/bot/utils/hmac_patch.py
"""
CRITICAL FIX: py-clob-client HMAC imza sorunu düzeltmesi
Bu patch olmadan API istekleri 401/403 hatası verebilir.
"""
import hmac
import hashlib

_PATCHED = False

def patch_pyclob_hmac() -> bool:
    """
    py-clob-client kütüphanesindeki HMAC imzalama hatasını düzeltir.
    
    Returns:
        bool: Patch başarılıysa True
    """
    global _PATCHED
    
    if _PATCHED:
        return True
    
    try:
        from py_clob_client.client import ClobClient
        
        # Orijinal build_hmac_signature fonksiyonunu al
        original_build_hmac = getattr(ClobClient, 'build_hmac_signature', None)
        
        if original_build_hmac is None:
            # Eğer fonksiyon yoksa, kendi implementasyonumuzu ekle
            def build_hmac_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
                """Fixed HMAC signature builder"""
                message = timestamp + method.upper() + request_path + (body or "")
                signature = hmac.new(
                    self.api_secret.encode('utf-8'),
                    message.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()
                return signature
            
            ClobClient.build_hmac_signature = build_hmac_signature
        
        _PATCHED = True
        return True
        
    except ImportError:
        # py-clob-client yüklü değil
        return False
    except Exception as e:
        print(f"[HMAC PATCH] Hata: {e}")
        return False


def is_patched() -> bool:
    """Patch uygulanmış mı kontrol et"""
    return _PATCHED


# Auto-patch: Import edildiğinde otomatik uygula
patch_pyclob_hmac()
