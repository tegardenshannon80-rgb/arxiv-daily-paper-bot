"""Generic Feishu (Lark) sender for the arXiv daily pipeline.

Why this file exists:
  The upstream code hard-codes a private Feishu card template
  (template_id "AAqxH62u1uNko"). That template only exists in the
  original author's Feishu tenant, so a fresh deployment cannot send it.
  This sender builds a standard interactive card instead, so it works
  with any custom-bot webhook.

Env:
  FEISHU_URL          comma-separated webhook URL(s), required unless --dry-run
  FEISHU_SECRET       optional signature secret (custom bot -> signature verification)
  RETURN_PAPERS       default 20
  FEISHU_CHUNK_SIZE   papers per card, default 6
  FEISHU_DRY_RUN      "1" to only write a preview JSON
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT.parents[1] / ".env")
except ImportError:
    pass


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _sign(secret, timestamp):
    # Feishu custom bot signature:
    # string_to_sign = f"{timestamp}\n{secret}"
    # sign = base64(hmac_sha256(key=string_to_sign, msg=""))
    string_to_sign = "{}\n{}".format(timestamp, secret)
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def today_data_file():
    """Only send *today's* file; avoids re-sending yesterday's data on a failed run."""
    if not DATA_DIR.exists():
        return None
    path = DATA_DIR / (datetime.now().strftime("%Y%m%d") + ".json")
    return path if path.exists() else None


def load_papers(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    papers = []
    if isinstance(raw, dict):
        for arxiv_id, info in raw.items():
            if not isinstance(info, dict):
                continue
            item = dict(info)
            item.setdefault("arxiv_id", arxiv_id)
            papers.append(item)
    elif isinstance(raw, list):
        papers = [dict(x) for x in raw if isinstance(x, dict)]
    return papers


def select_papers(papers, limit):
    ranked = [p for p in papers if p.get("is_fine_ranked") and isinstance(p.get("rerank_relevance_score"), (int, float))]
    if not ranked:
        ranked = [p for p in papers if isinstance(p.get("rerank_relevance_score"), (int, float))]
    if not ranked:
        ranked = papers
    ranked.sort(key=lambda p: p.get("rerank_relevance_score", 0), reverse=True)
    return ranked[:limit]


def _short(text, n):
    text = (text or "").strip().replace("\r", "")
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def build_card(papers, date, part, total_parts, categories):
    elements = []
    if total_parts > 1:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**Part {part}/{total_parts}**"},
        })
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": f"{categories} · Top {len(papers)}"}],
    })
    for idx, paper in enumerate(papers, start=1):
        title = _short(paper.get("title", "Untitled"), 180)
        translation = _short(paper.get("translation", ""), 180)
        summary = _short(paper.get("summary", ""), 320)
        url = paper.get("url") or ("https://arxiv.org/abs/" + str(paper.get("arxiv_id", "")))
        arxiv_id = paper.get("arxiv_id", "")
        score = paper.get("rerank_relevance_score", "N/A")
        lines = [
            f"**{idx}. {title}**",
            f"[arXiv:{arxiv_id}]({url}) · ⭐ **{score}/10**",
        ]
        if translation:
            lines.append(f"**中文标题**：{translation}")
        if summary:
            lines.append(summary)
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(lines)},
        })
        if idx != len(papers):
            elements.append({"tag": "hr"})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": f"arXiv Daily · {date}"},
        },
        "elements": elements,
    }


def post_card(url, payload, secret, retries=3):
    if secret:
        ts = str(int(time.time()))
        payload = dict(payload)
        payload["timestamp"] = ts
        payload["sign"] = _sign(secret, ts)

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                data = resp.json()
            except ValueError:
                raise RuntimeError(f"non-JSON response: {resp.text[:300]}")
            code = data.get("code", data.get("StatusCode", 0))
            if code not in (0, None):
                raise RuntimeError(f"Feishu code={code}, msg={data.get('msg', data.get('StatusMessage', ''))}")
            return
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Feishu send failed after {retries} attempts: {last_error}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=None, help="path to YYYYMMDD.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="send again even if the sent marker exists")
    args = parser.parse_args(argv)

    data_path = Path(args.data) if args.data else today_data_file()
    if not data_path or not data_path.exists():
        print("[feishu] no daily JSON found; nothing to send")
        return 0

    papers = load_papers(data_path)
    limit = args.limit if args.limit is not None else _env_int("RETURN_PAPERS", 20)
    papers = select_papers(papers, limit)
    if not papers:
        print("[feishu] no ranked papers; nothing to send")
        return 0

    date = datetime.now().strftime("%Y-%m-%d")
    categories = os.environ.get("TARGET_CATEGORYS", "cs.IR,cs.CL,cs.CV")
    chunk_size = max(1, _env_int("FEISHU_CHUNK_SIZE", 6))
    chunks = [papers[i:i + chunk_size] for i in range(0, len(papers), chunk_size)]
    payloads = []
    for i, chunk in enumerate(chunks, start=1):
        card = build_card(chunk, date, i, len(chunks), categories)
        payloads.append({"msg_type": "interactive", "card": card})

    urls = [u.strip() for u in os.environ.get("FEISHU_URL", "").split(",") if u.strip()]
    secret = os.environ.get("FEISHU_SECRET", "").strip()
    dry_run = args.dry_run or os.environ.get("FEISHU_DRY_RUN", "0") == "1"

    if dry_run:
        out = ROOT / "data" / f"feishu_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payloads, f, ensure_ascii=False, indent=2)
        print(f"[feishu] dry-run: wrote {len(payloads)} card(s) to {out}")
        return 0

    if not urls:
        raise SystemExit("[feishu] FEISHU_URL is empty. Set it as a GitHub Actions secret or use --dry-run.")

    date_key = data_path.stem
    sent_marker = DATA_DIR / f".feishu_sent_{date_key}"
    if sent_marker.exists() and not args.force:
        print(f"[feishu] {date_key} already sent ({sent_marker.name}); use --force to resend")
        return 0

    for i, payload in enumerate(payloads, start=1):
        for url in urls:
            post_card(url, payload, secret)
        print(f"[feishu] sent part {i}/{len(payloads)} to {len(urls)} webhook(s)")
        time.sleep(0.5)

    sent_marker.write_text(datetime.now().isoformat(), encoding="utf-8")
    print(f"[feishu] done: {len(papers)} paper(s), {len(payloads)} card(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
