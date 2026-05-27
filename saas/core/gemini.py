"""콘텐츠 생성 엔진. app.py:1295-1308의 폴백 루프를 이식."""
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from core import config

_client = None


def _get_client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def generate(system_instruction: str, prompt: str, paid: bool = False) -> tuple[str, str]:
    """(생성된 텍스트, 사용된 모델명) 반환.

    유료 티어는 품질 우선(flash), 무료 티어는 비용 우선(flash-lite)으로 모델 순서를 바꾼다.
    app.py와 동일하게 ServerError는 재시도, ClientError는 즉시 중단.
    """
    client = _get_client()
    cfg = types.GenerateContentConfig(system_instruction=system_instruction)
    models = config.MODELS_PAID if paid else config.MODELS_FREE

    last_error = None
    for model in models:
        for _ in range(2):
            try:
                resp = client.models.generate_content(
                    model=model, contents=prompt, config=cfg
                )
                return (resp.text or "", model)
            except genai_errors.ServerError as e:
                last_error = e
                time.sleep(1.5)
            except genai_errors.ClientError as e:
                last_error = e
                break
    raise last_error
