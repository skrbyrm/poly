# agent/bot/ai/llm_client.py
import os
import json
from typing import Dict, Any, Optional, List
from ..config import LLM_API_KEY, OPENAI_BASE_URL, LLM_MODEL, LLM_TIMEOUT_S, LLM_MAX_OUTPUT_TOKENS

class LLMClient:
    
    def __init__(self):
        self.api_key = LLM_API_KEY
        self.base_url = OPENAI_BASE_URL
        self.timeout = LLM_TIMEOUT_S
        self.max_tokens = LLM_MAX_OUTPUT_TOKENS

    def call_openai(self, messages: List[Dict[str, str]], model: str = None) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            print("[LLM] No API key configured")
            return None

        _model = model or LLM_MODEL

        try:
            import openai

            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout
            )

            # gpt-5.x ve o-serisi modeller max_completion_tokens kullanır
            new_api_models = ("gpt-5", "o1", "o3", "o4")
            use_new_param = any(_model.startswith(p) for p in new_api_models)

            kwargs = dict(
                model=_model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            if use_new_param:
                kwargs["max_completion_tokens"] = self.max_tokens
            else:
                kwargs["max_tokens"] = self.max_tokens

            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            return json.loads(content)

        except json.JSONDecodeError as e:
            print(f"[LLM] JSON parse error: {e}")
            return None
        except Exception as e:
            print(f"[LLM] OpenAI error: {e}")
            return None

    def call(self, messages: List[Dict[str, str]], model: str = None, provider: str = "openai") -> Optional[Dict[str, Any]]:
        return self.call_openai(messages, model or LLM_MODEL)


_llm_client = None

def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
