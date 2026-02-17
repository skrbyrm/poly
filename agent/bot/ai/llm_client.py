import json
from typing import Dict, Any, Optional, List
from ..config import (
    LLM_API_KEY,
    OPENAI_BASE_URL,
    LLM_MODEL,
    LLM_TIMEOUT_S,
    LLM_MAX_OUTPUT_TOKENS,
    ANTHROPIC_API_KEY,
)
from ..monitoring.logger import get_logger


logger = get_logger("llm")


class LLMClient:
    def __init__(self):
        self.openai_api_key = LLM_API_KEY
        self.anthropic_api_key = ANTHROPIC_API_KEY
        self.base_url = OPENAI_BASE_URL
        self.timeout = LLM_TIMEOUT_S
        self.max_tokens = LLM_MAX_OUTPUT_TOKENS

    def call_openai(self, messages: List[Dict[str, str]], model: str = None) -> Optional[Dict[str, Any]]:
        if not self.openai_api_key:
            logger.warning("OpenAI key missing")
            return None

        _model = model or LLM_MODEL

        try:
            import openai

            logger.info("Calling OpenAI", provider="openai", model=_model)

            client = openai.OpenAI(
                api_key=self.openai_api_key,
                base_url=self.base_url,
                timeout=self.timeout
            )

            new_api_models = ("gpt-5", "o1", "o3", "o4")
            use_new_param = any(_model.startswith(p) for p in new_api_models)

            kwargs = dict(
                model=_model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            if use_new_param:
                kwargs["max_completion_tokens"] = self.max_tokens
            else:
                kwargs["max_tokens"] = self.max_tokens

            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            parsed = json.loads(content)

            logger.info("OpenAI response parsed", provider="openai", model=_model, ok=bool(parsed))
            return parsed

        except json.JSONDecodeError as e:
            logger.error("OpenAI JSON parse error", provider="openai", model=_model, error=str(e))
            return None
        except Exception as e:
            logger.error("OpenAI call error", provider="openai", model=_model, error=str(e))
            return None

    def call_anthropic(self, messages: List[Dict[str, str]], model: str = None) -> Optional[Dict[str, Any]]:
        if not self.anthropic_api_key:
            logger.warning("Anthropic key missing")
            return None

        _model = model or "claude-3-5-sonnet-latest"

        try:
            import anthropic

            logger.info("Calling Anthropic", provider="anthropic", model=_model)

            client = anthropic.Anthropic(api_key=self.anthropic_api_key)

            system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
            system_prompt = "\n".join(system_parts).strip()
            non_system = [m for m in messages if m.get("role") != "system"]

            resp = client.messages.create(
                model=_model,
                max_tokens=self.max_tokens,
                temperature=0.3,
                system=system_prompt if system_prompt else None,
                messages=non_system,
            )

            text_chunks = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
            raw_text = "".join(text_chunks).strip()
            parsed = json.loads(raw_text)

            logger.info("Anthropic response parsed", provider="anthropic", model=_model, ok=bool(parsed))
            return parsed

        except json.JSONDecodeError as e:
            logger.error("Anthropic JSON parse error", provider="anthropic", model=_model, error=str(e))
            return None
        except Exception as e:
            logger.error("Anthropic call error", provider="anthropic", model=_model, error=str(e))
            return None

    def call(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        provider: str = "openai"
    ) -> Optional[Dict[str, Any]]:
        provider = (provider or "openai").lower()
        logger.debug("LLM dispatch", provider=provider, model=model or LLM_MODEL)

        if provider == "anthropic":
            return self.call_anthropic(messages, model=model)
        return self.call_openai(messages, model=model)


_llm_client = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
