"""Supabase Auth 래퍼 (회원가입/로그인/로그아웃)."""
from core import db


def sign_up(email: str, password: str):
    sb = db.get_supabase()
    res = sb.auth.sign_up({"email": email, "password": password})
    if res.user:
        # 이메일 확인이 꺼져 있으면 session이 바로 생기고, 켜져 있으면 None
        db.ensure_profile(sb, res.user.id, email)
    return res


def sign_in(email: str, password: str):
    sb = db.get_supabase()
    res = sb.auth.sign_in_with_password({"email": email, "password": password})
    if res.user:
        db.ensure_profile(sb, res.user.id, email)
    return res


def sign_out():
    sb = db.get_supabase()
    try:
        sb.auth.sign_out()
    except Exception:
        pass
