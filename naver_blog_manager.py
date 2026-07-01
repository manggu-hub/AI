"""
네이버 블로그 이웃 자동관리 모듈
Playwright 브라우저 자동화 기반
"""

import json
import time
import random
import re
import logging
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

_BROWSER_STATE = "naver_state.json"
_CACHE_FILE    = "neighbor_cache.json"
_LOG_FILE      = "neighbor_log.json"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class NaverBlogManager:
    """네이버 블로그 이웃 자동관리"""

    def __init__(self, data_dir: Path):
        self.data_dir   = data_dir
        self.state_path = data_dir / _BROWSER_STATE
        self.cache_path = data_dir / _CACHE_FILE
        self.log_path   = data_dir / _LOG_FILE
        self._blog_id: Optional[str] = None

    # ─── 브라우저 헬퍼 ─────────────────────────────────────────────

    def _launch(self, p):
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        opts = dict(
            user_agent=_UA,
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
        )
        if self.state_path.exists():
            opts["storage_state"] = str(self.state_path)
        return browser, browser.new_context(**opts)

    @staticmethod
    def _human_type(locator, text: str):
        locator.clear()
        locator.type(text, delay=random.randint(60, 140))

    @staticmethod
    def _wait(lo: float = 0.5, hi: float = 1.5):
        time.sleep(random.uniform(lo, hi))

    # ─── 로그인 / 세션 ─────────────────────────────────────────────

    def login(self, nid: str, npw: str) -> Tuple[bool, str]:
        """네이버 로그인. (성공여부, 메시지) 반환."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser, ctx = self._launch(p)
                page = ctx.new_page()

                page.goto(
                    "https://nid.naver.com/nidlogin.login?mode=form&url=https://www.naver.com/",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                self._wait(0.6, 1.2)

                page.locator("#id").click()
                self._wait(0.2, 0.5)
                self._human_type(page.locator("#id"), nid)
                self._wait(0.3, 0.7)

                page.locator("#pw").click()
                self._wait(0.2, 0.4)
                self._human_type(page.locator("#pw"), npw)
                self._wait(0.4, 0.8)

                page.locator(".btn_login").click()

                try:
                    page.wait_for_url("*naver.com*", timeout=15000)
                    url = page.url

                    if "nidlogin" in url or "nidcheck" in url:
                        err = page.locator(".error_message, #err_common, .login_error")
                        msg = err.first.inner_text().strip() if err.count() > 0 else "아이디/비밀번호를 확인하세요."
                        browser.close()
                        return False, msg

                    if "captcha" in url.lower():
                        browser.close()
                        return False, "캡차 인증이 필요합니다. 잠시 후 다시 시도해주세요."

                    ctx.storage_state(path=str(self.state_path))
                    browser.close()
                    return True, "로그인 성공!"

                except Exception as e:
                    browser.close()
                    return False, f"로그인 시간 초과 또는 보안 인증 필요 ({str(e)[:80]})"

        except Exception as e:
            return False, f"오류: {str(e)[:200]}"

    def logout(self):
        if self.state_path.exists():
            self.state_path.unlink()
        self._blog_id = None

    def is_logged_in(self) -> bool:
        if not self.state_path.exists():
            return False
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser, ctx = self._launch(p)
                page = ctx.new_page()
                page.goto("https://www.naver.com/", timeout=10000, wait_until="domcontentloaded")
                cookies = {c["name"] for c in ctx.cookies()}
                logged = "NID_SES" in cookies or "NID_AUT" in cookies
                browser.close()
                return logged
        except:
            return False

    # ─── 내 블로그 ID ──────────────────────────────────────────────

    def get_my_blog_id(self) -> Optional[str]:
        if self._blog_id:
            return self._blog_id
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser, ctx = self._launch(p)
                page = ctx.new_page()

                # 내 블로그로 이동 시 URL에서 blogId 추출
                page.goto("https://blog.naver.com/MyBlog.naver", timeout=15000)
                self._wait(0.8, 1.5)
                url = page.url
                m = re.search(r"blog\.naver\.com/([A-Za-z0-9_]+)", url)
                if m and m.group(1) not in ("MyBlog.naver",):
                    self._blog_id = m.group(1)
                    browser.close()
                    return self._blog_id

                # 페이지 소스에서 추출
                content = page.content()
                for pat in (r'"blogId"\s*:\s*"([^"]+)"', r"'blogId'\s*:\s*'([^']+)'"):
                    m = re.search(pat, content)
                    if m:
                        self._blog_id = m.group(1)
                        browser.close()
                        return self._blog_id

                # 내 블로그 링크에서 추출
                links = page.locator("a[href*='blog.naver.com']").all()
                for link in links[:20]:
                    href = link.get_attribute("href") or ""
                    m = re.search(r"blog\.naver\.com/([A-Za-z0-9_]+)", href)
                    if m and m.group(1) not in ("MyBlog.naver", "PostList.naver"):
                        self._blog_id = m.group(1)
                        browser.close()
                        return self._blog_id

                browser.close()
                return None
        except Exception as e:
            logger.error(f"get_my_blog_id: {e}")
            return None

    # ─── 이웃 목록 수집 ────────────────────────────────────────────

    def get_following(self, blog_id: str, progress_cb: Optional[Callable] = None) -> List[Dict]:
        """내가 이웃 추가한 목록 (팔로잉)"""
        return self._fetch_neighbor_list(blog_id, "follow", progress_cb)

    def get_followers(self, blog_id: str, progress_cb: Optional[Callable] = None) -> List[Dict]:
        """나를 이웃 추가한 목록 (팔로워)"""
        return self._fetch_neighbor_list(blog_id, "follower", progress_cb)

    def _fetch_neighbor_list(self, blog_id: str, list_type: str, progress_cb=None) -> List[Dict]:
        results: List[Dict] = []
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser, ctx = self._launch(p)
                page = ctx.new_page()

                current_page = 1
                while True:
                    url = (
                        f"https://m.blog.naver.com/BuddyListStatHelper.naver"
                        f"?blogId={blog_id}&type={list_type}&size=100&currentPage={current_page}"
                    )
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")

                    try:
                        raw = page.locator("body").inner_text()
                        data = json.loads(raw)
                        items = (
                            data.get("result", {}).get("buddyList")
                            or data.get("result", {}).get("neighborList")
                            or data.get("buddyList")
                            or []
                        )
                        if not items:
                            break
                        results.extend(items)
                        if progress_cb:
                            progress_cb(len(results))
                        if len(items) < 100:
                            break
                        current_page += 1
                        self._wait(0.5, 1.2)

                    except (json.JSONDecodeError, Exception):
                        # JSON API 실패 시 HTML 스크래핑 폴백
                        html_items = self._scrape_html_neighbor_list(page, blog_id, list_type)
                        results.extend(html_items)
                        break

                browser.close()
        except Exception as e:
            logger.error(f"_fetch_neighbor_list({list_type}): {e}")

        return results

    def _scrape_html_neighbor_list(self, page, blog_id: str, list_type: str) -> List[Dict]:
        results: List[Dict] = []
        mode = "0" if list_type == "follow" else "1"
        page_num = 1
        try:
            while True:
                url = (
                    f"https://blog.naver.com/NeighborList.naver"
                    f"?blogId={blog_id}&mode={mode}&currentPage={page_num}"
                )
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                self._wait(0.5, 1.0)

                rows = page.locator(".buddy_list_item, .neighborListItem, .item_neighbor, .bl_item").all()
                if not rows:
                    break

                for row in rows:
                    try:
                        nick_el = row.locator(".nick, .buddy_name, .name")
                        link_el = row.locator("a[href*='blog.naver.com']").first
                        nick = nick_el.first.inner_text().strip() if nick_el.count() else ""
                        href = link_el.get_attribute("href") if link_el.count() else ""
                        m = re.search(r"blog\.naver\.com/([A-Za-z0-9_]+)", href or "")
                        if m:
                            results.append({
                                "blogId": m.group(1),
                                "nickName": nick,
                                "blogName": nick,
                            })
                    except:
                        pass

                next_btn = page.locator("a.btn_next:not([class*='disabled']), a:has-text('다음'):not([aria-disabled])")
                if next_btn.count() == 0:
                    break
                page_num += 1
                self._wait(0.5, 1.0)
        except Exception as e:
            logger.error(f"HTML scrape error: {e}")
        return results

    # ─── 서로이웃 분석 ─────────────────────────────────────────────

    def analyze_mutual(self, blog_id: str, progress_cb: Optional[Callable] = None) -> Dict:
        """팔로잉/팔로워 분석 후 서로이웃 여부 판단."""
        if progress_cb:
            progress_cb("팔로잉 목록 수집 중...")
        following = self.get_following(blog_id)

        if progress_cb:
            progress_cb("팔로워 목록 수집 중...")
        followers = self.get_followers(blog_id)

        def _id(item):
            return (item.get("blogId") or item.get("blogid") or "").lower()

        following_ids = {_id(f) for f in following if _id(f)}
        follower_ids  = {_id(f) for f in followers if _id(f)}

        mutual_ids     = following_ids & follower_ids
        non_mutual_ids = following_ids - follower_ids   # 내가 팔로우 → 상대 안 함
        fan_ids        = follower_ids  - following_ids  # 상대가 팔로우 → 내가 안 함

        def _filter(lst, ids):
            return [i for i in lst if _id(i) in ids]

        result = {
            "following":   following,
            "followers":   followers,
            "mutual":      _filter(following, mutual_ids),
            "non_mutual":  _filter(following, non_mutual_ids),
            "fans":        _filter(followers, fan_ids),
            "stats": {
                "following_count":  len(following),
                "follower_count":   len(followers),
                "mutual_count":     len(mutual_ids),
                "non_mutual_count": len(non_mutual_ids),
                "fan_count":        len(fan_ids),
            },
        }

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "blog_id": blog_id, **result}, f,
                      ensure_ascii=False, indent=2)

        return result

    def load_cache(self) -> Optional[Dict]:
        if not self.cache_path.exists():
            return None
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except:
            return None

    # ─── 이웃 삭제 ────────────────────────────────────────────────

    def remove_neighbor(self, target_blog_id: str, dry_run: bool = False) -> Tuple[bool, str]:
        """이웃 삭제."""
        if dry_run:
            return True, f"[건식실행] {target_blog_id}"

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser, ctx = self._launch(p)
                page = ctx.new_page()

                # 모바일 블로그 페이지 접속
                page.goto(f"https://m.blog.naver.com/{target_blog_id}", timeout=15000)
                self._wait(0.8, 1.5)

                removed = False
                selectors = [
                    "button.buddy_del_btn",
                    ".btn_buddy_del",
                    "button:has-text('이웃삭제')",
                    "button:has-text('이웃 삭제')",
                    "a:has-text('이웃삭제')",
                ]
                for sel in selectors:
                    btn = page.locator(sel)
                    if btn.count() > 0:
                        btn.first.click()
                        self._wait(0.5, 1.0)
                        # 확인 다이얼로그
                        confirm = page.locator("button:has-text('확인'), button:has-text('삭제')")
                        if confirm.count() > 0:
                            confirm.first.click()
                            self._wait(0.5, 1.0)
                        removed = True
                        break

                browser.close()

                if removed:
                    self._write_log("remove", target_blog_id, True)
                    return True, f"{target_blog_id} 삭제 완료"
                return False, f"삭제 버튼을 찾지 못했습니다 ({target_blog_id})"

        except Exception as e:
            self._write_log("remove", target_blog_id, False, str(e))
            return False, f"오류: {str(e)[:120]}"

    def batch_remove(
        self,
        target_ids: List[str],
        delay_sec: float = 3.0,
        progress_cb: Optional[Callable] = None,
        dry_run: bool = False,
    ) -> Dict:
        """일괄 이웃 삭제. progress_cb(idx, total, blog_id)"""
        res: Dict = {"success": [], "failed": [], "total": len(target_ids)}

        for i, bid in enumerate(target_ids):
            if progress_cb:
                progress_cb(i + 1, len(target_ids), bid)
            ok, msg = self.remove_neighbor(bid, dry_run=dry_run)
            if ok:
                res["success"].append(bid)
            else:
                res["failed"].append({"id": bid, "reason": msg})
            if not dry_run and i < len(target_ids) - 1:
                time.sleep(delay_sec + random.uniform(0.5, 2.5))

        return res

    # ─── 이웃 추가 ────────────────────────────────────────────────

    def add_neighbor(self, target_blog_id: str, is_mutual: bool = False) -> Tuple[bool, str]:
        """이웃 추가 (is_mutual=True → 서로이웃 신청)."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser, ctx = self._launch(p)
                page = ctx.new_page()

                page.goto(f"https://m.blog.naver.com/{target_blog_id}", timeout=15000)
                self._wait(0.8, 1.5)

                added = False
                selectors = [
                    "button.buddy_add_btn",
                    ".btn_buddy_add",
                    "button:has-text('이웃추가')",
                    "button:has-text('이웃 추가')",
                ]
                for sel in selectors:
                    btn = page.locator(sel)
                    if btn.count() > 0:
                        btn.first.click()
                        self._wait(0.5, 1.0)

                        if is_mutual:
                            mut = page.locator("label:has-text('서로이웃'), input[value='mutual']")
                            if mut.count() > 0:
                                mut.first.click()
                                self._wait(0.2, 0.5)

                        confirm = page.locator("button:has-text('확인'), button:has-text('추가'), button[type='submit']")
                        if confirm.count() > 0:
                            confirm.first.click()
                            self._wait(0.5, 1.0)

                        added = True
                        break

                browser.close()

                if added:
                    self._write_log("add", target_blog_id, True)
                    label = "서로이웃" if is_mutual else "이웃"
                    return True, f"{target_blog_id} {label} 추가 완료"
                return False, f"추가 버튼을 찾지 못했습니다 ({target_blog_id})"

        except Exception as e:
            self._write_log("add", target_blog_id, False, str(e))
            return False, f"오류: {str(e)[:120]}"

    # ─── 블로그 검색 ──────────────────────────────────────────────

    def search_blogs(self, keyword: str, max_results: int = 30) -> List[Dict]:
        """네이버 블로그 검색으로 키워드 관련 블로그 목록 반환."""
        results: List[Dict] = []
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser, ctx = self._launch(p)
                page = ctx.new_page()

                encoded = urllib.parse.quote(keyword)
                page.goto(
                    f"https://search.naver.com/search.naver?where=blog&query={encoded}",
                    timeout=15000,
                    wait_until="domcontentloaded",
                )
                self._wait(0.5, 1.2)

                # 검색 결과 항목에서 블로거 정보 추출
                seen: set = set()
                items = page.locator(".api_subject_bx, .blog_item, .total_area").all()
                for item in items:
                    if len(results) >= max_results:
                        break
                    try:
                        # 블로그 URL 링크
                        links = item.locator("a[href*='blog.naver.com']").all()
                        for link in links:
                            href = link.get_attribute("href") or ""
                            m = re.search(r"blog\.naver\.com/([A-Za-z0-9_]+)", href)
                            if not m:
                                continue
                            bid = m.group(1)
                            if bid in seen or bid in ("PostView.naver", "PostList.naver"):
                                continue
                            seen.add(bid)

                            # 닉네임 추출 시도
                            nick_el = item.locator(".name_area, .blog_name, .user_info_area")
                            nick = nick_el.first.inner_text().strip() if nick_el.count() > 0 else bid

                            results.append({
                                "blogId": bid,
                                "nickName": nick,
                                "url": f"https://blog.naver.com/{bid}",
                            })
                            break
                    except:
                        pass

                browser.close()
        except Exception as e:
            logger.error(f"search_blogs: {e}")

        return results

    # ─── 로그 ──────────────────────────────────────────────────────

    def _write_log(self, action: str, blog_id: str, success: bool, error: str = ""):
        logs: List[Dict] = []
        if self.log_path.exists():
            try:
                with open(self.log_path, encoding="utf-8") as f:
                    logs = json.load(f)
            except:
                pass

        logs.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "blog_id": blog_id,
            "success": success,
            "error": error,
        })
        logs = logs[-500:]

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)

    def get_logs(self, limit: int = 100) -> List[Dict]:
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, encoding="utf-8") as f:
                logs = json.load(f)
            return list(reversed(logs[-limit:]))
        except:
            return []
