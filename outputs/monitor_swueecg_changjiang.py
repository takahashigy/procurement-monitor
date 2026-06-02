#!/usr/bin/env python3
"""
Monitor SWUEECG purchasing notices for:
四川省长江造林局六十周年纪念品采购项目

Notification options, in priority order:
- WECHAT_WEBHOOK_URL: full webhook URL, receives JSON {"title": ..., "content": ...}
- SERVERCHAN_SENDKEY: ServerChan/Server酱 sendkey
- PUSHPLUS_TOKEN: PushPlus token

First run creates a baseline and does not notify old notices unless NOTIFY_ON_INIT=1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://swueecg.com"
PROJECT_CODE = "SWUEECG202609293"
PROJECT_NAME = "四川省长江造林局六十周年纪念品采购项目"
OLD_NOTICE_ID = "ec5e5bb5-b518-4357-b314-6b9e39913e43"
OLD_NOTICE_TYPE = "YCGG"
PAGE_URL = (
    "https://swueecg.com/#/purchase/tradeDetail"
    "?id=ec5e5bb5-b518-4357-b314-6b9e39913e43"
    "&activeIndex=0-5&noticeTypes=YCGG"
)

CHNENERGY_SEARCH_URL = (
    "http://www.chnenergybidding.com.cn/"
    "bidfulltextsearch/rest/inteligentSearch/getFullTextData"
)
CHNENERGY_KEYWORD = "丹巴水电站"
CHNENERGY_TITLE_KEYWORDS = ("大渡河公司", "丹巴水电站")
DLNYZB_SEARCH_URL = "https://www.dlnyzb.com/search?kw=丹巴水电站&si=375&page=1"


def request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers = {
        "Client-Id": "swuee",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 swueecg-monitor/1.0",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def compact_html(html: str) -> str:
    text = unescape(html or "")
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def clean_text(text: str) -> str:
    return compact_html(text)


def digest_detail(detail: dict[str, Any]) -> str:
    data = detail.get("data") or {}
    publish_data = data.get("publishData") or {}
    important = {
        "bidSectionName": data.get("bidSectionName"),
        "publishTime": data.get("publishTime"),
        "searchType": data.get("searchType"),
        "title": publish_data.get("bid_title"),
        "projectCode": publish_data.get("proj_number"),
        "noticeStart": publish_data.get("notice_start_time"),
        "noticeEnd": publish_data.get("notice_end_time"),
        "content": compact_html(publish_data.get("content", ""))[:2000],
    }
    raw = json.dumps(important, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"known_ids": [], "detail_digest": None, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_records() -> list[dict[str, Any]]:
    data = request_json(
        f"{BASE_URL}/api/purchasing/search",
        method="POST",
        payload={"current": 1, "size": 20, "projectCode": PROJECT_CODE},
    )
    if data.get("code") != 200:
        raise RuntimeError(f"search API returned: {data}")
    records = (data.get("data") or {}).get("records") or []
    return [r for r in records if r.get("projectCode") == PROJECT_CODE or r.get("projectName") == PROJECT_NAME]


def fetch_old_detail() -> dict[str, Any]:
    qs = urlencode({"id": OLD_NOTICE_ID, "searchType": OLD_NOTICE_TYPE, "n": time.time()})
    data = request_json(f"{BASE_URL}/api/purchasing/detail?{qs}")
    if data.get("code") != 200:
        raise RuntimeError(f"detail API returned: {data}")
    return data


def fetch_chnenergy_records() -> list[dict[str, Any]]:
    payload = {
        "token": "",
        "pn": 0,
        "rn": 20,
        "sdt": "19900101",
        "edt": "",
        "wd": quote(CHNENERGY_KEYWORD),
        "inc_wd": "",
        "exc_wd": "",
        "fields": "title;content",
        "cnum": "",
        "sort": '{"infodate":0}',
        "ssort": "title",
        "cl": 500,
        "terminal": "",
        "condition": None,
        "time": None,
        "highlights": "title;content",
        "statistics": None,
        "unionCondition": None,
        "accuracy": "",
        "noParticiple": "0",
        "searchRange": None,
    }
    data = request_json(CHNENERGY_SEARCH_URL, method="POST", payload=payload)
    records = ((data.get("result") or {}).get("records")) or []
    filtered = []
    for record in records:
        haystack = clean_text((record.get("title") or "") + " " + (record.get("content") or ""))
        if all(keyword in haystack for keyword in CHNENERGY_TITLE_KEYWORDS):
            filtered.append(record)
    return filtered


def chnenergy_url(record: dict[str, Any]) -> str:
    link = record.get("linkurl") or ""
    if link.startswith("http"):
        return link
    return "http://www.chnenergybidding.com.cn" + link


def notice_url(record: dict[str, Any]) -> str:
    notice_type = record.get("noticeType") or ""
    active_index = "1-0" if record.get("purchasingType") else "0-0"
    if notice_type in {"YCGG", "ZJYCGG"}:
        active_index = "0-5"
    return (
        f"{BASE_URL}/#/purchase/tradeDetail?id={record.get('id')}"
        f"&activeIndex={active_index}&noticeTypes={notice_type}"
    )


def send_notification(title: str, content: str) -> None:
    webhook = os.getenv("WECHAT_WEBHOOK_URL")
    serverchan = os.getenv("SERVERCHAN_SENDKEY")
    pushplus = os.getenv("PUSHPLUS_TOKEN") or load_secret("PUSHPLUS_TOKEN")

    if webhook:
        request_json(webhook, method="POST", payload={"title": title, "content": content})
        return

    if serverchan:
        url = f"https://sctapi.ftqq.com/{serverchan}.send"
        payload = urlencode({"title": title, "desp": content}).encode("utf-8")
        req = Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=20) as resp:
            resp.read()
        return

    if pushplus:
        request_json(
            "https://www.pushplus.plus/send",
            method="POST",
            payload={"token": pushplus, "title": title, "content": content, "template": "markdown"},
        )
        return

    print("No WeChat notification token configured; printing alert only.", file=sys.stderr)
    print(f"{title}\n{content}")


def load_secret(name: str) -> str:
    candidates = [
        Path.cwd() / "work" / "monitor_secrets.json",
        Path(__file__).resolve().parent / "monitor_secrets.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        value = data.get(name)
        if value:
            return str(value)
    return ""


def format_record(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"- 标题：{record.get('title')}",
            f"- 项目编号：{record.get('projectCode')}",
            f"- 公告类型：{record.get('noticeType')} / {record.get('searchType')}",
            f"- 发布时间：{record.get('recTime')}",
            f"- 报名/截止：{record.get('enrollEndTime') or '-'}",
            f"- 链接：{notice_url(record)}",
        ]
    )


def format_chnenergy_record(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"- 来源：国家能源招标网",
            f"- 标题：{clean_text(record.get('title') or '')}",
            f"- 发布时间：{record.get('infodate') or '-'}",
            f"- 分类：{record.get('categorynum') or '-'}",
            f"- 链接：{chnenergy_url(record)}",
        ]
    )


def check(state_path: Path, init: bool = False) -> int:
    state = load_state(state_path)
    records = fetch_records()
    detail = fetch_old_detail()
    chnenergy_records = fetch_chnenergy_records()
    detail_hash = digest_detail(detail)

    known_ids = set(state.get("known_ids") or [])
    current_ids = {r.get("id") for r in records if r.get("id")}
    new_records = [r for r in records if r.get("id") and r.get("id") not in known_ids]

    chnenergy_known_ids = set(state.get("chnenergy_known_ids") or [])
    chnenergy_current_ids = {r.get("id") for r in chnenergy_records if r.get("id")}
    chnenergy_new_records = [
        r for r in chnenergy_records if r.get("id") and r.get("id") not in chnenergy_known_ids
    ]
    detail_changed = state.get("detail_digest") not in (None, detail_hash)

    state["known_ids"] = sorted(current_ids | known_ids)
    state["chnenergy_known_ids"] = sorted(chnenergy_current_ids | chnenergy_known_ids)
    state["detail_digest"] = detail_hash
    state["last_checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state_path, state)

    if init and not os.getenv("NOTIFY_ON_INIT"):
        print(
            "Baseline initialized with "
            f"{len(current_ids)} SWUEECG notices and "
            f"{len(chnenergy_current_ids)} CHN Energy notices. No notification sent."
        )
        return 0

    alerts: list[str] = []
    for record in new_records:
        title = record.get("title") or ""
        if "终止" not in title and "异常" not in title:
            alerts.append(format_record(record))
        else:
            alerts.append("发现新的终止/异常类公告：\n" + format_record(record))

    if detail_changed:
        alerts.append(f"旧详情页内容发生变化：{PAGE_URL}")

    for record in chnenergy_new_records:
        alerts.append(format_chnenergy_record(record))

    if alerts:
        send_notification(
            "采购/招标公告更新",
            "\n\n".join(alerts),
        )
        print(f"Alert sent. {len(alerts)} change(s).")
        return 2

    print(
        "No change. "
        f"Known SWUEECG notices: {len(current_ids)}. "
        f"Known CHN Energy notices: {len(chnenergy_current_ids)}. "
        f"dlnyzb fallback URL: {DLNYZB_SEARCH_URL}. "
        f"Checked at {state['last_checked_at']}."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=str(Path(__file__).with_suffix(".state.json")))
    parser.add_argument("--init", action="store_true", help="initialize baseline without notifying old notices")
    args = parser.parse_args()

    try:
        return check(Path(args.state), init=args.init)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
