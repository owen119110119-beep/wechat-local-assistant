#!/usr/bin/env python3
"""Read a public WeChat Official Account article into structured Markdown.

The script is intentionally narrow: exact mp.weixin.qq.com HTTPS URLs, GET only,
no credentials, bounded redirects, bounded response size, and no JS rendering.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html.parser
import json
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


VERSION = "1.0.1"
ALLOWED_HOST = "mp.weixin.qq.com"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
MAX_REDIRECTS = 4

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
WECHAT_WEBVIEW_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.49 NetType/WIFI Language/zh_CN"
)
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
DROP_TAGS = {
    "script", "style", "noscript", "iframe", "object", "svg", "canvas",
    "form", "button", "select", "textarea",
}
VERIFY_MARKERS = (
    "环境异常", "请完成验证", "安全验证", "去验证", "访问过于频繁",
    "verify_wx", "waf_captcha",
)


def log(message: str, quiet: bool = False) -> None:
    if not quiet:
        sys.stderr.write(f"[wechat-article-reader] {message}\n")


def validate_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("URL must use https")
    if parsed.username or parsed.password:
        raise ValueError("credentials in URLs are not allowed")
    if (parsed.hostname or "").lower() != ALLOWED_HOST:
        raise ValueError(f"host must be exactly {ALLOWED_HOST}")
    if parsed.port not in (None, 443):
        raise ValueError("custom ports are not allowed")
    if not parsed.path.startswith("/"):
        raise ValueError("invalid article path")
    return urllib.parse.urlunsplit(parsed)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> Any:
        self.count += 1
        if self.count > MAX_REDIRECTS:
            raise urllib.error.HTTPError(req.full_url, code, "too many redirects", headers, fp)
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        validate_url(absolute)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


@dataclass
class FetchResult:
    body: bytes
    status: int
    content_type: str
    final_url: str
    duration_ms: int
    redirects: int
    profile: str


def fetch_once(url: str, timeout: int, profile: str) -> FetchResult:
    ua = BROWSER_UA if profile == "browser" else WECHAT_WEBVIEW_UA
    headers = {
        "User-Agent": ua,
        "Referer": "https://mp.weixin.qq.com/",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    redirect_handler = SafeRedirectHandler()
    opener = urllib.request.build_opener(redirect_handler)
    request = urllib.request.Request(url, method="GET", headers=headers)
    started = time.monotonic()
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
        final_url = validate_url(response.geturl())
        return FetchResult(
            body=body,
            status=getattr(response, "status", 200),
            content_type=response.headers.get("Content-Type", ""),
            final_url=final_url,
            duration_ms=int((time.monotonic() - started) * 1000),
            redirects=redirect_handler.count,
            profile=profile,
        )


def looks_like_verification(html: str) -> bool:
    head = html[:20000].lower()
    marker_hits = sum(marker.lower() in head for marker in VERIFY_MARKERS)
    has_content_root = bool(re.search(r'id=["\']js_content["\']', html, re.I))
    title_is_verify = bool(re.search(
        r"<title>[^<]*(?:验证|verification|环境异常)[^<]*</title>", head, re.I
    ))
    return title_is_verify or (marker_hits >= 2 and not has_content_root)


class MarkdownWriter:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.skip_depth = 0
        self.list_stack: list[str] = []
        self.link_stack: list[str | None] = []
        self.in_pre = 0
        self.in_code = 0

    @staticmethod
    def _safe_link(value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if value.startswith(("https://", "http://", "#")):
            return value.replace(" ", "%20")
        return None

    def start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        data = dict(attrs)
        if tag in DROP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag == "hr":
            self.parts.append("\n\n---\n\n")
        elif tag == "img":
            src = self._safe_link(data.get("data-src") or data.get("src"))
            if src:
                alt = (data.get("alt") or "图片").replace("]", "\\]")
                self.parts.append(f"\n\n![{alt}]({src})\n\n")
        elif re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("p", "section", "article"):
            self.parts.append("\n\n")
        elif tag in ("ul", "ol"):
            self.list_stack.append(tag)
            self.parts.append("\n")
        elif tag == "li":
            indent = "  " * max(0, len(self.list_stack) - 1)
            marker = "1." if self.list_stack and self.list_stack[-1] == "ol" else "-"
            self.parts.append(f"\n{indent}{marker} ")
        elif tag == "blockquote":
            self.parts.append("\n\n> ")
        elif tag == "pre":
            self.in_pre += 1
            self.parts.append("\n\n```\n")
        elif tag == "code" and not self.in_pre:
            self.in_code += 1
            self.parts.append("`")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "a":
            href = self._safe_link(data.get("href"))
            self.link_stack.append(href)
            if href:
                self.parts.append("[")
        elif tag == "tr":
            self.parts.append("\n")
        elif tag in ("th", "td"):
            self.parts.append(" | ")

    def end(self, tag: str) -> None:
        tag = tag.lower()
        if tag in DROP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if re.fullmatch(r"h[1-6]", tag) or tag in ("p", "section", "article"):
            self.parts.append("\n\n")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self.parts.append("\n")
        elif tag == "pre":
            if self.in_pre:
                self.in_pre -= 1
            self.parts.append("\n```\n\n")
        elif tag == "code" and not self.in_pre and self.in_code:
            self.in_code -= 1
            self.parts.append("`")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else None
            if href:
                self.parts.append(f"]({href})")

    def data(self, value: str) -> None:
        if not self.skip_depth:
            self.parts.append(value)

    def output(self) -> str:
        text = "".join(self.parts).replace("\u200b", "").replace("\ufeff", "")
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\[\s*\]", "", text)
        return text.strip()


class ArticleParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.writer = MarkdownWriter()
        self.in_content = False
        self.content_depth = 0
        self.found_content = False
        self.meta: dict[str, str] = {}
        self.capture_id: str | None = None
        self.capture_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k.lower(): v for k, v in attrs}
        if tag.lower() == "meta":
            key = (data.get("property") or data.get("name") or "").lower()
            value = (data.get("content") or "").strip()
            if key and value:
                self.meta.setdefault(key, value)

        element_id = data.get("id") or ""
        if not self.in_content and element_id == "js_content":
            self.in_content = True
            self.found_content = True
            self.content_depth = 1
            return

        if not self.in_content and element_id in {
            "activity-name", "js_name", "profileBt", "publish_time"
        }:
            self.capture_id = element_id
            self.capture_parts = []

        if self.in_content:
            if tag.lower() not in VOID_TAGS:
                self.content_depth += 1
            self.writer.start(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.in_content:
            self.writer.start(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.in_content:
            self.writer.end(tag)
            if tag.lower() not in VOID_TAGS:
                self.content_depth -= 1
            if self.content_depth <= 0:
                self.in_content = False
                self.content_depth = 0
            return

        if self.capture_id:
            value = " ".join("".join(self.capture_parts).split())
            if value:
                self.meta.setdefault(f"id:{self.capture_id}", value)
            self.capture_id = None
            self.capture_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_content:
            self.writer.data(data)
        elif self.capture_id:
            self.capture_parts.append(data)


def first_match(patterns: list[str], source: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, source, re.I | re.S)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return ""


def parse_article(html_text: str) -> dict[str, Any]:
    parser = ArticleParser()
    parser.feed(html_text)
    parser.close()
    body = parser.writer.output()

    title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or parser.meta.get("id:activity-name")
        or first_match([
            r"var\s+msg_title\s*=\s*['\"](.*?)['\"]\s*;",
            r"window\.msg_title\s*=\s*['\"](.*?)['\"]\s*;",
        ], html_text)
        or "未知标题"
    )
    author = (
        parser.meta.get("author")
        or parser.meta.get("article:author")
        or parser.meta.get("id:js_name")
        or parser.meta.get("id:profileBt")
        or first_match([
            r"var\s+nickname\s*=\s*['\"](.*?)['\"]\s*;",
            r"author\s*:\s*['\"](.*?)['\"]",
        ], html_text)
    )
    publish_time = (
        parser.meta.get("article:published_time")
        or parser.meta.get("id:publish_time")
    )
    if not publish_time:
        timestamp = first_match([r"var\s+ct\s*=\s*['\"](\d+)['\"]"], html_text)
        if timestamp:
            try:
                publish_time = dt.datetime.fromtimestamp(int(timestamp)).astimezone().isoformat(timespec="minutes")
            except (ValueError, OSError, OverflowError):
                publish_time = timestamp

    return {
        "title": " ".join(title.split()),
        "author": " ".join(author.split()),
        "publish_time": publish_time,
        "body": body,
        "found_content": parser.found_content,
        "image_count": len(re.findall(r"!\[[^\]]*\]\([^\)]+\)", body)),
    }


def make_output_dir(explicit: str | None) -> pathlib.Path:
    if explicit:
        path = pathlib.Path(explicit).expanduser().resolve()
    else:
        run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        path = pathlib.Path(tempfile.gettempdir()) / f"wechat-article-{run_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_self_test() -> int:
    fixture = """<!doctype html><html><head>
<meta property="og:title" content="测试文章">
<meta name="author" content="测试账号">
</head><body><div id="js_content">
<h2>第一节</h2><p>这是<strong>正文</strong>。</p>
<ul><li>项目一</li><li><a href="https://example.com/a">项目二</a></li></ul>
<p><img data-src="https://mmbiz.qpic.cn/test.jpg" alt="示意图"></p>
</div><script>var ct = '1710000000';</script></body></html>"""
    article = parse_article(fixture)
    assert article["title"] == "测试文章"
    assert article["author"] == "测试账号"
    assert article["found_content"] is True
    assert "## 第一节" in article["body"]
    assert "**正文**" in article["body"]
    assert "[项目二](https://example.com/a)" in article["body"]
    assert "mmbiz.qpic.cn/test.jpg" in article["body"]
    assert article["image_count"] == 1
    assert validate_url("https://mp.weixin.qq.com/s/test")
    for bad in (
        "http://mp.weixin.qq.com/s/test",
        "https://mp.weixin.qq.com.evil.test/s/test",
        "https://example.com/?next=mp.weixin.qq.com",
        "https://user:pass@mp.weixin.qq.com/s/test",
    ):
        try:
            validate_url(bad)
        except ValueError:
            continue
        raise AssertionError(f"unsafe URL accepted: {bad}")
    assert looks_like_verification("<title>请进行安全验证</title><p>环境异常，去验证</p>")
    print("wechat-article-reader self-test: OK")
    return 0


def main() -> int:
    argp = argparse.ArgumentParser(description="Read a public WeChat article")
    argp.add_argument("url", nargs="?", help="public https://mp.weixin.qq.com article URL")
    argp.add_argument("--output-dir", help="output directory; defaults to a new temp directory")
    argp.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    argp.add_argument("--quiet", action="store_true")
    argp.add_argument("--print-content", action="store_true")
    argp.add_argument("--self-test", action="store_true")
    args = argp.parse_args()

    if args.self_test:
        return run_self_test()
    if not args.url:
        argp.error("url is required unless --self-test is used")

    try:
        url = validate_url(args.url)
    except (ValueError, urllib.error.URLError) as exc:
        log(f"invalid URL: {exc}", args.quiet)
        return 1

    timeout = max(1, min(args.timeout, MAX_TIMEOUT))
    output_dir = make_output_dir(args.output_dir)
    attempts: list[dict[str, Any]] = []
    selected: FetchResult | None = None
    parsed: dict[str, Any] | None = None
    verification = False

    for profile in ("browser", "wechat-webview"):
        try:
            log(f"GET public article ({profile})", args.quiet)
            result = fetch_once(url, timeout, profile)
            html_text = result.body.decode("utf-8", errors="replace")
            verification = looks_like_verification(html_text)
            candidate = parse_article(html_text) if not verification else None
            useful = bool(
                candidate
                and candidate["found_content"]
                and len(candidate["body"]) >= 80
            )
            attempts.append({
                "profile": profile,
                "status": result.status,
                "bytes": len(result.body),
                "duration_ms": result.duration_ms,
                "redirects": result.redirects,
                "verification_page": verification,
                "found_content": bool(candidate and candidate["found_content"]),
                "content_chars": len(candidate["body"]) if candidate else 0,
            })
            if useful:
                selected = result
                parsed = candidate
                break
        except Exception as exc:  # noqa: BLE001 - error is recorded for the caller
            attempts.append({"profile": profile, "error": str(exc)})

    trace_path = output_dir / "trace.json"
    trace = {
        "version": VERSION,
        "url": url,
        "attempts": attempts,
        "output_dir": str(output_dir),
    }
    write_json(trace_path, trace)

    if not selected or not parsed:
        metadata = {
            "ok": False,
            "url": url,
            "verification_page": verification,
            "error": "verification/login/paywall page or article body unavailable",
            "trace_path": str(trace_path),
        }
        metadata_path = output_dir / "article.json"
        write_json(metadata_path, metadata)
        print(metadata_path)
        log("article unavailable; see trace.json", args.quiet)
        return 3

    raw_path = output_dir / "raw.html"
    raw_path.write_bytes(selected.body)
    body = parsed.pop("body")
    md_lines = [f"# {parsed['title']}", ""]
    if parsed["author"]:
        md_lines.append(f"作者：{parsed['author']}")
    if parsed["publish_time"]:
        md_lines.append(f"发布时间：{parsed['publish_time']}")
    md_lines.extend([f"来源：{url}", "", body, ""])
    markdown = "\n".join(md_lines)
    content_path = output_dir / "article.md"
    content_path.write_text(markdown, encoding="utf-8")

    metadata = {
        "ok": True,
        "version": VERSION,
        "url": url,
        "final_url": selected.final_url,
        "title": parsed["title"],
        "author": parsed["author"],
        "publish_time": parsed["publish_time"],
        "content_chars": len(body),
        "image_count": parsed["image_count"],
        "verification_page": False,
        "request_profile": selected.profile,
        "content_path": str(content_path),
        "raw_path": str(raw_path),
        "trace_path": str(trace_path),
    }
    metadata_path = output_dir / "article.json"
    write_json(metadata_path, metadata)
    print(content_path)
    print(metadata_path)
    log(f"OK: {metadata['title']} ({len(body)} chars)", args.quiet)
    if args.print_content:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
