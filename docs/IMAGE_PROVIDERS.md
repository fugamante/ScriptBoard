# Image Provider Architecture

ScriptBoard image generation is provider-neutral. The job ledger remains the
source of truth, providers are interchangeable execution backends, and generated
assets are always written to local project output paths before a job is marked
done.

## Provider Ranking

1. OpenAI Image API is the first real provider because it gives ScriptBoard a
   direct, supported prompt-to-image API path without Safari, ChatGPT UI state,
   Apple Events, browser cookies, or manual download scraping.
2. Managed provider APIs such as Replicate, fal, Black Forest Labs, Google, or
   Stability should be added after the first OpenAI path is stable. They fit the
   same contract, but often add remote job polling, provider-specific artifact
   URLs, and retention rules.
3. ComfyUI should be treated as a local worker backend. ScriptBoard should submit
   workflows and poll local queue/history endpoints, while still owning the job
   ledger and final local image files.
4. Browser automation is a legacy fallback only. It is brittle, auth-state heavy,
   and should stay isolated behind explicit manual commands.

## Provider Contract

The active CLI command is:

```bash
scriptboard generate --provider openai --limit 1
```

`scriptboard generate` loads `Storyboard_Image_Jobs.json`, selects jobs whose
image file is missing, marks each selected job `running`, saves the ledger,
calls one provider for one image, writes bytes to `job.image_path`, stores a
checksum, then marks the job `done`. Provider failures mark the job `failed`
without deleting prior generated files.

A provider implements:

```python
class ImageProvider(Protocol):
    name: str
    model: str

    def generate(self, job: dict[str, Any]) -> GenerationResult:
        ...
```

`GenerationResult` returns image bytes and sanitized request metadata. It must
not return API keys, browser auth state, signed URLs, or another copy of private
prompt text.

## Durable Metadata Schema

Each generated job keeps its existing ScriptBoard fields and adds provider
metadata under `job.provider`:

```json
{
  "status": "done",
  "output_path": "Storyboard_Images/scene_001/panel_001.png",
  "provider": {
    "provider": "openai",
    "model": "gpt-image-2",
    "status": "done",
    "started_at": "2026-07-07T00:00:00+00:00",
    "completed_at": "2026-07-07T00:00:30+00:00",
    "provider_job_id": "req_...",
    "request_metadata": {
      "model": "gpt-image-2",
      "n": 1,
      "size": "1536x1024",
      "quality": "medium",
      "output_format": "png",
      "prompt_hash": "..."
    },
    "output_format": "png",
    "checksum_sha256": "...",
    "output_path": "Storyboard_Images/scene_001/panel_001.png"
  }
}
```

Failure metadata uses the same envelope with `status: "failed"` and an `error`
message. An interrupted run may leave a job `running`; the next run treats a
missing image file as resumable work and attempts the job again.

The ledger summary now supports:

```json
{"total": 4, "pending": 2, "done": 1, "failed": 1}
```

## OpenAI Provider

`OpenAIImageProvider` reads `OPENAI_API_KEY` from the environment, posts one
image generation request to the OpenAI Image API, decodes `data[0].b64_json`,
and writes the decoded bytes to the local image path. The transient request
body contains `job.prompt`; persisted `request_metadata` stores only model
parameters and `prompt_hash`.

Default settings:

- model: `gpt-image-2`
- size: `1536x1024`
- quality: `medium`
- output format: `png`

Run a small real-provider batch only after fake-provider validation:

```bash
OPENAI_API_KEY=... scriptboard generate --provider openai --limit 1
```

Do not commit `.env` files, API keys, signed artifact URLs, browser profiles, or
generated screenplay images.

## Fake Provider

`FakeImageProvider` writes deterministic one-pixel PNG files. It is the default
test double for provider work and covers:

- fake-provider generation without network access
- interrupted resume from `running`
- local output checksum recording
- failed-job state and `--retry-failed`
- CLI routing through `scriptboard generate --provider fake`

The fake provider is not a storyboard-quality renderer; it exists to prove the
ledger contract before real credentials or paid providers are used.

## Future Provider Lanes

Managed APIs should map their native job lifecycle into the same ledger states.
For example, queued or in-progress remote jobs can persist a provider job ID and
poll status until final bytes are available. Persist provider job IDs and stable
non-secret metadata; avoid storing short-lived signed download URLs.

ComfyUI should be implemented as a local worker provider. Submit to `/prompt`,
poll `/queue` or `/history/{prompt_id}`, then copy/download the produced image
into `job.image_path`. ScriptBoard should not treat the ComfyUI history folder
as the canonical artifact store.

Browser fallback should stay outside the primary provider path. The existing
Safari inspection command can remain for local manual recovery, but standalone
ScriptBoard should not depend on Safari, Apple Events, ChatGPT cookies, or DOM
shape for normal generation.

## Authorities

- OpenAI Image API guide and image reference:
  <https://platform.openai.com/docs/guides/image-generation> and
  <https://platform.openai.com/docs/api-reference/images/create>
- OpenAI Batch API guide for future bulk request shape:
  <https://platform.openai.com/docs/guides/batch>
- Replicate prediction lifecycle:
  <https://replicate.com/docs/topics/predictions/create-a-prediction>
- fal queue lifecycle:
  <https://fal.ai/docs/model-endpoints/queue>
- ComfyUI queue/history routes:
  <https://docs.comfy.org/development/comfyui-server/comms_routes>
- Playwright auth-state guidance:
  <https://playwright.dev/docs/auth>
- OpenAI Terms of Use, including the restriction on automatic/programmatic
  extraction of Output from consumer services:
  <https://openai.com/policies/row-terms-of-use/>
