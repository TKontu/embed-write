"""Bounded OpenAI-compatible chat completions (GE-04).

Unwired by design until GE-01/proposal flow. Create a client per session;
remote access requires explicit allow_remote=True on that instance. The trusted
optional transport takes a urllib Request and returns a context-managed binary
response with read(size), allowing offline tests. It owns its network policy.
The default transport disables proxies and redirects, pins localhost to IPv4
loopback, and accepts literal loopback IPv4/IPv6 addresses without DNS lookup.
Unix-domain socket URL schemes are unsupported by stdlib urllib.
"""

import ipaddress
import json
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from generation.run_record import SamplingParams

_RESPONSE_LIMIT = 4 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('LLM endpoint redirects are disabled')


class LLMClient:
    """One POST per completion, with a 30-second socket timeout and 4 MiB cap.

    base_url is the API root (typically http://localhost:8000/v1).
    No retries, model selection or persistent remote opt-in.
    """

    def __init__(self, base_url: str, model: str, *, allow_remote=False, transport=None):
        if not isinstance(base_url, str) or any(c.isspace() or ord(c) < 32 for c in base_url):
            raise ValueError('invalid endpoint URL')
        try:
            parts = urlsplit(base_url)
            host = parts.hostname
            port = parts.port
        except ValueError as exc:
            raise ValueError('invalid endpoint URL') from exc
        if (parts.scheme not in ('http', 'https') or not host
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment or '?' in base_url or '#' in base_url):
            raise ValueError('endpoint must be an HTTP(S) URL without credentials, query or fragment')
        if host == 'localhost':
            host = '127.0.0.1'
        try:
            address = ipaddress.ip_address(host)
            local = address.is_loopback
        except ValueError:
            local = False
        if not local and allow_remote is not True:
            raise ValueError('remote endpoint requires per-session allow_remote=True')
        if not isinstance(model, str) or not model:
            raise ValueError('model must be a non-empty string')
        authority = '[' + host + ']' if ':' in host else host
        if port is not None:
            authority += ':' + str(port)
        self._url = urlunsplit((parts.scheme, authority,
                               parts.path.rstrip('/') + '/chat/completions', '', ''))
        self._model = model
        self._transport = transport

    @property
    def model(self) -> str:
        """The model identifier sent with every request (read-only)."""
        return self._model

    def complete(self, prompt: str, sampling: SamplingParams) -> str:
        """Return first assistant content; malformed/oversized responses raise ValueError.

        HTTP and connection errors propagate from urllib; response bodies are
        never included in errors. Sampling limits beyond JSON validity belong
        to the selected endpoint. Only one bounded response is held in memory.
        """
        if not isinstance(prompt, str):
            raise ValueError('prompt must be a string')
        if not isinstance(sampling, SamplingParams):
            raise ValueError('sampling must be SamplingParams')
        payload = dict(model=self._model, messages=[dict(role='user', content=prompt)],
                       stream=False, **sampling.to_dict())
        request = Request(self._url, json.dumps(payload, allow_nan=False).encode('utf-8'),
                          {'Content-Type': 'application/json'}, method='POST')
        if self._transport is None:
            response = build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=30)
        else:
            response = self._transport(request)
        with response:
            raw = response.read(_RESPONSE_LIMIT + 1)
        if len(raw) > _RESPONSE_LIMIT:
            raise ValueError('LLM response exceeds size limit (4 MiB)')
        try:
            text = json.loads(raw)['choices'][0]['message']['content']
            if not isinstance(text, str):
                raise ValueError('non-text content')
        except (ValueError, UnicodeError, KeyError, IndexError, TypeError, RecursionError) as exc:
            raise ValueError('malformed LLM response: expected choices[0].message.content text') from None
        return text

    def stream(self, prompt: str, sampling: SamplingParams, *, cancel=None):
        """Yield incremental text; unwired by design until GE-03/GE-04 proposal flow.

        A pre-set cancel event sends no request. Cancellation is checked before
        each byte read and yield; it cannot interrupt an in-flight socket read.
        Cancellation, exhaustion, errors and generator.close() close the response.
        Memory is bounded by one 1 MiB line plus caller-held chunks; total wire
        bytes are capped at 4 MiB. No read-ahead past a data line is performed.
        """
        if cancel is not None and cancel.is_set():
            return
        if not isinstance(prompt, str):
            raise ValueError('prompt must be a string')
        if not isinstance(sampling, SamplingParams):
            raise ValueError('sampling must be SamplingParams')
        payload = dict(model=self._model, messages=[dict(role='user', content=prompt)],
                       stream=True, **sampling.to_dict())
        request = Request(self._url, json.dumps(payload, allow_nan=False).encode('utf-8'),
                          {'Content-Type': 'application/json'}, method='POST')
        if self._transport is None:
            response = build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=30)
        else:
            response = self._transport(request)
        with response:
            line = bytearray()
            total = 0
            while True:
                if cancel is not None and cancel.is_set():
                    return
                byte = response.read(1)
                if cancel is not None and cancel.is_set():
                    return
                if not byte:
                    raise ValueError('LLM stream ended without [DONE]')
                total += len(byte)
                if total > _RESPONSE_LIMIT:
                    raise ValueError('LLM response exceeds size limit (4 MiB)')
                if byte != b'\n':
                    line.extend(byte)
                    if len(line) > 1024 * 1024:
                        raise ValueError('LLM stream line exceeds size limit (1 MiB)')
                    continue
                if not line.startswith(b'data:'):
                    line.clear()
                    continue
                data = line[5:].strip()
                line.clear()
                if data == b'[DONE]':
                    return
                try:
                    delta = json.loads(data)['choices'][0]['delta']
                    if not isinstance(delta, dict):
                        raise ValueError('invalid delta')
                    text = delta.get('content', '')
                    if not isinstance(text, str):
                        raise ValueError('non-text content')
                except (ValueError, UnicodeError, KeyError, IndexError, TypeError, RecursionError):
                    raise ValueError('malformed LLM stream: expected delta content text') from None
                if cancel is not None and cancel.is_set():
                    return
                if text:
                    yield text
