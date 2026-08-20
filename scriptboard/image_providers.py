"""Provider-neutral storyboard image generation backends."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Protocol
from urllib import error, request
import zlib


DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
DEFAULT_OPENAI_IMAGE_SIZE = "1536x1024"
DEFAULT_OPENAI_IMAGE_QUALITY = "medium"
DEFAULT_OPENAI_IMAGE_FORMAT = "png"
READY_PROMPT_REVISION_STATUS = "ready"
PROMPT_REVISION_SCHEMA_VERSION = 1
SAFE_REQUEST_METADATA_KEYS = {
    "provider",
    "job_id",
    "prompt_hash",
    "model",
    "n",
    "size",
    "quality",
    "output_format",
}
SENSITIVE_TEXT_MARKERS = (
    "api_key",
    "authorization",
    "bearer ",
    "secret",
    "signed_url",
    "sk-",
    "http://",
    "https://",
)


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce an image for a panel job."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str | None = None,
        error_code: str | None = None,
        http_status: int | None = None,
        request_id: str | None = None,
        persist_message: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.error_code = error_code
        self.http_status = http_status
        self.request_id = request_id
        self.persist_message = persist_message


@dataclass(frozen=True)
class GenerationResult:
    provider: str
    model: str
    image_bytes: bytes
    request_metadata: dict[str, Any]
    provider_job_id: str | None = None
    output_format: str = "png"
    seed: int | None = None
    cost_estimate: str | None = None
    notes: str = ""


class ImageProvider(Protocol):
    name: str
    model: str

    def generate(self, job: dict[str, Any]) -> GenerationResult:
        """Generate one storyboard panel image for a pending job."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)) and all(item is None or isinstance(item, (str, int, float, bool)) for item in value):
        return list(value)
    return None


def sanitize_metadata_value(value: Any, *, sensitive_values: list[str], fallback: str) -> Any:
    if isinstance(value, str):
        return safe_provider_text(value, sensitive_values=sensitive_values, fallback=fallback)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        safe_items = []
        for item in value:
            if isinstance(item, str):
                safe_items.append(safe_provider_text(item, sensitive_values=sensitive_values, fallback=fallback))
            elif isinstance(item, (int, float, bool)) or item is None:
                safe_items.append(item)
            else:
                return None
        return safe_items
    return None


def sanitize_request_metadata(metadata: dict[str, Any], *, sensitive_values: list[str]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if key_text not in SAFE_REQUEST_METADATA_KEYS:
            continue
        if safe_scalar(value) is None:
            continue
        safe_value = sanitize_metadata_value(
            value,
            sensitive_values=sensitive_values,
            fallback=f"{key_text}_redacted",
        )
        if safe_value is not None:
            safe[key_text] = safe_value
    return safe


def sensitive_values_for_job(*jobs: dict[str, Any]) -> list[str]:
    values = []
    for job in jobs:
        for key in ("prompt", "script_passage"):
            value = str(job.get(key) or "").strip()
            if len(value) >= 16:
                values.append(value)
    return values


def sensitive_values_for_provider(provider: ImageProvider) -> list[str]:
    values = []
    for attr in ("api_key",):
        value = str(getattr(provider, attr, "") or "").strip()
        if len(value) >= 8:
            values.append(value)
    return values


def safe_provider_text(value: Any, *, sensitive_values: list[str], fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lower = text.lower()
    if any(marker in lower for marker in SENSITIVE_TEXT_MARKERS):
        return fallback
    if any(secret and secret in text for secret in sensitive_values):
        return fallback
    return text


def provider_error_details(provider: ImageProvider, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ProviderError):
        details: dict[str, Any] = {
            "message": str(exc) if exc.persist_message else f"Provider {provider.name} failed",
            "error_type": exc.error_type or exc.__class__.__name__,
        }
        if exc.error_code:
            details["error_code"] = exc.error_code
        if exc.http_status:
            details["http_status"] = exc.http_status
        if exc.request_id:
            details["request_id"] = exc.request_id
        return details
    return {
        "message": f"Provider {provider.name} failed",
        "error_type": exc.__class__.__name__,
    }


def sanitize_error_details(details: dict[str, Any], *, sensitive_values: list[str]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in ("message", "error_type", "error_code", "request_id"):
        value = details.get(key)
        if value:
            safe[key] = safe_provider_text(
                value,
                sensitive_values=sensitive_values,
                fallback=f"{key}_redacted",
            )
    if details.get("http_status"):
        http_status = details["http_status"]
        if type(http_status) is int:
            safe["http_status"] = http_status
    return safe


def prompt_text_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        len(data).to_bytes(4, "big")
        + kind
        + data
        + zlib.crc32(kind + data).to_bytes(4, "big")
    )


def fake_png(label: str) -> bytes:
    text = f"scriptboard\x00{label}".encode("utf-8", errors="replace")
    raw_pixel = b"\x00\x25\x4a\x70"
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"),
            png_chunk(b"tEXt", text),
            png_chunk(b"IDAT", zlib.compress(raw_pixel)),
            png_chunk(b"IEND", b""),
        ]
    )


class FakeImageProvider:
    """Deterministic test provider that writes tiny PNG fixtures."""

    name = "fake"
    model = "fake-image-provider"

    def __init__(self, fail_job_ids: set[str] | None = None) -> None:
        self.fail_job_ids = fail_job_ids or set()

    def generate(self, job: dict[str, Any]) -> GenerationResult:
        job_id = str(job.get("id") or "")
        if job_id in self.fail_job_ids:
            raise ProviderError(f"Fake provider failure for {job_id}")
        prompt_hash = str(job.get("prompt_hash") or "")
        return GenerationResult(
            provider=self.name,
            model=self.model,
            image_bytes=fake_png(f"{job_id}:{prompt_hash}"),
            request_metadata={
                "provider": self.name,
                "job_id": job_id,
                "prompt_hash": prompt_hash,
            },
            provider_job_id=f"fake-{job_id}",
            notes="Generated by ScriptBoard fake provider for deterministic tests.",
        )


class OpenAIImageProvider:
    """OpenAI Image API provider for prompt-to-local-image generation."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_OPENAI_IMAGE_MODEL,
        size: str = DEFAULT_OPENAI_IMAGE_SIZE,
        quality: str = DEFAULT_OPENAI_IMAGE_QUALITY,
        output_format: str = DEFAULT_OPENAI_IMAGE_FORMAT,
        timeout_s: int = 180,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.size = size
        self.quality = quality
        self.output_format = output_format
        self.timeout_s = timeout_s

    def request_payload(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt": str(job.get("prompt") or ""),
            "n": 1,
            "size": self.size,
            "quality": self.quality,
            "output_format": self.output_format,
        }

    def generate(self, job: dict[str, Any]) -> GenerationResult:
        if not self.api_key:
            raise ProviderError(
                "OPENAI_API_KEY is required for provider 'openai'",
                error_type="missing_api_key",
                persist_message=True,
            )
        sensitive_values = sensitive_values_for_job(job)
        sensitive_values.extend(sensitive_values_for_provider(self))
        payload = self.request_payload(job)
        request_metadata = {key: value for key, value in payload.items() if key != "prompt"}
        request_metadata["prompt_hash"] = str(job.get("prompt_hash") or sha256_bytes(payload["prompt"].encode("utf-8")))
        req = request.Request(
            "https://api.openai.com/v1/images/generations",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                try:
                    body = json.loads(response.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderError(
                        "OpenAI Image API response was not valid JSON",
                        error_type="malformed_response",
                        persist_message=True,
                    ) from exc
                request_id = response.headers.get("x-request-id")
        except error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            finally:
                exc.close()
            error_type = None
            error_code = None
            try:
                error_payload = json.loads(detail).get("error") or {}
                error_type = safe_provider_text(
                    error_payload.get("type"),
                    sensitive_values=sensitive_values,
                    fallback="provider_error",
                )
                error_code = safe_provider_text(
                    error_payload.get("code"),
                    sensitive_values=sensitive_values,
                    fallback="provider_error",
                )
            except (json.JSONDecodeError, AttributeError):
                pass
            suffix = f": {error_code or error_type}" if error_code or error_type else ""
            request_id = safe_provider_text(
                exc.headers.get("x-request-id") if exc.headers else None,
                sensitive_values=sensitive_values,
                fallback="request_id_redacted",
            )
            raise ProviderError(
                f"OpenAI Image API failed with HTTP {exc.code}{suffix}",
                error_type=error_type or "http_error",
                error_code=error_code or None,
                http_status=exc.code,
                request_id=request_id or None,
                persist_message=True,
            ) from exc
        except error.URLError as exc:
            raise ProviderError(
                "OpenAI Image API request failed",
                error_type="network_error",
                persist_message=True,
            ) from exc
        try:
            encoded = body["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "OpenAI Image API response did not include data[0].b64_json",
                error_type="missing_image_data",
                persist_message=True,
            ) from exc
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ProviderError(
                "OpenAI Image API response included invalid base64 image data",
                error_type="invalid_image_data",
                persist_message=True,
            ) from exc
        return GenerationResult(
            provider=self.name,
            model=self.model,
            image_bytes=image_bytes,
            request_metadata=request_metadata,
            provider_job_id=request_id,
            output_format=self.output_format,
            notes="Generated by OpenAI Image API; image bytes decoded from data[0].b64_json.",
        )


def make_provider(
    name: str,
    *,
    model: str | None = None,
    size: str = DEFAULT_OPENAI_IMAGE_SIZE,
    quality: str = DEFAULT_OPENAI_IMAGE_QUALITY,
    output_format: str = DEFAULT_OPENAI_IMAGE_FORMAT,
) -> ImageProvider:
    if name == "fake":
        return FakeImageProvider()
    if name == "openai":
        return OpenAIImageProvider(
            model=model or DEFAULT_OPENAI_IMAGE_MODEL,
            size=size,
            quality=quality,
            output_format=output_format,
        )
    raise ValueError(f"Unknown image provider: {name}")


def load_ledger(ledger_path: Path) -> dict[str, Any]:
    return json.loads(ledger_path.read_text(encoding="utf-8"))


def prompt_revision_entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ProviderError("Prompt revision file must be a JSON object")
    if raw.get("schema_version") != PROMPT_REVISION_SCHEMA_VERSION:
        raise ProviderError(f"Prompt revision schema_version must be {PROMPT_REVISION_SCHEMA_VERSION}")
    entries = raw.get("revisions", [])
    if not isinstance(entries, list):
        raise ProviderError("Prompt revision file must contain a revisions list")

    revisions: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ProviderError(f"Prompt revision entry {index} must be an object")
        for field in ("job_id", "status", "source_prompt_hash", "revised_prompt"):
            if field not in entry or not isinstance(entry[field], str):
                raise ProviderError(f"Prompt revision entry {index} must include string field {field}")
        job_id = entry["job_id"].strip()
        if not job_id:
            raise ProviderError(f"Prompt revision entry {index} is missing job_id")
        if not entry["status"].strip():
            raise ProviderError(f"Prompt revision entry {index} is missing status")
        if not entry["source_prompt_hash"].strip():
            raise ProviderError(f"Prompt revision entry {index} is missing source_prompt_hash")
        if job_id in revisions:
            raise ProviderError(f"Duplicate prompt revision for job_id {job_id}")
        revisions[job_id] = entry
    return entries


def load_prompt_revisions(revisions_path: Path | None) -> dict[str, dict[str, Any]]:
    if revisions_path is None:
        return {}
    raw = json.loads(revisions_path.read_text(encoding="utf-8"))
    entries = prompt_revision_entries(raw)
    revisions: dict[str, dict[str, Any]] = {}
    for entry in entries:
        revisions[entry["job_id"].strip()] = entry
    return revisions


def save_ledger(ledger_path: Path, raw: dict[str, Any]) -> None:
    refresh_summary(raw)
    raw["generated_at"] = utc_now()
    ledger_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def recover_existing_outputs(raw: dict[str, Any]) -> int:
    recovered = 0
    for job in raw.get("jobs", []):
        image_path = job_image_path(job)
        if job.get("status") == "done" or not image_path.exists():
            continue
        image_bytes = image_path.read_bytes()
        completed_at = utc_now()
        job["status"] = "done"
        job["output_path"] = str(image_path)
        job["updated_at"] = completed_at
        job["notes"] = "Recovered existing image output without regenerating."
        provider = dict(job.get("provider") or {})
        provider.setdefault("provider", "recovered")
        provider.setdefault("model", None)
        provider["status"] = "done"
        provider["completed_at"] = completed_at
        provider["checksum_sha256"] = sha256_bytes(image_bytes)
        provider["output_path"] = str(image_path)
        job["provider"] = provider
        recovered += 1
    return recovered


def refresh_summary(raw: dict[str, Any]) -> None:
    jobs = list(raw.get("jobs", []))
    done = sum(1 for job in jobs if job.get("status") == "done" and Path(str(job.get("image_path") or "")).exists())
    failed = sum(1 for job in jobs if job.get("status") == "failed")
    raw["summary"] = {
        "total": len(jobs),
        "pending": len(jobs) - done - failed,
        "done": done,
        "failed": failed,
    }


def job_image_path(job: dict[str, Any]) -> Path:
    return Path(str(job.get("image_path") or ""))


def prompt_revision_review(
    job: dict[str, Any],
    *,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not prompt_revisions:
        return None
    job_id = str(job.get("id") or "")
    revision = prompt_revisions.get(job_id)
    if revision is None:
        return None

    status = str(revision.get("status") or "").strip().lower()
    source_hash = str(revision.get("source_prompt_hash") or "").strip()
    current_hash = str(job.get("prompt_hash") or "").strip()
    revised_prompt = str(revision.get("revised_prompt") or "")
    revised_hash = None
    blocker = ""

    if status != READY_PROMPT_REVISION_STATUS:
        blocker = "prompt revision is not ready"
    elif not source_hash:
        blocker = "prompt revision is missing source_prompt_hash"
    elif source_hash != current_hash:
        blocker = "prompt revision source_prompt_hash does not match job prompt_hash"
    elif not revised_prompt.strip():
        blocker = "prompt revision is ready but revised_prompt is empty"
    else:
        revised_hash = prompt_text_hash(revised_prompt)

    return {
        "status": status or None,
        "source_prompt_hash": source_hash or None,
        "current_prompt_hash": current_hash or None,
        "revised_prompt_hash": revised_hash,
        "applies": not blocker,
        "blocker": blocker or None,
    }


def prompt_revision_metadata(review: dict[str, Any] | None) -> dict[str, Any] | None:
    if not review:
        return None
    return {
        "status": review.get("status"),
        "source_prompt_hash": review.get("source_prompt_hash"),
        "revised_prompt_hash": review.get("revised_prompt_hash"),
    }


def find_job(raw: dict[str, Any], job_id: str) -> dict[str, Any]:
    for job in raw.get("jobs", []):
        if job.get("id") == job_id:
            return job
    raise ProviderError(f"Job id not found: {job_id}")


def prompt_revision_document(revisions_path: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    if not revisions_path.exists():
        if allow_missing:
            return {"schema_version": PROMPT_REVISION_SCHEMA_VERSION, "revisions": []}
        raise ProviderError(f"Prompt revision file not found: {revisions_path}")
    raw = json.loads(revisions_path.read_text(encoding="utf-8"))
    prompt_revision_entries(raw)
    return raw


def save_prompt_revision_document(revisions_path: Path, raw: dict[str, Any]) -> None:
    prompt_revision_entries(raw)
    revisions_path.parent.mkdir(parents=True, exist_ok=True)
    revisions_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def revision_review_item(
    job: dict[str, Any],
    revision: dict[str, Any],
) -> dict[str, Any]:
    review = prompt_revision_review(job, prompt_revisions={str(job.get("id") or ""): revision})
    image_path = job_image_path(job)
    return {
        "job_id": job.get("id"),
        "status": revision.get("status"),
        "source_prompt_hash": revision.get("source_prompt_hash"),
        "current_prompt_hash": job.get("prompt_hash"),
        "revised_prompt_hash": review.get("revised_prompt_hash") if review else None,
        "applies": bool(review and review.get("applies")),
        "blocker": review.get("blocker") if review else None,
        "image_path": str(image_path),
        "image_exists": image_path.exists(),
    }


def scaffold_prompt_revision(
    ledger_path: Path,
    revisions_path: Path,
    *,
    job_id: str,
    status: str | None = None,
    revised_prompt: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    raw = load_ledger(ledger_path)
    job = find_job(raw, job_id)
    document = prompt_revision_document(revisions_path, allow_missing=True)
    entries = document["revisions"]
    existing_index = None
    for index, entry in enumerate(entries):
        if entry.get("job_id") == job_id:
            existing_index = index
            break
    if existing_index is not None and not replace:
        raise ProviderError(f"Prompt revision already exists for job_id {job_id}; pass --replace to update it")

    existing = entries[existing_index] if existing_index is not None else {}
    next_status = status or str(existing.get("status") or "draft")
    next_prompt = revised_prompt if revised_prompt is not None else str(existing.get("revised_prompt") or "")
    if next_status == READY_PROMPT_REVISION_STATUS and not next_prompt.strip():
        raise ProviderError("Ready prompt revisions require a non-empty --revised-prompt-file")

    revision = {
        "job_id": job_id,
        "status": next_status,
        "source_prompt_hash": str(job.get("prompt_hash") or ""),
        "revised_prompt": next_prompt,
    }
    if existing_index is None:
        entries.append(revision)
        action = "created"
    else:
        entries[existing_index] = revision
        action = "updated"
    save_prompt_revision_document(revisions_path, document)
    item = revision_review_item(job, revision)
    return {
        "action": action,
        "revision": item,
    }


def validate_prompt_revision_file(
    ledger_path: Path,
    revisions_path: Path,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    raw = load_ledger(ledger_path)
    document = prompt_revision_document(revisions_path)
    entries = prompt_revision_entries(document)
    jobs_by_id = {str(job.get("id") or ""): job for job in raw.get("jobs", [])}
    revisions = []
    for entry in entries:
        entry_job_id = entry["job_id"].strip()
        if job_id and entry_job_id != job_id:
            continue
        job = jobs_by_id.get(entry_job_id)
        if not job:
            revisions.append(
                {
                    "job_id": entry_job_id,
                    "status": entry.get("status"),
                    "source_prompt_hash": entry.get("source_prompt_hash"),
                    "current_prompt_hash": None,
                    "revised_prompt_hash": None,
                    "applies": False,
                    "blocker": "job id is not present in ledger",
                    "image_path": None,
                    "image_exists": False,
                }
            )
            continue
        revisions.append(revision_review_item(job, entry))
    if job_id and not revisions:
        raise ProviderError(f"Prompt revision not found for job_id {job_id}")
    summary = {
        "total": len(revisions),
        "ready": sum(1 for item in revisions if item.get("status") == READY_PROMPT_REVISION_STATUS),
        "draft": sum(1 for item in revisions if item.get("status") == "draft"),
        "applies": sum(1 for item in revisions if item.get("applies")),
        "blocked": sum(1 for item in revisions if item.get("blocker")),
        "missing_job": sum(1 for item in revisions if item.get("blocker") == "job id is not present in ledger"),
    }
    return {
        "schema_version": PROMPT_REVISION_SCHEMA_VERSION,
        "summary": summary,
        "revisions": revisions,
    }


def job_selection_blockers(
    job: dict[str, Any],
    *,
    retry_failed: bool = False,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    blockers = []
    image_path = job_image_path(job)
    if job.get("status") == "done" and image_path.exists():
        blockers.append("job is already done and its image file exists")
    if job.get("status") == "failed" and not retry_failed:
        blockers.append("job is failed; pass --retry-failed to select it")
    if image_path.exists():
        blockers.append("image file already exists")
    revision = prompt_revision_review(job, prompt_revisions=prompt_revisions)
    if revision and revision.get("blocker"):
        blockers.append(str(revision["blocker"]))
    return blockers


def job_selection_blocker(
    job: dict[str, Any],
    *,
    retry_failed: bool = False,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> str:
    return "; ".join(
        job_selection_blockers(job, retry_failed=retry_failed, prompt_revisions=prompt_revisions)
    )


def job_preview(
    job: dict[str, Any],
    *,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    image_path = job_image_path(job)
    provider = job.get("provider") or {}
    preview = {
        "id": job.get("id"),
        "status": job.get("status"),
        "scene_id": job.get("scene_id"),
        "panel_index": job.get("panel_index"),
        "panel_label": job.get("panel_label"),
        "prompt_hash": job.get("prompt_hash"),
        "image_path": str(image_path),
        "image_exists": image_path.exists(),
        "provider": provider.get("provider"),
        "provider_status": provider.get("status"),
    }
    revision = prompt_revision_review(job, prompt_revisions=prompt_revisions)
    if revision:
        preview["revision"] = revision
    return preview


def job_review(
    job: dict[str, Any],
    *,
    retry_failed: bool = False,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blockers = job_selection_blockers(job, retry_failed=retry_failed, prompt_revisions=prompt_revisions)
    review = job_preview(job, prompt_revisions=prompt_revisions)
    review["selectable"] = not blockers
    review["blocker"] = "; ".join(blockers) if blockers else None
    review["blockers"] = blockers
    return review


def provider_job_with_prompt_revision(
    job: dict[str, Any],
    *,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    review = prompt_revision_review(job, prompt_revisions=prompt_revisions)
    if not review:
        return job, None
    if review.get("blocker"):
        raise ProviderError(f"Job {job.get('id')} prompt revision is not usable: {review['blocker']}")

    revision = (prompt_revisions or {})[str(job.get("id") or "")]
    run_job = dict(job)
    run_job["prompt"] = str(revision.get("revised_prompt") or "")
    run_job["prompt_hash"] = str(review.get("revised_prompt_hash") or "")
    return run_job, prompt_revision_metadata(review)


def selected_jobs(
    raw: dict[str, Any],
    *,
    limit: int,
    retry_failed: bool = False,
    job_id: str | None = None,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if job_id:
        for job in raw.get("jobs", []):
            if job.get("id") != job_id:
                continue
            blocker = job_selection_blocker(
                job,
                retry_failed=retry_failed,
                prompt_revisions=prompt_revisions,
            )
            if blocker:
                raise ProviderError(f"Job {job_id} is not selectable: {blocker}")
            return [job]
        raise ProviderError(f"Job id not found: {job_id}")

    jobs = []
    for job in raw.get("jobs", []):
        if job_selection_blocker(job, retry_failed=retry_failed, prompt_revisions=prompt_revisions):
            continue
        jobs.append(job)
        if len(jobs) >= limit:
            break
    return jobs


def generation_plan(
    raw: dict[str, Any],
    *,
    limit: int,
    retry_failed: bool = False,
    job_id: str | None = None,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    refresh_summary(raw)
    selected = selected_jobs(
        raw,
        limit=limit,
        retry_failed=retry_failed,
        job_id=job_id,
        prompt_revisions=prompt_revisions,
    )
    return {
        "summary": raw.get("summary", {}),
        "selection": {
            "limit": limit,
            "retry_failed": retry_failed,
            "job_id": job_id,
            "selected": len(selected),
            "revisions": bool(prompt_revisions),
        },
        "jobs": [job_preview(job, prompt_revisions=prompt_revisions) for job in selected],
    }


def review_plan(
    raw: dict[str, Any],
    *,
    limit: int,
    status: str = "pending",
    job_id: str | None = None,
    retry_failed: bool = False,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if status not in {"pending", "failed", "all"}:
        raise ValueError(f"Unknown review status: {status}")
    refresh_summary(raw)

    matches = []
    if job_id:
        for job in raw.get("jobs", []):
            if job.get("id") == job_id:
                matches.append(job)
                break
        if not matches:
            raise ProviderError(f"Job id not found: {job_id}")
    else:
        for job in raw.get("jobs", []):
            job_status = str(job.get("status") or "")
            if status == "pending" and (
                job_status == "failed"
                or job_selection_blocker(
                    job,
                    retry_failed=False,
                    prompt_revisions=prompt_revisions,
                )
            ):
                continue
            if status == "failed" and job_status != "failed":
                continue
            matches.append(job)
            if len(matches) >= limit:
                break

    return {
        "summary": raw.get("summary", {}),
        "review": {
            "limit": limit,
            "status": status,
            "job_id": job_id,
            "retry_failed": retry_failed,
            "revisions": bool(prompt_revisions),
            "selected": len(matches),
        },
        "jobs": [
            job_review(job, retry_failed=retry_failed, prompt_revisions=prompt_revisions)
            for job in matches
        ],
    }


def provider_metadata(
    *,
    provider: ImageProvider,
    result: GenerationResult | None,
    status: str,
    started_at: str,
    completed_at: str | None = None,
    checksum: str | None = None,
    output_path: str | None = None,
    error_details: dict[str, Any] | None = None,
    prompt_revision: dict[str, Any] | None = None,
    sensitive_values: list[str] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "provider": provider.name,
        "model": provider.model,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    if result:
        sensitive_values = sensitive_values or []
        provider_job_id = safe_provider_text(
            result.provider_job_id,
            sensitive_values=sensitive_values,
            fallback="provider_job_id_redacted",
        )
        notes = safe_provider_text(
            result.notes,
            sensitive_values=sensitive_values,
            fallback="Provider completed.",
        )
        cost_estimate = safe_provider_text(
            result.cost_estimate,
            sensitive_values=sensitive_values,
            fallback="",
        )
        metadata.update(
            {
                "provider_job_id": provider_job_id or None,
                "request_metadata": sanitize_request_metadata(
                    result.request_metadata,
                    sensitive_values=sensitive_values,
                ),
                "output_format": result.output_format,
                "seed": result.seed,
                "cost_estimate": cost_estimate or None,
                "notes": notes,
            }
        )
    if checksum:
        metadata["checksum_sha256"] = checksum
    if output_path:
        metadata["output_path"] = output_path
    if error_details:
        error_details = sanitize_error_details(error_details, sensitive_values=sensitive_values or [])
        metadata["error"] = error_details.get("message")
        for key in ("error_type", "error_code", "http_status", "request_id"):
            if error_details.get(key):
                metadata[key] = error_details[key]
    if prompt_revision:
        metadata["prompt_revision"] = prompt_revision
    return metadata


def run_provider_generation(
    ledger_path: Path,
    provider: ImageProvider,
    *,
    limit: int,
    retry_failed: bool = False,
    stop_on_error: bool = False,
    job_id: str | None = None,
    prompt_revisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, int]:
    raw = load_ledger(ledger_path)
    if recover_existing_outputs(raw):
        save_ledger(ledger_path, raw)
    selected = selected_jobs(
        raw,
        limit=limit,
        retry_failed=retry_failed,
        job_id=job_id,
        prompt_revisions=prompt_revisions,
    )
    counts = {"selected": len(selected), "completed": 0, "failed": 0}
    for job in selected:
        started_at = utc_now()
        provider_job, prompt_revision = provider_job_with_prompt_revision(
            job,
            prompt_revisions=prompt_revisions,
        )
        sensitive_values = sensitive_values_for_job(job, provider_job)
        sensitive_values.extend(sensitive_values_for_provider(provider))
        job["status"] = "running"
        job["updated_at"] = started_at
        job["provider"] = provider_metadata(
            provider=provider,
            result=None,
            status="running",
            started_at=started_at,
            prompt_revision=prompt_revision,
            sensitive_values=sensitive_values,
        )
        save_ledger(ledger_path, raw)
        try:
            result = provider.generate(provider_job)
            output = Path(str(job["image_path"]))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(result.image_bytes)
            digest = sha256_bytes(result.image_bytes)
            completed_at = utc_now()
            job["status"] = "done"
            job["output_path"] = str(output)
            job["updated_at"] = completed_at
            job["notes"] = safe_provider_text(
                result.notes,
                sensitive_values=sensitive_values,
                fallback="Provider completed.",
            )
            job["provider"] = provider_metadata(
                provider=provider,
                result=result,
                status="done",
                started_at=started_at,
                completed_at=completed_at,
                checksum=digest,
                output_path=str(output),
                prompt_revision=prompt_revision,
                sensitive_values=sensitive_values,
            )
            counts["completed"] += 1
        except Exception as exc:
            completed_at = utc_now()
            details = provider_error_details(provider, exc)
            safe_details = sanitize_error_details(details, sensitive_values=sensitive_values)
            message = str(safe_details.get("message") or f"Provider {provider.name} failed")
            job["status"] = "failed"
            job["updated_at"] = completed_at
            job["notes"] = message
            job["provider"] = provider_metadata(
                provider=provider,
                result=None,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                error_details=safe_details,
                prompt_revision=prompt_revision,
                sensitive_values=sensitive_values,
            )
            counts["failed"] += 1
            save_ledger(ledger_path, raw)
            if stop_on_error:
                raise ProviderError(message) from exc
        save_ledger(ledger_path, raw)
        time.sleep(0)
    return counts
