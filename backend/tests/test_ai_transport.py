"""The AI providers driven over a real socket.

Every other test of the AI layer substitutes a stub object for the provider,
which proves the verification logic but never exercises the part that talks to a
model: the URL, the auth headers, the request body, the response shape, and what
happens when the far end misbehaves.

These tests run a real HTTP server on localhost speaking the Anthropic and
OpenAI wire formats, so the provider code makes genuine requests. What that
cannot cover is a live vendor endpoint - a contract change at Anthropic or
OpenAI would not fail these. It covers everything up to the network.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.engines.ai_provider import (
    AnthropicProvider,
    DeterministicProvider,
    OpenAICompatibleProvider,
    narrate,
)

# Set by each test before a request arrives; read by the handler.
_RESPONSE: dict = {}
_REQUESTS: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's own name
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode()
        _REQUESTS.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(raw) if raw else {},
        })
        status = _RESPONSE.get("status", 200)
        body = _RESPONSE.get("body", "")
        payload = body if isinstance(body, (str, bytes)) else json.dumps(body)
        encoded = payload.encode() if isinstance(payload, str) else payload
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args) -> None:
        """Silence the default stderr logging."""


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _reset():
    _RESPONSE.clear()
    _REQUESTS.clear()


def _anthropic(server: str, timeout: int = 10) -> AnthropicProvider:
    return AnthropicProvider("test-key-123", "claude-test", server, timeout)


def _openai(server: str, timeout: int = 10) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider("sk-test-123", "gpt-test", server, timeout)


# --- Anthropic wire format --------------------------------------------------

def test_anthropic_sends_a_well_formed_request(server):
    _RESPONSE.update(body={"content": [{"type": "text", "text": "Revenue grew 18.4%."}]})
    result = _anthropic(server).complete("Rewrite this", max_tokens=256)

    assert result == "Revenue grew 18.4%."
    request = _REQUESTS[0]
    assert request["path"] == "/v1/messages"
    assert request["headers"]["x-api-key"] == "test-key-123"
    assert request["headers"]["anthropic-version"] == "2023-06-01"
    assert request["body"]["model"] == "claude-test"
    assert request["body"]["max_tokens"] == 256
    assert request["body"]["system"]
    assert request["body"]["messages"] == [{"role": "user", "content": "Rewrite this"}]


def test_anthropic_joins_text_blocks_and_ignores_others(server):
    _RESPONSE.update(body={"content": [
        {"type": "text", "text": "One. "},
        {"type": "tool_use", "name": "ignored", "input": {}},
        {"type": "text", "text": "Two."},
    ]})
    assert _anthropic(server).complete("x") == "One. Two."


def test_anthropic_without_a_key_makes_no_request(server):
    assert AnthropicProvider("", "claude-test", server, 10).complete("x") == ""
    assert _REQUESTS == []


# --- OpenAI wire format -----------------------------------------------------

def test_openai_sends_a_well_formed_request(server):
    _RESPONSE.update(body={"choices": [{"message": {"content": "Revenue grew 18.4%."}}]})
    result = _openai(server).complete("Rewrite this", max_tokens=128)

    assert result == "Revenue grew 18.4%."
    request = _REQUESTS[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["authorization"] == "Bearer sk-test-123"
    assert request["body"]["model"] == "gpt-test"
    roles = [m["role"] for m in request["body"]["messages"]]
    assert roles == ["system", "user"]


def test_openai_without_a_key_makes_no_request(server):
    assert OpenAICompatibleProvider("", "gpt-test", server, 10).complete("x") == ""
    assert _REQUESTS == []


# --- when the far end misbehaves --------------------------------------------
# Every one of these must degrade to the engine's own wording. An analysis must
# never fail because a third-party model did.

@pytest.mark.parametrize("provider_factory", [_anthropic, _openai])
@pytest.mark.parametrize("response", [
    {"status": 500, "body": {"error": "internal"}},
    {"status": 429, "body": {"error": "rate limited"}},
    {"status": 200, "body": "this is not json"},
    {"status": 200, "body": {"unexpected": "shape"}},
    {"status": 401, "body": {"error": "bad key"}},
])
def test_a_misbehaving_endpoint_yields_empty_not_an_exception(server, provider_factory, response):
    _RESPONSE.update(response)
    assert provider_factory(server).complete("x") == ""


@pytest.mark.parametrize("provider_factory", [_anthropic, _openai])
def test_an_unreachable_endpoint_yields_empty(provider_factory):
    # Port 1 is reserved and nothing listens on it.
    assert provider_factory("http://127.0.0.1:1").complete("x") == ""


# --- narration over the wire ------------------------------------------------

FACTS = {"revenue_growth_pct": 18.4, "revenue_total": 12_500_000}
BASELINE = "Revenue grew 18.4% to 12.5M."


def test_a_faithful_rephrase_is_used(server):
    _RESPONSE.update(body={"content": [
        {"type": "text", "text": "Revenue rose 18.4%, reaching 12.5M over the period."},
    ]})
    result = narrate("Rewrite", FACTS, BASELINE, provider=_anthropic(server))
    assert result["source"] == "anthropic"
    assert "18.4" in result["text"]
    assert result["rejected"] == []


def test_a_fabricated_figure_is_rejected_over_the_wire(server):
    """The promise the whole product rests on, exercised through real HTTP."""
    _RESPONSE.update(body={"content": [
        {"type": "text", "text": "Revenue exploded 412% to 88 million."},
    ]})
    result = narrate("Rewrite", FACTS, BASELINE, provider=_anthropic(server))

    assert result["text"] == BASELINE
    assert result["source"] == "deterministic"
    assert any("412" in figure for figure in result["rejected"])
    assert "do not appear in the calculated results" in result["rejection_reason"]


def test_an_outage_falls_back_to_the_engines_wording(server):
    _RESPONSE.update(status=503, body={"error": "unavailable"})
    result = narrate("Rewrite", FACTS, BASELINE, provider=_anthropic(server))
    assert result["text"] == BASELINE
    assert result["source"] == "deterministic"


def test_no_raw_rows_are_sent(server):
    """Only aggregates reach the model - asserted on the bytes actually sent."""
    _RESPONSE.update(body={"content": [{"type": "text", "text": BASELINE}]})
    narrate("Rewrite", FACTS, BASELINE, provider=_anthropic(server))

    sent = json.dumps(_REQUESTS[0]["body"])
    assert "revenue_growth_pct" in sent          # the aggregate did go
    assert "FACTS" in sent and "BASELINE" in sent
    # The facts block is the only data channel; nothing row-shaped rides along.
    assert "Order ID" not in sent
    assert "ORD0" not in sent


def test_the_deterministic_provider_never_opens_a_socket(server):
    result = narrate("Rewrite", FACTS, BASELINE, provider=DeterministicProvider())
    assert result["text"] == BASELINE
    assert result["source"] == "deterministic"
    assert _REQUESTS == []
