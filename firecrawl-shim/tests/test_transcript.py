from app import transcript


def test_is_video_url_youtube():
    assert transcript.is_video_url("https://www.youtube.com/watch?v=abc12345678")
    assert transcript.is_video_url("https://youtu.be/abc12345678")


def test_is_video_url_other_hosts():
    assert transcript.is_video_url("https://vimeo.com/123456")
    assert transcript.is_video_url("https://www.dailymotion.com/video/x123")
    assert transcript.is_video_url("https://www.tiktok.com/@a/video/123")


def test_is_video_url_rejects_plain_page():
    assert not transcript.is_video_url("https://example.com/article")
    assert not transcript.is_video_url("not-a-url")


def test_parse_vtt_strips_timestamps_and_tags():
    vtt = (
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: en\n"
        "\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Hello <c>world</c>\n"
        "\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "Hello <c>world</c>\n"          # trùng dòng trước → dedup liên tiếp
        "\n"
        "00:00:05.000 --> 00:00:07.000\n"
        "Second line\n"
    )
    text, segments = transcript._parse_vtt(vtt)
    assert text == "Hello world\nSecond line"
    assert segments == []


def test_parse_json3_extracts_text_and_segments():
    raw = (
        '{"events":[{"tStartMs":1000,"dDurationMs":2000,"segs":[{"utf8":"Hello "},'
        '{"utf8":"world"}]},{"tStartMs":3000,"dDurationMs":1000,"segs":[{"utf8":"\\n"}]},'
        '{"tStartMs":4000,"dDurationMs":1000,"segs":[{"utf8":"Bye"}]}]}'
    )
    text, segments = transcript._parse_json3(raw)
    assert text == "Hello world\nBye"
    assert segments[0] == {"start": 1.0, "dur": 2.0, "text": "Hello world"}
    assert len(segments) == 2


def test_caption_to_text_dispatch():
    assert transcript._caption_to_text("{}", "json3") == ("", [])
    text, _ = transcript._caption_to_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n", "vtt")
    assert text == "Hi"


def test_lang_matches():
    assert transcript._lang_matches("en", "en")
    assert transcript._lang_matches("en-US", "en")
    assert not transcript._lang_matches("fr", "en")


def test_pick_caption_prefers_manual_in_languages():
    subs = {"fr": [{"ext": "vtt", "url": "u_fr"}], "en": [{"ext": "vtt", "url": "u_en"}]}
    autos = {"en": [{"ext": "vtt", "url": "a_en"}]}
    key, entries = transcript._pick_caption(subs, autos, ["en", "vi"])
    assert key == "en" and entries == subs["en"]


def test_pick_caption_falls_back_to_auto_then_any():
    # Không có manual; có auto trong list
    key, entries = transcript._pick_caption({}, {"vi": [{"ext": "vtt", "url": "a_vi"}]}, ["en", "vi"])
    assert key == "vi"
    # Không có gì trong list → lấy bất kỳ manual
    key2, _ = transcript._pick_caption({"de": [{"ext": "vtt", "url": "u_de"}]}, {}, ["en"])
    assert key2 == "de"
    # Hoàn toàn rỗng
    assert transcript._pick_caption({}, {}, ["en"]) == (None, None)


def test_pick_format_prefers_vtt_then_json3():
    entries = [{"ext": "json3", "url": "j"}, {"ext": "vtt", "url": "v"}]
    assert transcript._pick_format(entries) == ("vtt", "v")
    assert transcript._pick_format([{"ext": "json3", "url": "j"}]) == ("json3", "j")
    assert transcript._pick_format([]) is None


# ─── #1: nhận diện video chính xác (không nuốt trang non-video trên host video) ───
def test_is_video_url_rejects_non_video_on_video_host():
    assert not transcript.is_video_url("https://www.youtube.com/about/")
    assert not transcript.is_video_url("https://www.youtube.com/@NASA")
    assert not transcript.is_video_url("https://www.youtube.com/results?search_query=x")
    assert not transcript.is_video_url("https://vimeo.com/help")


def test_is_video_url_accepts_more_video_patterns():
    assert transcript.is_video_url("https://www.youtube.com/shorts/abc123")
    assert transcript.is_video_url("https://www.youtube.com/embed/abc123")
    assert transcript.is_video_url("https://dai.ly/x7tgad0")


def test_is_video_url_custom_host(monkeypatch):
    monkeypatch.setattr(transcript, "VIDEO_HOSTS", ["tube.example.org"])
    assert transcript.is_video_url("https://tube.example.org/w/abcd")
    assert not transcript.is_video_url("https://other.example.org/w/abcd")


# ─── #2: timeout cho việc lấy transcript ───
def test_ytdlp_opts_has_socket_timeout():
    opts = transcript._ytdlp_opts()
    assert opts["socket_timeout"] == transcript.TRANSCRIPT_TIMEOUT
    assert opts["skip_download"] is True


def test_get_transcript_blocked_when_backends_return_none(monkeypatch):
    import asyncio

    async def none_backend(*a, **k):
        return None

    monkeypatch.setattr(transcript, "_via_youtube_api", none_backend)
    monkeypatch.setattr(transcript, "_via_ytdlp", none_backend)
    result = asyncio.run(transcript.get_transcript("https://youtu.be/abc12345678"))
    assert result == {"text": "", "language": None, "segments": [],
                      "source": "caption", "title": None, "blocked": True}
