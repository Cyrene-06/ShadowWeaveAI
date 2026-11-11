"""Exercise the actual HTTP adapter against loopback fixtures, never a paid model."""

import importlib.util
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("model_probe", ROOT / "scripts/model_probe.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
SECRET = "unit-secret-must-not-be-in-evidence"


def completion(**changes):
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"evidence_ref": "probe-evidence", "decision": "uncertain"}),
                },
            }
        ],
        "usage": {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20},
    }
    payload.update(changes)
    return payload


@pytest.fixture
def server():
    state = {"status": 200, "body": completion(), "requests": [], "headers": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            state["requests"].append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            body = state["body"]
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(state["status"])
            for k, v in state["headers"].items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{httpd.server_port}/v1"
    yield state
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def env(url):
    return {
        "MODEL_PROVIDER": "openai_compatible",
        "MODEL_BASE_URL": url,
        "MODEL_NAME": "fixture-model",
        "MODEL_API_KEY": SECRET,
    }


def test_missing_configuration_and_dry_run_never_send_requests(server):
    assert module.probe({}, execute=True)["status"] == "not_configured"
    result = module.probe(env(server["url"]))
    assert result["status"] == "not_run"
    assert not result["request_attempted"] and not result["model_called"]
    assert not server["requests"]


def test_real_http_request_is_bounded_and_loopback_never_claims_model_execution(server):
    result = module.probe(env(server["url"]), execute=True)
    assert result["status"] == "succeeded"
    assert result["request_attempted"] and result["model_called"] is False
    assert result["usage_status"] == "loopback_fixture"
    assert result["usage"]["total_tokens"] == 20
    assert result["cost"] is None and result["cost_estimate"] is None
    assert result["structured_result"] == {"evidence_ref": "probe-evidence", "decision": "uncertain"}
    (request,) = server["requests"]
    assert request["path"] == "/v1/chat/completions"
    assert request["auth"] == "Bearer " + SECRET
    assert request["body"]["max_completion_tokens"] == 256
    assert request["body"]["store"] is False and request["body"]["stream"] is False
    assert request["body"]["response_format"]["json_schema"]["strict"] is True
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_failures_do_not_retry_or_echo_provider_errors(server, status):
    server.update(status=status, body={"error": SECRET})
    result = module.probe(env(server["url"]), execute=True)
    assert result["status"] == "failed" and result["failure_code"] == f"http_{status}"
    assert result["http_status"] == status and result["retry_count"] == 0
    assert len(server["requests"]) == 1 and SECRET not in json.dumps(result)
    assert result["usage"] is None and result["cost"] is None


def test_redirect_does_not_forward_credentials_or_issue_a_second_request(server):
    server.update(status=307, headers={"Location": server["url"] + "/redirected"})
    result = module.probe(env(server["url"]), execute=True)
    assert result["failure_code"] == "http_307" and len(server["requests"]) == 1


@pytest.mark.parametrize("kind", ["json", "schema", "refusal", "truncated", "envelope", "oversized"])
def test_invalid_structured_results_are_recorded_as_failures(server, kind):
    if kind == "json":
        server["body"] = b"not json " + SECRET.encode()
    elif kind == "schema":
        server["body"]["choices"][0]["message"]["content"] = json.dumps({"decision": SECRET})
    elif kind == "refusal":
        server["body"]["choices"][0]["message"]["refusal"] = SECRET
    elif kind == "truncated":
        server["body"]["choices"][0]["finish_reason"] = "length"
    elif kind == "envelope":
        server["body"] = {"unknown": SECRET}
    else:
        server["body"] = b"x" * (module.MAX_RESPONSE_BYTES + 1)
    result = module.probe(env(server["url"]), execute=True)
    assert result["status"] == "failed" and result["structured_result"] is None
    assert SECRET not in json.dumps(result)
    if kind in ("schema", "refusal", "truncated"):
        assert result["usage"]["total_tokens"] == 20


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/v1",
        "https://user:password@example.test/v1",
        "https://example.test/v1?api_key=secret",
        "https://example.test/v1#secret",
        "https://example.test/v1/chat/completions",
        "https://example.test:bad/v1",
    ],
)
def test_bad_endpoint_configuration_is_rejected_before_network_access(url):
    result = module.probe(env(url), execute=True)
    assert result["status"] == "failed" and result["request_attempted"] is False


def test_pricing_is_explicit_estimate_and_invalid_usage_is_not_zero_cost():
    pricing = module.Pricing(
        input_per_million="2",
        output_per_million="3",
        currency="USD",
        reference="unit tariff, not actual pricing",
    )
    usage = module.usage_record(completion())
    result = module.cost_estimate(usage, pricing)
    assert result["amount"] == "0.000047" and not result["is_invoice_or_reported_charge"]
    assert module.cost_estimate(None, pricing) is None
    assert (
        module.usage_record(
            completion(usage={"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 999})
        )
        is None
    )
    assert (
        module.usage_record(
            completion(usage={"prompt_tokens": True, "completion_tokens": 7, "total_tokens": 8})
        )
        is None
    )


def test_timeout_keeps_request_uncertainty_without_exposing_raw_exception(monkeypatch):
    class TimeoutOpener:
        def open(self, *args, **kwargs):
            raise TimeoutError(SECRET)

    monkeypatch.setattr(module, "build_opener", lambda *args: TimeoutOpener())
    result = module.probe(env("https://provider.example.test/v1"), execute=True)
    assert result["status"] == "timed_out" and result["model_called"] is None
    assert result["request_attempted"] and SECRET not in json.dumps(result)
