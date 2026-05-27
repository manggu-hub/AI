"""생성기 레지스트리.

각 생성기는 dict로 정의된다:
    key    : 고유 식별자 (generations.type 으로 저장)
    label  : UI 표시명
    group  : 사이드/카테고리 묶음
    fields : 입력 폼 정의 리스트
             {name, label, type('text'|'textarea'|'select'), options?, placeholder?, required?}
    system : (lang) -> system_instruction 문자열
    prompt : (params: dict, lang) -> 프롬프트 문자열

새 생성기를 추가하려면 generators/ 아래 모듈에서 GENERATORS 리스트에 append 한 뒤
여기 _MODULES 에 등록하면 된다.
"""
from generators import blog, email, marketing, social, startup

_MODULES = [blog, social, marketing, email, startup]

GENERATORS: dict[str, dict] = {}
for _m in _MODULES:
    for _spec in _m.GENERATORS:
        GENERATORS[_spec["key"]] = _spec


def groups() -> dict[str, list[dict]]:
    """group 이름 -> 생성기 리스트 (UI 그룹핑용)."""
    out: dict[str, list[dict]] = {}
    for spec in GENERATORS.values():
        out.setdefault(spec["group"], []).append(spec)
    return out


def lang_note(lang: str) -> str:
    """모든 system_instruction 끝에 붙이는 출력 언어 지시."""
    if lang == "en":
        return " Write the entire output in natural, fluent English."
    return " 결과물 전체를 자연스러운 한국어로 작성해."
