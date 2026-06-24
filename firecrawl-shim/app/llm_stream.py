"""Streaming LLM qua LiteLLM + abort guards (chống generation chậm/treo/degenerate).

stream_chat (Task 2): đọc SSE, gom token, cho qua _StreamMonitor. Guard nổ → StreamAborted
(lớp con RuntimeError) → caller xử lý như lỗi LLM thường. Clock tiêm vào feed() để test.
"""
import asyncio
import json
import logging
import time

from .config import (
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_JSON_NATIVE,
    STREAM_STALL_TIMEOUT,
    STREAM_SLOW_SEC_PER_WORD,
    STREAM_MAX_WORDS_NO_PUNCT,
    STREAM_MAX_CHARS_NO_SPACE,
    STREAM_MAX_REPEAT,
    STREAM_WARMUP_WORDS,
)

_now = time.monotonic

log = logging.getLogger("shim.llm_stream")

_PROSE_BREAKS = set(".!?…\n;")
_JSON_EXTRA = set(",{}[]")


class StreamAborted(RuntimeError):
    """Generation bị cắt sớm do guard (chậm/treo/degenerate)."""


class _StreamMonitor:
    """Giám sát stream token, raise StreamAborted khi degenerate/chậm. Clock tiêm qua feed(now)."""

    def __init__(self, *, json_mode: bool, start: float, slow_sec_per_word: float,
                 max_words_no_punct: int, max_chars_no_space: int, max_repeat: int, warmup: int):
        self.start = start
        self.breaks = _PROSE_BREAKS | (_JSON_EXTRA if json_mode else set())
        self.slow = slow_sec_per_word
        self.max_words_no_punct = max_words_no_punct
        self.max_chars_no_space = max_chars_no_space
        self.max_repeat = max_repeat
        self.warmup = warmup
        self.total_words = 0
        self.words_since_break = 0   # đếm từ kể từ ký tự ngắt cuối (tránh split() O(n²))
        self.cur_word = ""      # từ đang ráp giữa các chunk
        self.last_word = None
        self.repeat = 0

    def _complete_word(self, w: str) -> None:
        self.total_words += 1
        self.words_since_break += 1
        if len(w) > 2 and not w.isdigit() and w == self.last_word:
            self.repeat += 1
            if self.repeat >= self.max_repeat:
                raise StreamAborted(f"degeneration: lặp '{w}' x{self.repeat}")
        else:
            self.repeat = 1
            self.last_word = w

    def feed(self, text: str, now: float) -> None:
        for ch in text:
            # no-break run (theo ký tự ngắt tuỳ mode)
            if ch in self.breaks:
                if self.cur_word:
                    self._complete_word(self.cur_word)
                    self.cur_word = ""
                self.words_since_break = 0
            else:
                # ráp từ + no-space blob
                if ch.isspace():
                    if self.cur_word:
                        self._complete_word(self.cur_word)
                        self.cur_word = ""
                else:
                    self.cur_word += ch
                    if len(self.cur_word) > self.max_chars_no_space:
                        raise StreamAborted(
                            f"degeneration: token > {self.max_chars_no_space} ký tự không khoảng trắng")
            if self.words_since_break > self.max_words_no_punct:
                raise StreamAborted(
                    f"degeneration: > {self.max_words_no_punct} từ không ngắt câu")
        # throughput (sau warmup)
        if self.total_words >= self.warmup and self.total_words:
            rate = (now - self.start) / self.total_words
            if rate > self.slow:
                raise StreamAborted(f"quá chậm: {rate:.1f}s/word")


async def stream_chat(messages, *, model=None, temperature=0, json_mode=True,
                      timeout=None, on_token=None) -> str:
    """Stream LLM qua LiteLLM, gom token (cho qua _StreamMonitor + stall guard). Trả full string.

    on_token(delta) (async) được gọi mỗi mảnh token để đẩy ra SSE. Guard nổ → StreamAborted."""
    from .clients import _http, _client_with_timeout   # lazy: tránh circular import
    use_model = model or LLM_MODEL
    if not (LLM_BASE_URL and use_model):
        raise RuntimeError("LLM chưa cấu hình — đặt LLM_BASE_URL + LLM_MODEL (hoặc dùng LiteLLM)")
    body: dict = {"model": use_model, "messages": messages,
                  "temperature": temperature, "stream": True}
    if json_mode and LLM_JSON_NATIVE:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    client = _client_with_timeout(timeout) if timeout else _http()
    mon = _StreamMonitor(json_mode=json_mode, start=_now(),
                         slow_sec_per_word=STREAM_SLOW_SEC_PER_WORD,
                         max_words_no_punct=STREAM_MAX_WORDS_NO_PUNCT,
                         max_chars_no_space=STREAM_MAX_CHARS_NO_SPACE,
                         max_repeat=STREAM_MAX_REPEAT, warmup=STREAM_WARMUP_WORDS)
    buf: list[str] = []
    first = True
    async with client.stream("POST", f"{LLM_BASE_URL}/chat/completions",
                             json=body, headers=headers) as resp:
        resp.raise_for_status()
        backend = resp.headers.get("x-litellm-model-api-base") or "?"
        log.info("LLM stream: group=%s → backend=%s", use_model, backend)
        it = resp.aiter_lines().__aiter__()
        while True:
            try:
                line = await asyncio.wait_for(it.__anext__(), STREAM_STALL_TIMEOUT)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise StreamAborted(f"stall: không có token > {STREAM_STALL_TIMEOUT}s")
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content")
            except Exception:
                continue
            if delta:
                if first:
                    # Đo throughput từ TOKEN ĐẦU, không tính time-to-first-token (model local
                    # eval prompt dài có thể chậm vài chục giây — không phải "sinh chậm").
                    mon.start = _now()
                    first = False
                buf.append(delta)
                mon.feed(delta, _now())
                if on_token is not None:
                    await on_token(delta)
    return "".join(buf)
