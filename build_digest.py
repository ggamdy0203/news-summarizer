# -*- coding: utf-8 -*-
"""
부동산/금융/증권/산업/글로벌경제 투자 뉴스 다이제스트를 한 번에 만들어
digest.json에 병합 저장하는 스크립트.

스케줄 작업(realestate-news-digest-morning/afternoon)은 이 스크립트만 실행하면 된다:
    python build_digest.py morning   (또는 afternoon)

내부에서 한국경제 RSS + 네이버 뉴스 검색 API로 기사를 모으고,
Gemini로 기사별 AI 심층 요약(3~4개 불릿)을 미리 만들어 digest.json에 저장한다.
"""

import sys
import os
import re
import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# API 키는 이 저장소에 커밋되지 않는 별도 로컬 파일(secrets.local.json)에서 읽는다.
_SECRETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.local.json")
with open(_SECRETS_PATH, "r", encoding="utf-8") as _f:
    _secrets = json.load(_f)

GEMINI_API_KEY = _secrets["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-2.5-flash"
NAVER_CLIENT_ID = _secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = _secrets["NAVER_CLIENT_SECRET"]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
KST = timezone(timedelta(hours=9))
MAX_PER_CATEGORY = 3

SUMMARY_FORMAT = (
    '요약은 3~4개의 핵심 포인트로 나눠서, 포인트마다 줄을 바꾸고 맨 앞에 "• "를 붙여줘. '
    '각 포인트는 한 문장으로 짧고 명확하게 써줘.'
)

CATEGORIES = [
    {"category": "부동산", "naver_query": "부동산", "hk_feed": "realestate"},
    {"category": "금융", "naver_query": "금융", "hk_feed": None},
    {"category": "증권", "naver_query": "증권", "hk_feed": "finance"},
    {"category": "산업", "naver_query": "산업", "hk_feed": None},
    {"category": "글로벌경제", "naver_query": "글로벌 경제", "hk_feed": "international"},
]

HK_SOURCE_NAME = "한국경제"
NAVER_SOURCE_NAME = "네이버 뉴스"


def log(msg):
    print(msg, flush=True)


def fetch_hankyung_rss(feed):
    if not feed:
        return []
    url = f"https://www.hankyung.com/feed/{feed}"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        items = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if title and link:
                items.append({"title": title, "url": link, "pubDate": pub_date})
        return items
    except Exception as e:
        log(f"  [경고] 한국경제 RSS({feed}) 실패: {e}")
        return []


def fetch_naver_news(query, display=20):
    params = urllib.parse.urlencode({"query": query, "display": display, "sort": "date"})
    url = f"https://openapi.naver.com/v1/search/news.json?{params}"
    headers = dict(UA)
    headers["X-Naver-Client-Id"] = NAVER_CLIENT_ID
    headers["X-Naver-Client-Secret"] = NAVER_CLIENT_SECRET
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        items = []
        for it in data.get("items", []):
            title = re.sub(r"<.*?>", "", it.get("title", "")).strip()
            title = title.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            link = it.get("originallink") or it.get("link") or ""
            items.append({"title": title, "url": link, "pubDate": it.get("pubDate", "")})
        return items
    except Exception as e:
        log(f"  [경고] 네이버 뉴스 검색({query}) 실패: {e}")
        return []


def normalize_title(title):
    return re.sub(r"[^\w가-힣]", "", title).lower()


def pick_top(items, limit):
    seen = set()
    picked = []
    for it in items:
        key = normalize_title(it["title"])[:20]
        if not key or key in seen:
            continue
        seen.add(key)
        picked.append(it)
        if len(picked) >= limit:
            break
    return picked


def call_gemini(prompt, use_url_context):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if use_url_context:
        body["tools"] = [{"url_context": {}}]
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    status = None
    meta = cand.get("urlContextMetadata", {}).get("urlMetadata")
    if meta:
        status = meta[0].get("urlRetrievalStatus")
    return text, status


def summarize(article_url):
    try:
        prompt = (
            f"다음 링크에 접속해서 글 내용을 읽고 핵심만 한국어로 요약해줘. {SUMMARY_FORMAT} "
            f"머릿말이나 따옴표 없이 바로 첫 포인트부터 시작해.\n\n링크: {article_url}"
        )
        text, status = call_gemini(prompt, use_url_context=True)
        if status == "URL_RETRIEVAL_STATUS_SUCCESS" and text:
            return text
    except Exception as e:
        log(f"    url_context 실패: {e}")

    try:
        reader_req = urllib.request.Request(f"https://r.jina.ai/{article_url}", headers=UA)
        with urllib.request.urlopen(reader_req, timeout=20) as r:
            article_text = r.read().decode("utf-8", errors="replace")[:16000]
        fallback_prompt = (
            "다음은 어떤 기사 페이지에서 가져온 텍스트다. 광고/메뉴/구독 안내 같은 본문과 무관한 내용은 "
            f"무시하고, 핵심만 한국어로 요약해줘. {SUMMARY_FORMAT} 머릿말이나 따옴표 없이 바로 요약문부터 시작해.\n\n{article_text}"
        )
        text2, _ = call_gemini(fallback_prompt, use_url_context=False)
        return text2 or "요약 내용을 생성하지 못했습니다."
    except Exception as e:
        return f"요약 내용을 생성하지 못했습니다. ({e})"


def build_entry(slot):
    now_kst = datetime.now(timezone.utc).astimezone(KST)
    today_str = now_kst.strftime("%Y-%m-%d")
    label_prefix = "오전 다이제스트" if slot == "morning" else "오후 다이제스트"
    label = f"{label_prefix} · {today_str}"

    categories_out = []
    headline_candidates = []

    for cat in CATEGORIES:
        cat_name = cat["category"]
        log(f"[{cat_name}] 기사 수집 중...")

        hk_items = pick_top(fetch_hankyung_rss(cat["hk_feed"]), MAX_PER_CATEGORY)
        naver_items = pick_top(fetch_naver_news(cat["naver_query"]), MAX_PER_CATEGORY)

        sections = []
        for source_name, items in [(HK_SOURCE_NAME, hk_items), (NAVER_SOURCE_NAME, naver_items)]:
            if cat["hk_feed"] is None and source_name == HK_SOURCE_NAME:
                continue
            if not items:
                continue
            built_items = []
            for it in items:
                log(f"  요약 중: {it['title'][:40]}")
                summary = summarize(it["url"])
                built_items.append({"title": it["title"], "url": it["url"], "summary": summary})
                headline_candidates.append(it["title"])
                time.sleep(0.3)
            sections.append({"source": source_name, "items": built_items})

        categories_out.append({"category": cat_name, "sections": sections})

    entry = {
        "label": label,
        "createdAt": now_kst.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "categories": categories_out,
    }
    return entry, today_str, headline_candidates


def merge_and_save(entry, today_str, digest_path):
    if os.path.exists(digest_path):
        try:
            with open(digest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"entries": []}
    else:
        data = {"entries": []}

    existing = data.get("entries", [])
    kept = [e for e in existing if today_str in (e.get("label") or "")]
    kept.insert(0, entry)
    data["entries"] = kept[:10]

    with open(digest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    slot = sys.argv[1] if len(sys.argv) > 1 else "morning"
    digest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "digest.json")

    entry, today_str, headlines = build_entry(slot)
    merge_and_save(entry, today_str, digest_path)

    log("\n=== 완성된 다이제스트 ===")
    log(entry["label"])
    for cat in entry["categories"]:
        log(f"\n[{cat['category']}]")
        for section in cat["sections"]:
            for item in section["items"]:
                log(f"  - {item['title']}")

    top_headline = headlines[0] if headlines else "새 기사 없음"
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_last_top_headline.txt"), "w", encoding="utf-8") as f:
        f.write(top_headline)


if __name__ == "__main__":
    main()
