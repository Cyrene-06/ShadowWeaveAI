"""One explicit, bounded Chat Completions protocol probe; never a quality evaluation."""

import argparse
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from ipaddress import ip_address
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE_BYTES = 256 * 1024


class ProbeReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evidence_ref: Literal["probe-evidence"]
    decision: Literal["uncertain"]


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input_per_million: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$", max_length=32)
    output_per_million: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$", max_length=32)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reference: str = Field(min_length=1, max_length=500)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sha(value):
    return hashlib.sha256(value).hexdigest()


def endpoint(base):
    parsed = urlsplit(base)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid_model_base_url")
    try:
        local = ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = parsed.hostname.lower() == "localhost"
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("https_required_outside_loopback")
    # MODEL_BASE_URL is the API root, usually ending in /v1, not a full method URL.
    if parsed.path.rstrip("/").endswith("/chat/completions"):
        raise ValueError("base_url_must_be_api_root")
    _ = parsed.port  # Reject malformed ports before sending credentials.
    return base.rstrip("/") + "/chat/completions", local


def usage_record(payload):
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if any(type(usage.get(k)) is not int or usage[k] < 0 for k in keys):
        return None
    if usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
        return None
    return {k: usage[k] for k in keys}


def cost_estimate(usage, pricing):
    if usage is None or pricing is None:
        return None
    amount = (
        Decimal(usage["prompt_tokens"]) * Decimal(pricing.input_per_million)
        + Decimal(usage["completion_tokens"]) * Decimal(pricing.output_per_million)
    ) / Decimal(1_000_000)
    return {
        "amount": format(amount, "f"),
        "currency": pricing.currency,
        "basis": "reported_tokens_times_operator_supplied_flat_rates",
        "pricing_reference": pricing.reference,
        "input_per_million": pricing.input_per_million,
        "output_per_million": pricing.output_per_million,
        "is_invoice_or_reported_charge": False,
    }


def probe(environ, *, execute=False, timeout=30, max_output_tokens=256, pricing=None):
    started = time.monotonic()
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "kind": "phase_one_model_protocol_probe",
        "source_kind": "synthetic_metadata",
        "status": "not_configured",
        "request_attempted": False,
        "model_called": False,
        "endpoint_kind": None,
        "http_status": None,
        "structured_result": None,
        "usage": None,
        "usage_status": "not_observed",
        "cost": None,
        "cost_estimate": None,
        "failure_code": None,
        "model_name": None,
        "endpoint_sha256": None,
        "prompt_version": "phase-one-protocol-v1",
        "request_sha256": None,
        "response_sha256": None,
        "max_output_tokens": max_output_tokens,
        "timeout_seconds": timeout,
        "retry_count": 0,
        "limitations": [
            "This probes a declared provider protocol, not model quality or real media understanding.",
            "model_called=null means a request was attempted but inference could not be established.",
            "A loopback test response never counts as a real model call.",
            "cost stays null: an optional flat-rate estimate is not an invoice or actual billed charge.",
        ],
    }
    try:
        names = ("MODEL_PROVIDER", "MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY")
        if not all(environ.get(k) for k in names):
            record["failure_code"] = "missing_provider_configuration"
            return record
        provider, base, model, api_key = (environ[k] for k in names)
        if provider not in ("openai", "openai_compatible"):
            raise ValueError("unsupported_provider_adapter")
        if not 0 < timeout <= 60 or not 16 <= max_output_tokens <= 4096:
            raise ValueError("invalid_request_limits")
        url, local = endpoint(base)
        record.update(
            status="not_run",
            endpoint_kind="loopback_test" if local else "provider",
            model_name=model.replace(api_key, "[REDACTED]"),
            endpoint_sha256=sha(url.encode()),
        )
        if not execute:
            return record
        body = json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Protocol probe with synthetic metadata only. Search for probe-evidence "
                        "is incomplete. Return JSON with evidence_ref=probe-evidence and decision=uncertain. "
                        "Do not infer missing coverage or perform any action.",
                    }
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "phase_one_probe",
                        "strict": True,
                        "schema": ProbeReply.model_json_schema(),
                    },
                },
                "max_completion_tokens": max_output_tokens,
                "stream": False,
                "store": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        record["request_sha256"] = sha(body)
        request = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
            },
            method="POST",
        )
        record.update(status="failed", request_attempted=True, model_called=False if local else None)
        proxy = ProxyHandler({}) if local else ProxyHandler()
        with build_opener(proxy, NoRedirect()).open(request, timeout=timeout) as response:
            record["http_status"] = response.status
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        record["response_sha256"] = sha(raw)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid_completion_envelope")
        # Usage is retained even when the output was refused, truncated or fails local validation.
        record["usage"] = usage_record(payload)
        record["usage_status"] = "provider_reported" if record["usage"] is not None else "missing_or_invalid"
        if local:
            record["usage_status"] = (
                "loopback_fixture" if record["usage"] is not None else "missing_or_invalid"
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("invalid_completion_envelope")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("invalid_completion_envelope")
        record["model_called"] = not local
        # Fixture token counts must not produce a provider cost estimate.
        record["cost_estimate"] = cost_estimate(record["usage"], pricing) if not local else None
        if message.get("refusal"):
            raise ValueError("provider_refusal")
        if choice.get("finish_reason") != "stop":
            raise ValueError("incomplete_completion")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("missing_text_content")
        reply = ProbeReply.model_validate_json(content)
        record.update(status="succeeded", structured_result=reply.model_dump())
    except HTTPError as exc:
        record.update(status="failed", http_status=exc.code, failure_code=f"http_{exc.code}")
        # Do not echo provider error bodies, headers or URLs; they can contain credentials.
        if exc.code in (400, 401, 403, 404, 405, 415, 422, 429):
            record["model_called"] = False
        exc.close()
    except (TimeoutError, socket.timeout):
        record.update(status="timed_out", failure_code="request_timeout")
    except URLError as exc:
        record.update(
            status="timed_out" if isinstance(exc.reason, TimeoutError) else "failed",
            failure_code="request_timeout" if isinstance(exc.reason, TimeoutError) else "transport_error",
        )
    except (OSError, HTTPException):
        record.update(status="failed", failure_code="transport_error")
    except (ValueError, UnicodeError) as exc:
        # Never persist validation exception text, which may include untrusted response content.
        code = str(exc) if type(exc) is ValueError else "invalid_json_or_schema"
        allowed = {
            "invalid_model_base_url",
            "https_required_outside_loopback",
            "base_url_must_be_api_root",
            "unsupported_provider_adapter",
            "invalid_request_limits",
            "response_too_large",
            "invalid_completion_envelope",
            "provider_refusal",
            "incomplete_completion",
            "missing_text_content",
        }
        record.update(status="failed", failure_code=code if code in allowed else "invalid_json_or_schema")
    finally:
        record["duration_seconds"] = round(time.monotonic() - started, 4)
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Send one configured synthetic probe; may incur cost"
    )
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--pricing", type=Path, help="Reviewed flat-rate JSON; produces an estimate only")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/phase-one/model-probe.json")
    args = parser.parse_args()
    try:
        pricing = (
            Pricing.model_validate_json(args.pricing.read_text(encoding="utf-8")) if args.pricing else None
        )
    except (OSError, ValidationError):
        raise SystemExit("Invalid pricing file; no request sent") from None
    record = probe(
        os.environ,
        execute=args.execute,
        timeout=args.timeout,
        max_output_tokens=args.max_output_tokens,
        pricing=pricing,
    )
    record["code"] = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "script_sha256": sha(Path(__file__).read_bytes()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("status", "request_attempted", "model_called", "failure_code")}))
    if args.execute and record["status"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
