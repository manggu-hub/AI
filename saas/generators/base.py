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


def with_brand(system: str, brand: dict | None) -> str:
    """브랜드 보이스를 system_instruction에 주입 (차별화 핵심)."""
    if not brand:
        return system
    lines = ["\n\n[브랜드 가이드라인 — 반드시 일관되게 따를 것]"]
    if brand.get("company"):
        lines.append(f"- 브랜드/회사: {brand['company']}")
    if brand.get("tone"):
        lines.append(f"- 톤앤매너: {brand['tone']}")
    if brand.get("audience"):
        lines.append(f"- 핵심 독자: {brand['audience']}")
    if brand.get("sample"):
        lines.append(f"- 참고 문체 예시(스타일만 모방, 내용 복붙 금지):\n{brand['sample']}")
    if brand.get("avoid"):
        lines.append(f"- 피해야 할 표현/금칙어: {brand['avoid']}")
    return system + "\n".join(lines)


def refine_system(lang: str) -> str:
    """기존 결과물을 사용자 지시대로 수정하는 시스템 지시."""
    base = ("You are an expert editor. Revise the given draft strictly according to "
            "the user's instruction while preserving its format and intent.")
    return base + lang_note(lang)


def variations_note(n: int = 3) -> str:
    return (f"\n\n[중요] 위 요건으로 서로 뚜렷하게 다른 {n}개의 버전을 작성해. "
            f"각 버전을 '--- 버전 1 ---', '--- 버전 2 ---' 처럼 구분선으로 명확히 나눠줘.")
