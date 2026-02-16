# agent/bot/ai/llm_client.py
"""
Multi-model LLM client - OpenAI ve Anthropic desteği
"""
import os
import json
from typing import Dict, Any, Optional, List
from ..config import (
    LLM_API_KEY,
    OPENAI_BASE_URL,
    LLM_MODEL,
    LLM_TIMEOUT_S,
    LLM_MAX_OUTPUT_TOKENS,
    ANTHROPIC_API_KEY
)

class LLMClient:
    """LLM API client wrapper"""
    
    def __init__(self):
        self.openai_api_key = LLM_API_KEY
        self.openai_base_url = OPENAI_BASE_URL
        self.anthropic_api_key = ANTHROPIC_API_KEY
        self.timeout = LLM_TIMEOUT_S
        self.max_tokens = LLM_MAX_OUTPUT_TOKENS
    
    def call_openai(self, messages: List[Dict[str, str]], model: str = None) -> Optional[Dict[str, Any]]:
        """
        OpenAI API çağrısı
        
        Args:
            messages: Mesaj listesi [{"role": "user", "content": "..."}]
            model: Model ismi (None ise config'den)
        
        Returns:
            Parsed decision dict veya None
        """
        if not self.openai_api_key:
            return None
        
        try:
            import openai
            
            client = openai.OpenAI(
                api_key=self.openai_api_key,
                base_url=self.openai_base_url,
                timeout=self.timeout
            )
            
            response = client.chat.completions.create(
                model=model or LLM_MODEL,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            return json.loads(content)
            
        except Exception as e:
            print(f"[LLM] OpenAI error: {e}")
            return None
    
    def call_anthropic(self, messages: List[Dict[str, str]], model: str = "claude-sonnet-4-20250514") -> Optional[Dict[str, Any]]:
        """
        Anthropic Claude API çağrısı
        
        Args:
            messages: Mesaj listesi
            model: Claude model
        
        Returns:
            Parsed decision dict veya None
        """
        if not self.anthropic_api_key:
            return None
        
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            
            # System message'ı ayır
            system_msg = ""
            user_messages = []
            
            for msg in messages:
                if msg["role"] == "system":
                    system_msg = msg["content"]
                else:
                    user_messages.append(msg)
            
            response = client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                system=system_msg,
                messages=user_messages
            )
            
            content = response.content[0].text
            return json.loads(content)
            
        except Exception as e:
            print(f"[LLM] Anthropic error: {e}")
            return None
    
    def call(self, messages: List[Dict[str, str]], model: str = None, provider: str = "openai") -> Optional[Dict[str, Any]]:
        """
        Generic LLM call
        
        Args:
            messages: Mesaj listesi
            model: Model ismi
            provider: "openai" veya "anthropic"
        
        Returns:
            Parsed response
        """
        if provider == "anthropic":
            return self.call_anthropic(messages, model or "claude-sonnet-4-20250514")
        else:
            return self.call_openai(messages, model or LLM_MODEL)


# Global instance
_llm_client = None

def get_llm_client() -> LLMClient:
    """LLMClient singleton"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
