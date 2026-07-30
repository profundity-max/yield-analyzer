"""
Auth sub-handler: 给 nginx auth_request 用

职责:
1. /check    - 验证 session cookie（仅 cookie，无 Basic Auth 回退）
2. /login    - 完整认证（Cookie 或 Basic Auth），成功后 302 跳转到 /
3. /logout   - 清除 cookie

监听 127.0.0.1:9999 (仅本机, 外部不可达)

设计目标：杜绝双弹窗问题。
- /check 只查 cookie → 401 时 nginx 302 到 /login
- /login 负责 Basic Auth 弹窗 → 成功后 Set-Cookie + 302 到 /
- 跳转确保 cookie 在 Streamlit 页面加载前已写入浏览器
"""

import base64
import hmac
import hashlib
import os
import time
from aiohttp import web
import asyncio

# ── 配置 ──
HTPASSWD_PATH = os.path.expanduser("~/.config/yield-nginx/conf/.htpasswd")
COOKIE_SECRET = "yield-analyzer-cookie-secret-2026"
COOKIE_NAME = "yield_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天


def parse_htpasswd(path: str) -> dict[str, str]:
    """读取 htpasswd 文件, 返回 {user: hash}。"""
    result = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                u, h = line.split(":", 1)
                result[u] = h
    return result


USERS = parse_htpasswd(HTPASSWD_PATH)


def check_apr1(password: str, hashed: str) -> bool:
    """验证 APR1 (apache md5) 哈希。"""
    import passlib.hash
    return passlib.hash.apr_md5_crypt.verify(password, hashed)


def make_cookie_value(username: str) -> str:
    """生成签名 cookie: username|expiry|hmac。"""
    expiry = int(time.time()) + COOKIE_MAX_AGE
    payload = f"{username}|{expiry}"
    sig = hmac.new(
        COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{payload}|{sig}"


def verify_cookie_value(cookie: str) -> str | None:
    """验证 cookie, 成功返回 username, 失败返回 None。"""
    try:
        payload, sig = cookie.rsplit("|", 1)
        expected = hmac.new(
            COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        username, expiry = payload.split("|", 1)
        if int(expiry) < time.time():
            return None
        return username
    except Exception:
        return None


def make_set_cookie_header(username: str) -> str:
    """构造 Set-Cookie 响应头（Lax: 允许同站 top-level 导航携带）。"""
    cookie_value = make_cookie_value(username)
    return (
        f"{COOKIE_NAME}={cookie_value}; "
        f"Path=/; Max-Age={COOKIE_MAX_AGE}; HttpOnly; SameSite=Lax"
    )


def clear_cookie_header() -> str:
    return f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly"


def verify_basic_auth(request: web.Request) -> str | None:
    """从 Authorization 头提取并验证 Basic Auth，成功返回用户名。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return None
    if username in USERS and check_apr1(password, USERS[username]):
        return username
    return None


def check_cookie(request: web.Request) -> str | None:
    """检查 session cookie，成功返回用户名。"""
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return verify_cookie_value(cookie)
    return None


# ── 路由 ──


async def handle_check(request: web.Request) -> web.Response:
    """
    /check — 仅验证 cookie，供 nginx auth_request 使用。
    只查 cookie，不回调 Basic Auth（避免 WebSocket 触发第二次弹窗）。
    成功: 200
    失败: 401 → nginx 302 到 /login
    """
    username = check_cookie(request)
    if username:
        return web.Response(
            status=200,
            headers={"X-Auth-User": username},
        )
    return web.Response(status=401)


async def handle_login(request: web.Request) -> web.Response:
    """
    /login — 完整认证入口。
    1. 已有有效 cookie → 直接 302 到 /
    2. 有 Basic Auth 头且验证通过 → Set-Cookie + 302 到 /
    3. 都没有 → 401 → nginx 下放 WWW-Authenticate，浏览器弹 Basic Auth 框
    """
    # 已有 cookie → 直接跳转
    username = check_cookie(request)
    if username:
        raise web.HTTPFound(location="/")

    # Basic Auth 验证
    username = verify_basic_auth(request)
    if username:
        # 成功 → 写入 cookie + 跳转到首页
        response = web.HTTPFound(location="/")
        response.headers["Set-Cookie"] = make_set_cookie_header(username)
        response.headers["X-Auth-User"] = username
        return response

    # 未认证 → 401
    return web.Response(status=401)


async def handle_logout(request: web.Request) -> web.Response:
    response = web.HTTPFound(location="/")
    response.headers["Set-Cookie"] = clear_cookie_header()
    return response


# ── 启动 ──

app = web.Application()
app.router.add_get("/check", handle_check)
app.router.add_get("/login", handle_login)
app.router.add_post("/login", handle_login)
app.router.add_get("/logout", handle_logout)


if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=9999, access_log=None)
