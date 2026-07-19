"""
Platform definitions + individual check functions for HandleCheck.

Every checker is an async function that takes (client, username) and
returns a dict: {"status": "available"|"taken"|"unknown", "note": str|None}

status meanings:
  available -> the exact string looks free on that platform
  taken     -> the exact string looks in use
  unknown   -> we couldn't tell (blocked, JS-only site, ambiguous response, error)
"""

import asyncio
import socket
import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 HandleCheck/1.0"
    )
}

TIMEOUT = 6.0

# Phrases that show up on interstitial/challenge pages instead of real content.
# When we see these, a 200 status code does NOT mean "profile exists" — it
# means we got a bot-block page, and the honest answer is "unknown".
_BOT_WALL_MARKERS = (
    "checking your browser",
    "just a moment",
    "cf-browser-verification",
    "attention required! | cloudflare",
    "enable javascript and cookies to continue",
    "please verify you are a human",
    "unusual traffic from your computer network",
    "captcha",
    "access denied",
    "sorry, you have been blocked",
    "type the characters you see in this image",
    "to discuss automated access to amazon data",
    "robot check",
)


def _looks_like_bot_wall(body: str) -> bool:
    sample = body[:4000].lower()
    return any(marker in sample for marker in _BOT_WALL_MARKERS)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

async def _get(client: httpx.AsyncClient, url: str, **kwargs):
    return await client.get(url, headers=HEADERS, timeout=TIMEOUT,
                             follow_redirects=True, **kwargs)


def status_from_code(url_template):
    """Standard case: 404 => available, 200 => taken, anything else => unknown.
    Guards against Cloudflare/bot-block interstitials that return 200 with
    a challenge page instead of the real profile — those get reported as
    unknown rather than a false 'taken'.
    """
    async def check(client, username):
        url = url_template.format(u=username)
        try:
            resp = await _get(client, url)
            if resp.status_code == 404:
                return {"status": "available", "note": None}
            if resp.status_code == 200:
                if _looks_like_bot_wall(resp.text):
                    return {
                        "status": "unknown",
                        "note": "site returned a bot-check page instead of the profile",
                    }
                return {"status": "taken", "note": None}
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        except httpx.RequestError as e:
            return {"status": "unknown", "note": "request failed"}
    return check


def best_effort_unknown(note):
    """For platforms that are JS-rendered / actively block bots — we don't guess."""
    async def check(client, username):
        return {"status": "unknown", "note": note}
    return check


# ---------------------------------------------------------------------------
# Custom checkers
# ---------------------------------------------------------------------------

REDDIT_HEADERS = {
    # Reddit specifically wants a descriptive UA in this rough shape, and is
    # more likely to 403 a generic browser-style UA than most other sites.
    "User-Agent": "web:handlecheck-scanner:v1.0 (by /u/handlecheck)",
    "Accept": "application/json",
}


async def _reddit_lookup(client, url):
    resp = await client.get(
        url, headers=REDDIT_HEADERS, timeout=TIMEOUT, follow_redirects=True
    )
    return resp


async def check_reddit(client, username):
    # Try the modern endpoint first, then fall back to old.reddit.com,
    # which is sometimes less aggressive about blocking.
    for base in ("https://www.reddit.com", "https://old.reddit.com"):
        url = f"{base}/user/{username}/about.json"
        try:
            resp = await _reddit_lookup(client, url)
        except httpx.RequestError:
            continue

        if resp.status_code == 404:
            return {"status": "available", "note": None}
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("data", {}).get("name"):
                return {"status": "taken", "note": None}
            continue
        if resp.status_code in (403, 429):
            # Reddit is blocking this request/IP outright — try the other
            # base URL before giving up.
            continue
        return {"status": "unknown", "note": f"HTTP {resp.status_code}"}

    return {
        "status": "unknown",
        "note": "Reddit blocked the automated request (403/429) — check the link manually",
    }


async def check_hackernews(client, username):
    url = f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
    try:
        resp = await _get(client, url)
        if resp.status_code == 200:
            body = resp.text.strip()
            if body == "null":
                return {"status": "available", "note": None}
            return {"status": "taken", "note": None}
        return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


async def check_keybase(client, username):
    url = f"https://keybase.io/_/api/1.0/user/lookup.json?usernames={username}"
    try:
        resp = await _get(client, url)
        data = resp.json()
        results = data.get("them", [])
        if results and results[0]:
            return {"status": "taken", "note": None}
        return {"status": "available", "note": None}
    except (httpx.RequestError, ValueError):
        return {"status": "unknown", "note": "request failed"}


async def check_dockerhub(client, username):
    url = f"https://hub.docker.com/v2/users/{username}/"
    try:
        resp = await _get(client, url)
        if resp.status_code == 404:
            return {"status": "available", "note": None}
        if resp.status_code == 200:
            return {"status": "taken", "note": None}
        return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


async def check_steam(client, username):
    url = f"https://steamcommunity.com/id/{username}"
    try:
        resp = await _get(client, url)
        if resp.status_code != 200:
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        body = resp.text
        if _looks_like_bot_wall(body):
            return {
                "status": "unknown",
                "note": "Steam returned a bot-check page — verify manually",
            }
        lower = body.lower()
        if "the specified profile could not be found" in lower:
            return {"status": "available", "note": None}
        return {"status": "taken", "note": None}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


async def check_telegram(client, username):
    url = f"https://t.me/{username}"
    try:
        resp = await _get(client, url)
        if resp.status_code != 200:
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        body = resp.text
        if _looks_like_bot_wall(body):
            return {
                "status": "unknown",
                "note": "Telegram returned a bot-check page — verify manually",
            }
        # Telegram serves a generic marketing page for handles with no account,
        # and a profile preview (with a message/open-in-app button) for real ones.
        if "tgme_action_button_new" in body or "tgme_page_action_button" in body:
            return {"status": "taken", "note": None}
        if "tgme_page_title" in body:
            return {"status": "taken", "note": None}
        return {"status": "available", "note": "best-effort check"}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


def subdomain_status_check(domain_suffix):
    """For platforms hosted as {username}.{domain} — 404 vs 200 on the subdomain."""
    async def check(client, username):
        url = f"https://{username}.{domain_suffix}"
        try:
            resp = await _get(client, url)
            if resp.status_code == 404:
                return {"status": "available", "note": None}
            if resp.status_code == 200:
                if _looks_like_bot_wall(resp.text):
                    return {
                        "status": "unknown",
                        "note": "site returned a bot-check page instead of the profile",
                    }
                return {"status": "taken", "note": None}
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        except httpx.RequestError:
            return {"status": "unknown", "note": "request failed"}
    return check


async def check_youtube(client, username):
    url = f"https://www.youtube.com/@{username}"
    try:
        resp = await _get(client, url)
        if resp.status_code == 404:
            return {"status": "available", "note": None}
        if resp.status_code != 200:
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        body = resp.text
        if _looks_like_bot_wall(body):
            return {
                "status": "unknown",
                "note": "YouTube returned a bot-check page — verify manually",
            }
        lower = body.lower()
        if "this channel does not exist" in lower or "404 not found" in lower:
            return {"status": "available", "note": None}
        return {"status": "taken", "note": None}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


async def check_quora(client, username):
    url = f"https://www.quora.com/profile/{username}"
    try:
        resp = await _get(client, url)
        if resp.status_code == 404:
            return {"status": "available", "note": None}
        if resp.status_code != 200:
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        body = resp.text
        if _looks_like_bot_wall(body):
            return {
                "status": "unknown",
                "note": "Quora returned a bot-check page — verify manually",
            }
        lower = body.lower()
        if "page not found" in lower or "this page is no longer available" in lower:
            return {"status": "available", "note": None}
        return {"status": "taken", "note": None}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


async def check_medium(client, username):
    # Medium's profile page is JS-rendered and increasingly bot-gated; the
    # RSS feed is a plain, publicly-served XML document and a much more
    # reliable signal for whether the handle exists.
    url = f"https://medium.com/feed/@{username}"
    try:
        resp = await _get(client, url)
        if resp.status_code == 404:
            return {"status": "available", "note": None}
        if resp.status_code != 200:
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        body = resp.text
        if _looks_like_bot_wall(body):
            return {
                "status": "unknown",
                "note": "Medium returned a bot-check page — verify manually",
            }
        if "<rss" in body.lower():
            return {"status": "taken", "note": None}
        return {"status": "available", "note": None}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


async def check_roblox(client, username):
    # Official Roblox API — reliable, no scraping involved.
    url = "https://users.roblox.com/v1/usernames/users"
    try:
        resp = await client.post(
            url,
            json={"usernames": [username], "excludeBannedUsers": False},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
        data = resp.json()
        if data.get("data"):
            return {"status": "taken", "note": None}
        return {"status": "available", "note": None}
    except (httpx.RequestError, ValueError):
        return {"status": "unknown", "note": "request failed"}


async def check_minecraft(client, username):
    # Official Mojang API — reliable, no scraping involved.
    # Mojang has been inconsistent about whether a miss returns 204 or 404,
    # so both are treated as "available".
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
    try:
        resp = await _get(client, url)
        if resp.status_code in (204, 404):
            return {"status": "available", "note": None}
        if resp.status_code == 200:
            return {"status": "taken", "note": None}
        if resp.status_code == 400:
            return {"status": "unknown", "note": "invalid characters for Minecraft names"}
        return {"status": "unknown", "note": f"HTTP {resp.status_code}"}
    except httpx.RequestError:
        return {"status": "unknown", "note": "request failed"}


def domain_check(tld):
    async def check(client, username):
        host = f"{username}.{tld}"
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, socket.gethostbyname, host)
            return {"status": "taken", "note": "domain resolves (likely registered)"}
        except socket.gaierror:
            return {"status": "available", "note": "no DNS record found"}
        except Exception:
            return {"status": "unknown", "note": "lookup failed"}
    return check


# ---------------------------------------------------------------------------
# Platform registry
# ---------------------------------------------------------------------------
# Each entry: name, category, profile_url (for the link + display), check fn

PLATFORMS = [
    # --- Developer ---
    {
        "name": "GitHub", "category": "Developer",
        "url": "https://github.com/{u}",
        "check": status_from_code("https://github.com/{u}"),
    },
    {
        "name": "GitLab", "category": "Developer",
        "url": "https://gitlab.com/{u}",
        "check": status_from_code("https://gitlab.com/{u}"),
    },
    {
        "name": "npm", "category": "Developer",
        "url": "https://www.npmjs.com/~{u}",
        "check": status_from_code("https://www.npmjs.com/~{u}"),
    },
    {
        "name": "PyPI", "category": "Developer",
        "url": "https://pypi.org/user/{u}/",
        "check": status_from_code("https://pypi.org/user/{u}/"),
    },
    {
        "name": "crates.io (crate name)", "category": "Developer",
        "url": "https://crates.io/crates/{u}",
        "check": status_from_code("https://crates.io/crates/{u}"),
    },
    {
        "name": "Docker Hub", "category": "Developer",
        "url": "https://hub.docker.com/u/{u}",
        "check": check_dockerhub,
    },
    {
        "name": "Replit", "category": "Developer",
        "url": "https://replit.com/@{u}",
        "check": status_from_code("https://replit.com/@{u}"),
    },
    {
        "name": "CodePen", "category": "Developer",
        "url": "https://codepen.io/{u}",
        "check": status_from_code("https://codepen.io/{u}"),
    },
    {
        "name": "Hacker News", "category": "Developer",
        "url": "https://news.ycombinator.com/user?id={u}",
        "check": check_hackernews,
    },

    # --- Social ---
    {
        "name": "Reddit", "category": "Social",
        "url": "https://www.reddit.com/user/{u}",
        "check": check_reddit,
    },
    {
        "name": "Telegram", "category": "Social",
        "url": "https://t.me/{u}",
        "check": check_telegram,
    },
    {
        "name": "X (Twitter)", "category": "Social",
        "url": "https://x.com/{u}",
        "check": best_effort_unknown("X blocks automated checks — verify manually"),
    },
    {
        "name": "Instagram", "category": "Social",
        "url": "https://instagram.com/{u}",
        "check": best_effort_unknown("Instagram blocks automated checks — verify manually"),
    },
    {
        "name": "Keybase", "category": "Social",
        "url": "https://keybase.io/{u}",
        "check": check_keybase,
    },
    {
        "name": "Mastodon (mastodon.social)", "category": "Social",
        "url": "https://mastodon.social/@{u}",
        "check": status_from_code("https://mastodon.social/@{u}"),
    },
    {
        "name": "Facebook", "category": "Social",
        "url": "https://www.facebook.com/{u}",
        "check": best_effort_unknown("Facebook blocks automated checks — verify manually"),
    },
    {
        "name": "Threads", "category": "Social",
        "url": "https://www.threads.net/@{u}",
        "check": best_effort_unknown("Threads blocks automated checks — verify manually"),
    },
    {
        "name": "Pinterest", "category": "Social",
        "url": "https://www.pinterest.com/{u}/",
        "check": status_from_code("https://www.pinterest.com/{u}/"),
    },
    {
        "name": "Tumblr", "category": "Social",
        "url": "https://{u}.tumblr.com",
        "check": subdomain_status_check("tumblr.com"),
    },
    {
        "name": "Quora", "category": "Social",
        "url": "https://www.quora.com/profile/{u}",
        "check": check_quora,
    },
    {
        "name": "Clubhouse", "category": "Social",
        "url": "https://www.clubhouse.com/@{u}",
        "check": status_from_code("https://www.clubhouse.com/@{u}"),
    },

    # --- Professional ---
    {
        "name": "LinkedIn", "category": "Professional",
        "url": "https://www.linkedin.com/in/{u}",
        "check": best_effort_unknown("LinkedIn blocks automated checks — verify manually"),
    },

    # --- Video & Streaming ---
    {
        "name": "YouTube", "category": "Video & Streaming",
        "url": "https://www.youtube.com/@{u}",
        "check": check_youtube,
    },
    {
        "name": "TikTok", "category": "Video & Streaming",
        "url": "https://www.tiktok.com/@{u}",
        "check": best_effort_unknown("TikTok is JS-rendered and blocks automated checks — verify manually"),
    },
    {
        "name": "Twitch", "category": "Video & Streaming",
        "url": "https://www.twitch.tv/{u}",
        "check": best_effort_unknown("Twitch is JS-rendered — verify manually"),
    },

    # --- Music ---
    {
        "name": "SoundCloud", "category": "Music",
        "url": "https://soundcloud.com/{u}",
        "check": status_from_code("https://soundcloud.com/{u}"),
    },
    {
        "name": "Spotify", "category": "Music",
        "url": "https://open.spotify.com/user/{u}",
        "check": best_effort_unknown("Spotify profiles are JS-rendered — verify manually"),
    },

    # --- Creative ---
    {
        "name": "Dribbble", "category": "Creative",
        "url": "https://dribbble.com/{u}",
        "check": status_from_code("https://dribbble.com/{u}"),
    },
    {
        "name": "Behance", "category": "Creative",
        "url": "https://www.behance.net/{u}",
        "check": status_from_code("https://www.behance.net/{u}"),
    },
    {
        "name": "Product Hunt", "category": "Creative",
        "url": "https://www.producthunt.com/@{u}",
        "check": status_from_code("https://www.producthunt.com/@{u}"),
    },

    # --- Writing ---
    {
        "name": "Medium", "category": "Writing",
        "url": "https://medium.com/@{u}",
        "check": check_medium,
    },
    {
        "name": "Dev.to", "category": "Writing",
        "url": "https://dev.to/{u}",
        "check": status_from_code("https://dev.to/{u}"),
    },
    {
        "name": "Hashnode", "category": "Writing",
        "url": "https://hashnode.com/@{u}",
        "check": status_from_code("https://hashnode.com/@{u}"),
    },

    # --- Gaming ---
    {
        "name": "itch.io", "category": "Gaming",
        "url": "https://{u}.itch.io",
        "check": subdomain_status_check("itch.io"),
    },
    {
        "name": "Steam", "category": "Gaming",
        "url": "https://steamcommunity.com/id/{u}",
        "check": check_steam,
    },
    {
        "name": "Roblox", "category": "Gaming",
        "url": "https://www.roblox.com/search/users?keyword={u}",
        "check": check_roblox,
    },
    {
        "name": "Minecraft", "category": "Gaming",
        "url": "https://namemc.com/profile/{u}",
        "check": check_minecraft,
    },

    # --- Shopping ---
    {
        "name": "Amazon (Influencer Storefront)", "category": "Shopping",
        "url": "https://www.amazon.com/shop/{u}",
        "check": status_from_code("https://www.amazon.com/shop/{u}"),
    },
    {
        "name": "Etsy", "category": "Shopping",
        "url": "https://www.etsy.com/shop/{u}",
        "check": status_from_code("https://www.etsy.com/shop/{u}"),
    },
    {
        "name": "eBay Store", "category": "Shopping",
        "url": "https://www.ebay.com/str/{u}",
        "check": status_from_code("https://www.ebay.com/str/{u}"),
    },

    # --- Domains ---
    {
        "name": ".com domain", "category": "Domains",
        "url": "https://{u}.com",
        "check": domain_check("com"),
    },
    {
        "name": ".io domain", "category": "Domains",
        "url": "https://{u}.io",
        "check": domain_check("io"),
    },
    {
        "name": ".dev domain", "category": "Domains",
        "url": "https://{u}.dev",
        "check": domain_check("dev"),
    },
    {
        "name": ".app domain", "category": "Domains",
        "url": "https://{u}.app",
        "check": domain_check("app"),
    },
]
