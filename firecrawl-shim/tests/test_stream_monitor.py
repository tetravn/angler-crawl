import pytest

from app.llm_stream import _StreamMonitor, StreamAborted


def _mon(json_mode=False, **kw):
    base = dict(json_mode=json_mode, start=0.0, slow_sec_per_word=5.0,
                max_words_no_punct=10, max_chars_no_space=50, max_repeat=4, warmup=3)
    base.update(kw)
    return _StreamMonitor(**base)


def test_no_break_run_aborts():
    m = _mon()
    words = " ".join(f"w{i}" for i in range(12)) + " "   # 12 từ, không dấu câu
    with pytest.raises(StreamAborted):
        m.feed(words, now=0.1)


def test_break_char_resets_run():
    m = _mon()
    m.feed("a b c d e. ", now=0.1)        # có '.', reset
    m.feed("f g h i j. ", now=0.2)        # lại reset → không abort
    # không raise


def test_json_mode_commas_are_breaks():
    m = _mon(json_mode=True, max_words_no_punct=10)
    # 20 "từ" nhưng phân tách bởi dấu phẩy/ngoặc → không vượt no-punct
    js = "".join(f'"k{i}":{i},' for i in range(20))
    m.feed(js, now=0.1)                    # không raise (',{}' là break ở json mode)


def test_json_mode_distinguishes_from_prose():
    # CÙNG input (12 từ ngăn bởi ", " — có space). prose: ',' KHÔNG phải break → vượt
    # no-punct → abort. json: ',' LÀ break → reset → KHÔNG abort. Chứng minh phân biệt mode.
    text = ", ".join(f"w{i}" for i in range(12)) + ", "
    with pytest.raises(StreamAborted):
        _mon(json_mode=False, max_words_no_punct=10).feed(text, now=0.1)
    _mon(json_mode=True, max_words_no_punct=10).feed(text, now=0.1)   # không raise


def test_repetition_aborts():
    m = _mon(max_repeat=4)
    with pytest.raises(StreamAborted):
        m.feed("spam spam spam spam spam ", now=0.1)


def test_no_space_blob_aborts():
    m = _mon(max_chars_no_space=20)
    with pytest.raises(StreamAborted):
        m.feed("x" * 25, now=0.1)


def test_throughput_aborts_when_slow():
    m = _mon(warmup=3, slow_sec_per_word=5.0)
    # 4 từ hoàn chỉnh trong 100s = 25s/word → abort
    with pytest.raises(StreamAborted):
        m.feed("a b c d ", now=100.0)


def test_throughput_ok_when_fast():
    m = _mon(warmup=3, slow_sec_per_word=5.0)
    m.feed("a b c d ", now=2.0)            # 4 từ / 2s = 0.5s/word → ok


def test_below_warmup_no_throughput_abort():
    m = _mon(warmup=10, slow_sec_per_word=5.0)
    m.feed("a b ", now=1000.0)             # chỉ 2 từ < warmup → không xét throughput


# ─── FIX 2 regression: numeric/short tokens không kích hoạt repeat guard ──

def test_numeric_repeat_does_not_abort():
    """Số nguyên (digit) lặp nhiều lần (vd JSON array [1,1,1,...]) KHÔNG bị coi là degeneration."""
    # max_words_no_punct cao để tránh guard no-punct nổ trước; chỉ kiểm repeat guard
    m = _mon(max_repeat=4, max_words_no_punct=500)
    # 20 lần "1 " — digit thuần → không abort
    m.feed("1 " * 20, now=0.1)


def test_short_token_repeat_does_not_abort():
    """Token 2 ký tự (len <= 2) lặp nhiều lần KHÔNG bị coi là degeneration."""
    # max_words_no_punct cao để tránh guard no-punct nổ trước; chỉ kiểm repeat guard
    m = _mon(max_repeat=4, max_words_no_punct=500)
    # "ab" (len=2) lặp 20 lần → không abort
    m.feed("ab " * 20, now=0.1)


