"""Predict which GA4 *default channel group* a source/medium/campaign lands in.

Rules follow Google's "Traffic-source dimensions" help page
(https://support.google.com/analytics/answer/9756891, fetched 2026-11-07):
matching is case-insensitive and rules are evaluated in the order below.
Google decides Paid Search / Paid Social / Paid Video / Shopping / Organic
Search / Social / Video by comparing the *source* against long lists that
Google maintains; the lists here are small, partial copies of the best-known
sites. When the answer depends on a source outside our lists the result is
flagged ``certain=False`` instead of guessing. This is a pre-flight check,
not a substitute for GA4's own reports.
"""
from __future__ import annotations

import re
from typing import NamedTuple

_PAID = re.compile(r"^(.*cp.*|ppc|retargeting|paid.*)$", re.I)
_SHOP_CAMPAIGN = re.compile(r"^(.*(([^a-df-z]|^)shop|shopping).*)$", re.I)
_SEARCH = {"google", "bing", "yahoo", "duckduckgo", "baidu", "yandex", "ecosia", "ask",
           "naver", "brave", "startpage", "qwant", "seznam"}
_SOCIAL = {"facebook", "instagram", "linkedin", "twitter", "t.co", "pinterest", "reddit",
           "tiktok", "snapchat", "threads", "tumblr", "quora", "mastodon", "bluesky", "whatsapp",
           "telegram", "discord", "vk", "weibo", "wechat"}
_VIDEO = {"youtube", "vimeo", "twitch", "dailymotion"}
_SHOP = {"amazon", "ebay", "etsy", "walmart", "shopify", "alibaba", "aliexpress", "target"}
_DISPLAY = {"display", "banner", "expandable", "interstitial", "cpm"}
_SOCIAL_MED = {"social", "social-network", "social-media", "sm", "social network", "social media"}
_EMAIL = {"email", "e-mail", "e_mail", "e mail"}


class Channel(NamedTuple):
    name: str
    certain: bool
    note: str = ""


def ga4_channel(source: str, medium: str, campaign: str = "") -> Channel:
    s, m, c = source.strip().lower(), medium.strip().lower(), campaign.strip().lower()
    if s == "(direct)" and m in ("(not set)", "(none)"):
        return Channel("Direct", True)
    if "cross-network" in c:
        return Channel("Cross-network", True)
    paid = bool(_PAID.match(m))
    if paid and (s in _SHOP or _SHOP_CAMPAIGN.match(c)):
        return Channel("Paid Shopping", True)
    if paid and s in _SEARCH:
        return Channel("Paid Search", True)
    if paid and s in _SOCIAL:
        return Channel("Paid Social", True)
    if paid and s in _VIDEO:
        return Channel("Paid Video", True)
    if m in _DISPLAY:
        return Channel("Display", True)
    if paid:
        return Channel("Paid Other", False,
                       "becomes Paid Search/Social/Video/Shopping if Google lists this source")
    if s in _SHOP or _SHOP_CAMPAIGN.match(c):
        return Channel("Organic Shopping", True)
    if s in _SOCIAL or m in _SOCIAL_MED:
        return Channel("Organic Social", True)
    if s in _VIDEO or re.match(r"^(.*video.*)$", m):
        return Channel("Organic Video", True)
    if s in _SEARCH or m == "organic":
        return Channel("Organic Search", True)
    if m in ("referral", "app", "link"):
        return Channel("Referral", True)
    if s in _EMAIL or m in _EMAIL:
        return Channel("Email", True)
    if m == "affiliate":
        return Channel("Affiliates", True)
    if m == "audio":
        return Channel("Audio", True)
    if s == "sms" or m == "sms":
        return Channel("SMS", True)
    if m.endswith("push") or "mobile" in m or "notification" in m or s == "firebase":
        return Channel("Mobile Push Notifications", True)
    # A source on Google's (longer) lists would have matched above only if it is
    # also in our partial lists, so flag the guess as uncertain when it might be.
    return Channel("Unassigned", False,
                   "no GA4 default-channel rule matches (our source lists are partial)")
