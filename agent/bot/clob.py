# agent/bot/clob.py
"""
CLOB client builder - py-clob-client wrapper
"""
import os
from typing import Optional
from .config import (
    CHAIN_ID,
    CLOB_HOST,
    PRIVATE_KEY,
    PK,
    SIGNATURE_TYPE,
    FUNDER_ADDRESS,
    API_KEY,
    API_SECRET,
    API_PASSPHRASE
)

_CLOB_CLIENT = None

def build_clob_client():
    """
    CLOB client singleton
    
    Returns:
        ClobClient instance
    """
    global _CLOB_CLIENT
    
    if _CLOB_CLIENT is not None:
        return _CLOB_CLIENT
    
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
        
        # Private key tercih sırası: PRIVATE_KEY > PK
        private_key = PRIVATE_KEY or PK
        
        if not private_key:
            raise ValueError("PRIVATE_KEY or PK must be set")
        
        # API credentials
        api_creds = None
        if API_KEY and API_SECRET:
            api_creds = ApiCreds(
                api_key=API_KEY,
                api_secret=API_SECRET,
                api_passphrase=API_PASSPHRASE or ""
            )
        
        # Client oluştur
        client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=private_key,
            signature_type=SIGNATURE_TYPE,
            funder=FUNDER_ADDRESS or None,
            creds=api_creds
        )
        
        _CLOB_CLIENT = client
        return client
        
    except ImportError as e:
        raise ImportError(f"py-clob-client not installed: {e}")
    except Exception as e:
        raise Exception(f"Failed to build CLOB client: {e}")


def get_clob_address() -> Optional[str]:
    """CLOB client'ın wallet adresini getir"""
    try:
        client = build_clob_client()
        return getattr(client, "address", None) or getattr(client, "wallet_address", None)
    except Exception:
        return None
