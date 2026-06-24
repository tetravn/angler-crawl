"""P8 — Lấy transcript (caption có sẵn) từ video. Caption-only: không ASR/ffmpeg/LLM.

get_transcript() không bao giờ raise vì lỗi mạng/no-caption — trả blocked=true để
nguồn video bị chặn KHÔNG âm thầm tính là "có nội dung" (giống stub-detection của scrape).
"""
import asyncio
import json
import logging
import re
from urllib.parse import urlparse

from . import applog
from .config import TRANSCRIPT_LANGS, TRANSCRIPT_TIMEOUT, VIDEO_HOSTS

log = logging.getLogger("shim.transcript")

# Mẫu URL video THẬT cho các host built-in. Khớp theo MẪU (không chỉ host) để KHÔNG nuốt
# trang kênh/playlist/tìm-kiếm/about trên cùng host (vd youtube.com/@kênh) — những trang đó
# vẫn phải scrape như web bình thường. Site khác: thêm host vào VIDEO_HOSTS (tin mọi URL là
# video) hoặc gọi /v1/transcript trực tiếp.
_VIDEO_URL_PATTERNS = (
    r"youtube\.com/watch\?",
    r"youtube\.com/shorts/",
    r"youtube\.com/embed/",
    r"youtube\.com/live/",
    r"youtu\.be/[\w-]+",
    r"vimeo\.com/\d+",
    r"dailymotion\.com/video/",
    r"dai\.ly/[\w-]+",
    r"tiktok\.com/@[\w.-]+/video/\d+",
    r"twitch\.tv/videos/\d+",
    r"clips\.twitch\.tv/",
)
_VIDEO_URL_RE = re.compile("|".join(_VIDEO_URL_PATTERNS), re.IGNORECASE)


def is_video_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        return False
    # Host do người dùng tự cấu hình (VIDEO_HOSTS, vd PeerTube) → tin: mọi URL là video.
    if any(h in netloc for h in VIDEO_HOSTS):
        return True
    # Host built-in → chỉ nhận đúng MẪU URL video.
    return bool(_VIDEO_URL_RE.search(url))


def _parse_vtt(vtt: str) -> tuple[str, list[dict]]:
    """VTT → plaintext. Bỏ header/timestamp/cue-settings/inline-tag; dedup dòng liên tiếp
    (YouTube auto-caption roll-up lặp dòng rất nhiều)."""
    out: list[str] = []
    last: str | None = None
    for line in vtt.splitlines():
        s = line.strip()
        if not s or "-->" in s or s.isdigit():
            continue
        if s.startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "Kind:", "Language:")):
            continue
        s = re.sub(r"<[^>]+>", "", s).strip()  # bỏ <c>, <00:00:00.000>…
        if not s or s == last:
            continue
        last = s
        out.append(s)
    return "\n".join(out), []


def _parse_json3(raw: str) -> tuple[str, list[dict]]:
    """json3 (YouTube) → (text, segments). Mỗi event là 1 cue; nối các seg.utf8."""
    try:
        data = json.loads(raw)
    except Exception:
        return "", []
    lines: list[str] = []
    segments: list[dict] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text:
            continue
        lines.append(text)
        segments.append({
            "start": ev.get("tStartMs", 0) / 1000.0,
            "dur": ev.get("dDurationMs", 0) / 1000.0,
            "text": text,
        })
    return "\n".join(lines), segments


def _caption_to_text(raw: str, ext: str) -> tuple[str, list[dict]]:
    """Dispatch caption parser by extension (vtt | json3)."""
    if ext == "json3":
        return _parse_json3(raw)
    return _parse_vtt(raw)


_CAPTION_EXTS = ("vtt", "json3", "srv3", "srv1", "ttml")


def _lang_matches(key: str, lang: str) -> bool:
    """Kiểm tra xem lang_key có khớp với lang không (exact hoặc variant).

    Ví dụ: "en-US" khớp "en"; "en" khớp "en"; "fr" không khớp "en".
    """
    k, l = key.lower(), lang.lower()
    return k == l or k.startswith(l + "-")


def _pick_caption(
    subtitles: dict, automatic: dict, languages: list[str]
) -> tuple[str | None, list[dict] | None]:
    """Ưu tiên: manual trong list → auto trong list → manual bất kỳ → auto bất kỳ.

    Trả về (language_key, caption_entries) hoặc (None, None) nếu không có gì.
    """
    for lang in languages:
        for key, entries in subtitles.items():
            if _lang_matches(key, lang):
                return key, entries
    for lang in languages:
        for key, entries in automatic.items():
            if _lang_matches(key, lang):
                return key, entries
    if subtitles:
        key = next(iter(subtitles))
        return key, subtitles[key]
    if automatic:
        key = next(iter(automatic))
        return key, automatic[key]
    return None, None


def _pick_format(entries: list[dict]) -> tuple[str, str] | None:
    """Chọn (ext, url) caption: ưu tiên vtt → json3 → còn lại.

    Trả về (ext, url) hoặc None nếu không có entry nào có url.
    """
    for ext in _CAPTION_EXTS:
        for e in entries:
            if e.get("ext") == ext and e.get("url"):
                return ext, e["url"]
    for e in entries:
        if e.get("url"):
            return e.get("ext", ""), e["url"]
    return None


_YT_ID = re.compile(r"(?:v=|/shorts/|/embed/|youtu\.be/)([A-Za-z0-9_-]{11})")


def _is_youtube(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "youtube.com" in netloc or "youtu.be" in netloc


def _youtube_id(url: str) -> str | None:
    m = _YT_ID.search(url)
    return m.group(1) if m else None


def _yt_api_fetch(video_id: str, languages: list[str], proxy: str | None = None):
    """Sync — chạy trong to_thread. Trả (language_code, list[{text,start,duration}]) hoặc None."""
    from youtube_transcript_api import YouTubeTranscriptApi

    proxies = {"http": proxy, "https": proxy} if proxy else None
    tlist = YouTubeTranscriptApi.list_transcripts(video_id, proxies=proxies)
    transcript_obj = None
    try:
        transcript_obj = tlist.find_manually_created_transcript(languages)
    except Exception:
        pass
    if transcript_obj is None:
        try:
            transcript_obj = tlist.find_generated_transcript(languages)
        except Exception:
            pass
    if transcript_obj is None:
        for t in tlist:  # bất kỳ caption nào còn lại
            transcript_obj = t
            break
    if transcript_obj is None:
        return None
    return transcript_obj.language_code, transcript_obj.fetch()


async def _via_youtube_api(url: str, languages: list[str], proxy: str | None = None) -> dict | None:
    vid = _youtube_id(url)
    if not vid:
        return None
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(_yt_api_fetch, vid, languages, proxy), TRANSCRIPT_TIMEOUT
        )
    except Exception as exc:
        log.info("youtube-transcript-api lỗi %s: %s", url, exc)
        applog.event("transcript", "youtube-transcript-api lỗi", url=url, error=str(exc))
        return None
    if not res:
        return None
    lang, entries = res
    lines: list[str] = []
    segments: list[dict] = []
    last: str | None = None
    for e in entries:
        txt = (e.get("text") or "").strip()
        if not txt or txt == last:
            continue
        last = txt
        lines.append(txt)
        segments.append({"start": e.get("start", 0.0), "dur": e.get("duration", 0.0), "text": txt})
    text = "\n".join(lines)
    if not text:
        return None
    applog.event("transcript", "transcript qua youtube-api", url=url, language=lang)
    return {"text": text, "language": lang, "segments": segments,
            "source": "caption", "title": None, "blocked": False}


def _ytdlp_opts() -> dict:
    """Opts cho yt-dlp: caption-only (không tải video) + socket_timeout chặn treo mạng."""
    return {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": TRANSCRIPT_TIMEOUT,
    }


def _ytdlp_extract(url: str, proxy: str | None = None) -> dict:
    """Sync — chạy trong to_thread. extract_info không tải video (caption-only)."""
    import yt_dlp

    opts = _ytdlp_opts()
    if proxy:
        opts["proxy"] = proxy
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


async def _via_ytdlp(url: str, languages: list[str], proxy: str | None = None) -> dict | None:
    try:
        # wait_for: trần thời gian cứng để không kẹt request nếu yt-dlp treo.
        info = await asyncio.wait_for(
            asyncio.to_thread(_ytdlp_extract, url, proxy), TRANSCRIPT_TIMEOUT
        )
    except Exception as exc:
        log.info("yt-dlp lỗi %s: %s", url, exc)
        applog.event("transcript", "yt-dlp lỗi", url=url, error=str(exc))
        return None
    if not info:
        return None
    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    lang, entries = _pick_caption(subs, autos, languages)
    if not entries:
        return None
    picked = _pick_format(entries)
    if not picked:
        return None
    ext, cap_url = picked
    from . import clients  # lazy — tránh import httpx khi module load
    raw = await clients.http_get_text(cap_url, proxy=proxy)
    if not raw:
        return None
    text, segments = _caption_to_text(raw, ext)
    if not text:
        return None
    applog.event("transcript", "transcript qua yt-dlp", url=url, language=lang)
    return {"text": text, "language": lang, "segments": segments,
            "source": "caption", "title": info.get("title"), "blocked": False}


async def get_transcript(url: str, *, languages: list[str] | None = None,
                         proxy: str | None = None) -> dict:
    """Lấy caption: YouTube → youtube-transcript-api trước, fallback yt-dlp; site khác → yt-dlp.
    Không có caption nào → blocked=true (không raise)."""
    langs = languages or TRANSCRIPT_LANGS
    result: dict | None = None
    if _is_youtube(url):
        result = await _via_youtube_api(url, langs, proxy)
    if result is None:
        result = await _via_ytdlp(url, langs, proxy)
    if result is None:
        applog.event("transcript", "transcript blocked (không có caption)", url=url)
        return {"text": "", "language": None, "segments": [],
                "source": "caption", "title": None, "blocked": True}
    return result
