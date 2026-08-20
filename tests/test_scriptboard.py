from __future__ import annotations

import base64
from contextlib import redirect_stderr
import hashlib
from io import BytesIO, StringIO
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error

from scriptboard import board, builder, cli, image_jobs, image_providers
from scriptboard.config import load_config


class LeakyFailureProvider:
    name = "leaky"
    model = "leaky-provider"

    def generate(self, job: dict) -> image_providers.GenerationResult:
        prompt = str(job.get("prompt") or "")
        raise image_providers.ProviderError(
            f"Provider echoed unsafe prompt: {prompt}",
            error_type=f"type {prompt}",
            error_code=f"code {prompt}",
            request_id=f"request {prompt}",
        )


class LeakyMetadataProvider:
    name = "leaky"
    model = "leaky-provider"

    def generate(self, job: dict) -> image_providers.GenerationResult:
        return image_providers.GenerationResult(
            provider=self.name,
            model=self.model,
            image_bytes=image_providers.fake_png("leaky-metadata"),
            request_metadata={
                "provider": self.name,
                "job_id": job.get("id"),
                "prompt_hash": job.get("prompt"),
                "model": job.get("prompt"),
                "size": [job.get("prompt")],
                "prompt": job.get("prompt"),
                "api_key": "sk-test-should-not-persist",
                "signed_url": "https://example.invalid/signed",
            },
            provider_job_id="https://example.invalid/signed-provider-job",
            notes=f"Completed with prompt {job.get('prompt')}",
        )


class UnsafePersistingProvider:
    name = "unsafe"
    model = "unsafe-provider"

    def generate(self, job: dict) -> image_providers.GenerationResult:
        prompt = str(job.get("prompt") or "")
        raise image_providers.ProviderError(
            f"Persisted unsafe prompt: {prompt}",
            error_type=f"type {prompt}",
            error_code=f"code {prompt}",
            http_status=f"https://example.invalid/{prompt}",
            request_id=f"request {prompt}",
            persist_message=True,
        )


class MockOpenAIResponse:
    def __init__(self, payload: dict | bytes, *, request_id: str = "req_test") -> None:
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = {"x-request-id": request_id}

    def __enter__(self) -> "MockOpenAIResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def mock_openai_success(image_bytes: bytes, *, request_id: str = "req_test") -> MockOpenAIResponse:
    return MockOpenAIResponse(
        {"data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]},
        request_id=request_id,
    )


def mock_openai_http_error(
    *,
    status: int = 400,
    body: dict | bytes | None = None,
    request_id: str = "req_error",
) -> error.HTTPError:
    if body is None:
        body = {"error": {"type": "invalid_request_error", "code": "bad_request"}}
    payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return error.HTTPError(
        "https://api.openai.com/v1/images/generations",
        status,
        "provider error",
        {"x-request-id": request_id},
        BytesIO(payload),
    )


class ScriptBoardTests(unittest.TestCase):
    def write_provider_ledger(self, root: Path, *, count: int = 2) -> Path:
        jobs = []
        for index in range(1, count + 1):
            job_id = f"job-{index}"
            jobs.append(
                {
                    "id": job_id,
                    "status": "pending",
                    "scene_id": "scene_001_room",
                    "scene_title": "INT. ROOM - DAY",
                    "panel_index": index,
                    "panel_label": f"Panel {index}",
                    "script_passage": f"A test action beat {index}.",
                    "prompt": f"Storyboard prompt {index}",
                    "prompt_hash": f"hash-{index}",
                    "image_path": str(root / "Storyboard_Images" / "scene_001_room" / f"panel_{index:03d}.png"),
                    "updated_at": None,
                    "notes": "",
                }
            )
        ledger_path = root / "Storyboard_Image_Jobs.json"
        ledger_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00",
                    "source": str(root / "Storyboard_Prompts.json"),
                    "images_dir": str(root / "Storyboard_Images"),
                    "summary": {"total": count, "pending": count, "done": 0},
                    "jobs": jobs,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return ledger_path

    def write_revision_file(
        self,
        root: Path,
        *,
        job_id: str = "job-1",
        status: str = "ready",
        source_prompt_hash: str = "hash-1",
        revised_prompt: str = "Synthetic revised visual prompt.",
    ) -> Path:
        revisions_path = root / "Storyboard_Prompt_Revisions.json"
        revisions_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "revisions": [
                        {
                            "job_id": job_id,
                            "status": status,
                            "source_prompt_hash": source_prompt_hash,
                            "revised_prompt": revised_prompt,
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return revisions_path

    def test_render_fdx_text_preserves_screenplay_paragraph_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Draft_Test.fdx"
            path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<FinalDraft>
  <Content>
    <Paragraph Type="Scene Heading"><Text>int. kitchen - morning</Text></Paragraph>
    <Paragraph Type="Action"><Text>A kettle rattles on the stove.</Text></Paragraph>
    <Paragraph Type="Character"><Text>Mara</Text></Paragraph>
    <Paragraph Type="Dialogue"><Text>We have ten minutes.</Text></Paragraph>
  </Content>
</FinalDraft>
""",
                encoding="utf-8",
            )

            rendered = builder.render_fdx_text(path)

        self.assertIn("INT. KITCHEN - MORNING", rendered)
        self.assertIn("A kettle rattles on the stove.", rendered)
        self.assertIn("MARA", rendered)
        self.assertLess(rendered.index("INT. KITCHEN"), rendered.index("A kettle"))

    def test_candidate_files_prefers_fdx_over_same_stem_companion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Draft_Test.fdx").write_text("<FinalDraft />", encoding="utf-8")
            (root / "Draft_Test.txt").write_text("txt draft", encoding="utf-8")
            (root / "Storyboard_Prompts.md").write_text("generated", encoding="utf-8")

            candidates = builder.candidate_files(root)

        self.assertEqual([path.name for path in candidates], ["Draft_Test.fdx"])

    def test_default_config_uses_generic_public_safe_defaults(self) -> None:
        config = load_config(base_dir=Path("/definitely/missing"))
        prompt = builder.concise_prompt(
            "INT. ROOM - DAY",
            "A teenager stands by the kitchen door.",
            config.visual_style,
            config,
        )

        self.assertEqual(config.title, "Untitled Screenplay")
        self.assertIn("# Storyboard Prompts: Untitled Screenplay", builder.markdown([], [], config))
        self.assertIn("A teenager stands by the kitchen door.", prompt)
        self.assertNotIn("do not emphasize exact numeric age", prompt)

    def test_project_config_overrides_title_style_safety_sources_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "ScriptBoard_Config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "title": "Night Train",
                        "visual_style": "Use stark black-and-white location photography.",
                        "sources": {
                            "extensions": [".txt", ".fdx"],
                            "priority": [".txt", ".fdx"],
                        },
                        "outputs": {
                            "prompts_md": "Night_Prompts.md",
                            "prompts_json": "Night_Prompts.json",
                            "image_jobs": "Night_Jobs.json",
                            "panel_catalog": "Night_Catalog.md",
                            "board_html": "Night_Board.html",
                            "images_dir": "Night_Images",
                            "erased_panels": "Night_Erased.json",
                        },
                        "board": {
                            "html_title": "Night Train Board",
                            "brand": "Night Train",
                            "heading": "Night Train\\nStoryboard",
                            "intro": "Configured board intro.",
                            "annotation_placeholder": "Configured annotation placeholder.",
                        },
                        "safety": {
                            "replacements": [
                                {
                                    "pattern": r"\bKID, 12,",
                                    "replacement": "Kid, a young teenager,",
                                    "flags": "i",
                                }
                            ],
                            "notes": [
                                {
                                    "contains": "kid",
                                    "note": "Keep the kid in a non-sensitive context.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "Draft_Test.fdx").write_text("<FinalDraft />", encoding="utf-8")
            (root / "Draft_Test.txt").write_text("txt draft", encoding="utf-8")

            config = load_config(config_path)
            candidates = builder.candidate_files(root, config)
            prompt = builder.concise_prompt(
                "INT. TRAIN - NIGHT",
                "KID, 12, waits by a window.",
                config.visual_style,
                config,
            )
            html = board.build_html({"jobs": []}, root, config)

        self.assertEqual([path.name for path in candidates], ["Draft_Test.txt"])
        self.assertIn("# Storyboard Prompts: Night Train", builder.markdown([], [], config))
        self.assertIn("Use stark black-and-white location photography.", prompt)
        self.assertIn("Kid, a young teenager", prompt)
        self.assertIn("Keep the kid in a non-sensitive context.", prompt)
        self.assertIn("<title>Night Train Board</title>", html)
        self.assertIn("<p class=\"brand\">Night Train</p>", html)
        self.assertIn("<h1>Night Train<br>Storyboard</h1>", html)
        self.assertIn("Configured board intro.", html)
        self.assertIn("Configured annotation placeholder.", html)

    def test_build_jobs_filters_erased_panels_and_marks_existing_images_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompts_path = root / "Storyboard_Prompts.json"
            jobs_path = root / "Storyboard_Image_Jobs.json"
            removed_path = root / "Storyboard_Erased_Panels.json"
            images_dir = root / "Storyboard_Images"
            prompts_path.write_text(
                json.dumps(
                    {
                        "prompt_packs": [
                            {
                                "id": "scene_001_room",
                                "title": "INT. ROOM - DAY",
                                "frames": [
                                    {
                                        "id": "keep",
                                        "label": "Opening Panel",
                                        "script_passage": "A door opens.",
                                        "prompt": "Prompt keep",
                                    },
                                    {
                                        "id": "drop",
                                        "label": "Final Panel",
                                        "script_passage": "A door closes.",
                                        "prompt": "Prompt drop",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            removed_path.write_text(
                json.dumps({"erased_panels": [{"job_id": "drop"}]}),
                encoding="utf-8",
            )
            existing_image = images_dir / "scene_001_room" / "panel_001_opening_panel.png"
            existing_image.parent.mkdir(parents=True)
            existing_image.write_bytes(b"png")

            payload = image_jobs.build_jobs(prompts_path, images_dir, jobs_path, removed_path)

        self.assertEqual(payload["summary"], {"total": 1, "pending": 0, "done": 1})
        self.assertEqual(payload["jobs"][0]["id"], "keep")
        self.assertEqual(payload["jobs"][0]["status"], "done")

    def test_board_uses_relative_cache_busted_image_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "Storyboard_Images" / "scene_001_room" / "panel_001.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png")
            payload = {
                "jobs": [
                    {
                        "id": "job-1",
                        "status": "done",
                        "scene_id": "scene_001_room",
                        "scene_title": "INT. ROOM - DAY",
                        "panel_index": 1,
                        "panel_label": "Opening Panel",
                        "script_passage": "A door opens.",
                        "prompt": "Prompt",
                        "image_path": str(image_path),
                    }
                ]
            }

            html = board.build_html(payload, root)

        self.assertIn("Storyboard_Images/scene_001_room/panel_001.png?v=", html)
        self.assertIn("data-script-passage=\"A door opens.\"", html)
        self.assertIn("<strong>Script segment</strong>", html)
        self.assertIn("A door opens.", html)

    def test_catalog_records_panel_status_assignments_and_script_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "Storyboard_Images" / "scene_001_room" / "panel_001.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png")
            catalog_path = root / "Storyboard_Panel_Catalog.md"
            payload = {
                "jobs": [
                    {
                        "id": "job-1",
                        "status": "done",
                        "scene_id": "scene_001_room",
                        "scene_title": "INT. ROOM - DAY",
                        "panel_index": 1,
                        "panel_label": "Opening Panel",
                        "script_passage": "A door opens.",
                        "image_path": str(image_path),
                    },
                    {
                        "id": "job-2",
                        "status": "pending",
                        "scene_id": "scene_001_room",
                        "scene_title": "INT. ROOM - DAY",
                        "panel_index": 2,
                        "panel_label": "Panel 2",
                        "script_passage": "SARAH (INTO PHONE)",
                        "image_path": str(root / "missing.png"),
                    },
                    {
                        "id": "job-3",
                        "status": "pending",
                        "scene_id": "scene_001_room",
                        "scene_title": "INT. ROOM - DAY",
                        "panel_index": 3,
                        "panel_label": "Panel 3",
                        "script_passage": "SARAH (INTO PHONE)",
                        "image_path": str(root / "missing-2.png"),
                    },
                ]
            }

            image_jobs.build_catalog(payload, catalog_path)
            catalog = catalog_path.read_text(encoding="utf-8")

        self.assertIn("# Storyboard Panel Catalog", catalog)
        self.assertIn("- Generated and assigned: 1", catalog)
        self.assertIn("- Pending image generation: 2", catalog)
        self.assertIn("#### Panel 001: Opening Panel", catalog)
        self.assertIn("- Status: generated", catalog)
        self.assertIn("A door opens.", catalog)
        self.assertIn("duplicate script segment, weak visual basis", catalog)

    def test_fake_provider_generates_checksums_and_resumes_pending_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=2)
            provider = image_providers.FakeImageProvider()

            first = image_providers.run_provider_generation(ledger_path, provider, limit=1)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            first_job = raw["jobs"][0]
            first_image = Path(first_job["image_path"])
            first_bytes = first_image.read_bytes()

            self.assertEqual(first, {"selected": 1, "completed": 1, "failed": 0})
            self.assertEqual(raw["summary"], {"total": 2, "pending": 1, "done": 1, "failed": 0})
            self.assertEqual(first_job["status"], "done")
            self.assertTrue(first_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(first_job["provider"]["provider"], "fake")
            self.assertEqual(first_job["provider"]["checksum_sha256"], hashlib.sha256(first_bytes).hexdigest())

            second = image_providers.run_provider_generation(ledger_path, provider, limit=10)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))

        self.assertEqual(second, {"selected": 1, "completed": 1, "failed": 0})
        self.assertEqual(raw["summary"], {"total": 2, "pending": 0, "done": 2, "failed": 0})
        self.assertEqual([job["status"] for job in raw["jobs"]], ["done", "done"])

    def test_fake_provider_retries_failed_jobs_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)

            failed = image_providers.run_provider_generation(
                ledger_path,
                image_providers.FakeImageProvider(fail_job_ids={"job-1"}),
                limit=1,
            )
            skipped = image_providers.run_provider_generation(
                ledger_path,
                image_providers.FakeImageProvider(),
                limit=1,
            )
            retried = image_providers.run_provider_generation(
                ledger_path,
                image_providers.FakeImageProvider(),
                limit=1,
                retry_failed=True,
            )
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))

        self.assertEqual(failed, {"selected": 1, "completed": 0, "failed": 1})
        self.assertEqual(skipped, {"selected": 0, "completed": 0, "failed": 0})
        self.assertEqual(retried, {"selected": 1, "completed": 1, "failed": 0})
        self.assertEqual(raw["summary"], {"total": 1, "pending": 0, "done": 1, "failed": 0})
        self.assertEqual(raw["jobs"][0]["provider"]["status"], "done")

    def test_provider_generation_resumes_running_jobs_after_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            raw["jobs"][0]["status"] = "running"
            raw["jobs"][0]["provider"] = {
                "provider": "fake",
                "model": "fake-image-provider",
                "status": "running",
                "started_at": "2026-01-01T00:00:00+00:00",
                "completed_at": None,
            }
            ledger_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

            result = image_providers.run_provider_generation(
                ledger_path,
                image_providers.FakeImageProvider(),
                limit=1,
            )
            resumed = json.loads(ledger_path.read_text(encoding="utf-8"))
            resumed_image_exists = Path(resumed["jobs"][0]["image_path"]).exists()

        self.assertEqual(result, {"selected": 1, "completed": 1, "failed": 0})
        self.assertEqual(resumed["jobs"][0]["status"], "done")
        self.assertTrue(resumed_image_exists)

    def test_generation_plan_omits_private_prompt_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=2)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))

            plan = image_providers.generation_plan(raw, limit=1)

        self.assertEqual(plan["selection"]["selected"], 1)
        self.assertEqual(plan["jobs"][0]["id"], "job-1")
        self.assertIn("prompt_hash", plan["jobs"][0])
        self.assertNotIn("prompt", plan["jobs"][0])
        self.assertNotIn("script_passage", plan["jobs"][0])

    def test_cli_plan_reviews_pending_jobs_without_private_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=2)
            before = ledger_path.read_text(encoding="utf-8")
            stderr = StringIO()

            with redirect_stderr(stderr):
                self.assertEqual(cli.main(["plan", "--jobs", str(ledger_path), "--limit", "2"]), 0)
            after = ledger_path.read_text(encoding="utf-8")
            plan = json.loads(stderr.getvalue())

        self.assertEqual(after, before)
        self.assertEqual(plan["review"]["status"], "pending")
        self.assertEqual([job["id"] for job in plan["jobs"]], ["job-1", "job-2"])
        self.assertTrue(all(job["selectable"] for job in plan["jobs"]))
        self.assertNotIn("Storyboard prompt", stderr.getvalue())
        self.assertNotIn("A test action beat", stderr.getvalue())

    def test_cli_plan_filters_failed_jobs_and_exact_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=2)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            raw["jobs"][1]["status"] = "failed"
            raw["jobs"][1]["notes"] = "provider failed"
            ledger_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
            failed_stderr = StringIO()
            exact_stderr = StringIO()

            with redirect_stderr(failed_stderr):
                self.assertEqual(
                    cli.main(["plan", "--jobs", str(ledger_path), "--status", "failed", "--limit", "5"]),
                    0,
                )
            with redirect_stderr(exact_stderr):
                self.assertEqual(cli.main(["plan", "--jobs", str(ledger_path), "--job-id", "job-1"]), 0)
            failed_plan = json.loads(failed_stderr.getvalue())
            exact_plan = json.loads(exact_stderr.getvalue())

        self.assertEqual([job["id"] for job in failed_plan["jobs"]], ["job-2"])
        self.assertFalse(failed_plan["jobs"][0]["selectable"])
        self.assertIn("--retry-failed", failed_plan["jobs"][0]["blocker"])
        self.assertEqual([job["id"] for job in exact_plan["jobs"]], ["job-1"])
        self.assertNotIn("Storyboard prompt", failed_stderr.getvalue())
        self.assertNotIn("A test action beat", exact_stderr.getvalue())

    def test_cli_plan_reports_ready_prompt_revision_without_private_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revised_prompt = "Synthetic revised prompt that should stay local only."
            revisions_path = self.write_revision_file(root, revised_prompt=revised_prompt)
            stderr = StringIO()

            with redirect_stderr(stderr):
                self.assertEqual(
                    cli.main(
                        [
                            "plan",
                            "--jobs",
                            str(ledger_path),
                            "--revisions",
                            str(revisions_path),
                            "--job-id",
                            "job-1",
                        ]
                    ),
                    0,
                )
            plan = json.loads(stderr.getvalue())
            revision = plan["jobs"][0]["revision"]

        self.assertTrue(plan["jobs"][0]["selectable"])
        self.assertEqual(revision["status"], "ready")
        self.assertEqual(revision["source_prompt_hash"], "hash-1")
        self.assertEqual(revision["revised_prompt_hash"], image_providers.prompt_text_hash(revised_prompt))
        self.assertTrue(revision["applies"])
        self.assertNotIn("revised_prompt", revision)
        self.assertNotIn(revised_prompt, stderr.getvalue())
        self.assertNotIn("Storyboard prompt", stderr.getvalue())
        self.assertNotIn("A test action beat", stderr.getvalue())

    def test_cli_revisions_scaffold_ready_entry_without_printing_prompt_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revisions_path = root / "Storyboard_Prompt_Revisions.json"
            private_prompt = "Synthetic local prompt body that must not print."
            prompt_path = root / "private_prompt.txt"
            prompt_path.write_text(private_prompt, encoding="utf-8")
            stderr = StringIO()

            with redirect_stderr(stderr):
                self.assertEqual(
                    cli.main(
                        [
                            "revisions",
                            "scaffold",
                            "--jobs",
                            str(ledger_path),
                            "--revisions",
                            str(revisions_path),
                            "--job-id",
                            "job-1",
                            "--status",
                            "ready",
                            "--revised-prompt-file",
                            str(prompt_path),
                        ]
                    ),
                    0,
                )
            result = json.loads(stderr.getvalue())
            raw = json.loads(revisions_path.read_text(encoding="utf-8"))

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["revision"]["job_id"], "job-1")
        self.assertEqual(result["revision"]["status"], "ready")
        self.assertEqual(result["revision"]["source_prompt_hash"], "hash-1")
        self.assertEqual(
            result["revision"]["revised_prompt_hash"],
            image_providers.prompt_text_hash(private_prompt),
        )
        self.assertEqual(raw["revisions"][0]["revised_prompt"], private_prompt)
        self.assertNotIn(private_prompt, stderr.getvalue())
        self.assertNotIn("Storyboard prompt", stderr.getvalue())
        self.assertNotIn("A test action beat", stderr.getvalue())

    def test_cli_revisions_validate_ready_entry_without_private_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            private_prompt = "Synthetic revised prompt that validation must not print."
            revisions_path = self.write_revision_file(root, revised_prompt=private_prompt)
            stderr = StringIO()

            with redirect_stderr(stderr):
                self.assertEqual(
                    cli.main(
                        [
                            "revisions",
                            "validate",
                            "--jobs",
                            str(ledger_path),
                            "--revisions",
                            str(revisions_path),
                            "--job-id",
                            "job-1",
                            "--strict",
                        ]
                    ),
                    0,
                )
            result = json.loads(stderr.getvalue())
            item = result["revisions"][0]

        self.assertEqual(result["summary"]["ready"], 1)
        self.assertEqual(result["summary"]["blocked"], 0)
        self.assertTrue(item["applies"])
        self.assertEqual(item["revised_prompt_hash"], image_providers.prompt_text_hash(private_prompt))
        self.assertNotIn(private_prompt, stderr.getvalue())
        self.assertNotIn("Storyboard prompt", stderr.getvalue())
        self.assertNotIn("A test action beat", stderr.getvalue())

    def test_cli_revisions_validate_draft_entry_blocks_strict_without_private_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            private_prompt = "Synthetic draft prompt that validation must not print."
            revisions_path = self.write_revision_file(
                root,
                status="draft",
                revised_prompt=private_prompt,
            )
            stderr = StringIO()

            with redirect_stderr(stderr):
                code = cli.main(
                    [
                        "revisions",
                        "validate",
                        "--jobs",
                        str(ledger_path),
                        "--revisions",
                        str(revisions_path),
                        "--strict",
                    ]
                )
            result = json.loads(stderr.getvalue())
            item = result["revisions"][0]

        self.assertEqual(code, 1)
        self.assertEqual(result["summary"]["draft"], 1)
        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(item["blocker"], "prompt revision is not ready")
        self.assertNotIn(private_prompt, stderr.getvalue())
        self.assertNotIn("Storyboard prompt", stderr.getvalue())
        self.assertNotIn("A test action beat", stderr.getvalue())

    def test_cli_revisions_validate_hash_mismatch_without_private_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            private_prompt = "Synthetic mismatched prompt that validation must not print."
            revisions_path = self.write_revision_file(
                root,
                source_prompt_hash="stale-source-hash",
                revised_prompt=private_prompt,
            )
            stderr = StringIO()

            with redirect_stderr(stderr):
                code = cli.main(
                    [
                        "revisions",
                        "validate",
                        "--jobs",
                        str(ledger_path),
                        "--revisions",
                        str(revisions_path),
                        "--strict",
                    ]
                )
            result = json.loads(stderr.getvalue())
            item = result["revisions"][0]

        self.assertEqual(code, 1)
        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(
            item["blocker"],
            "prompt revision source_prompt_hash does not match job prompt_hash",
        )
        self.assertEqual(item["current_prompt_hash"], "hash-1")
        self.assertNotIn(private_prompt, stderr.getvalue())
        self.assertNotIn("Storyboard prompt", stderr.getvalue())
        self.assertNotIn("A test action beat", stderr.getvalue())

    def test_draft_prompt_revision_blocks_generation_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revisions_path = self.write_revision_file(
                root,
                status="draft",
                revised_prompt="Synthetic draft prompt.",
            )
            revisions = image_providers.load_prompt_revisions(revisions_path)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))

            plan = image_providers.review_plan(
                raw,
                limit=1,
                job_id="job-1",
                prompt_revisions=revisions,
            )
            with self.assertRaisesRegex(image_providers.ProviderError, "prompt revision is not ready"):
                image_providers.run_provider_generation(
                    ledger_path,
                    image_providers.FakeImageProvider(),
                    limit=1,
                    job_id="job-1",
                    prompt_revisions=revisions,
                )
            after = ledger_path.read_text(encoding="utf-8")

        self.assertFalse(plan["jobs"][0]["selectable"])
        self.assertIn("prompt revision is not ready", plan["jobs"][0]["blocker"])
        self.assertNotIn("Synthetic draft prompt.", json.dumps(plan))
        self.assertIn("\"status\": \"pending\"", after)

    def test_prompt_revision_schema_is_versioned_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            revisions_path = root / "Storyboard_Prompt_Revisions.json"
            revisions_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "revisions": [
                            {
                                "job_id": "job-1",
                                "status": "ready",
                                "source_prompt_hash": "hash-1",
                                "revised_prompt": "Synthetic revision.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(image_providers.ProviderError, "schema_version"):
                image_providers.load_prompt_revisions(revisions_path)

            revisions_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "revisions": [
                            {
                                "job_id": "job-1",
                                "status": "ready",
                                "source_prompt_hash": 123,
                                "revised_prompt": "Synthetic revision.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(image_providers.ProviderError, "source_prompt_hash"):
                image_providers.load_prompt_revisions(revisions_path)

    def test_prompt_revision_hash_mismatch_blocks_generation_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revisions_path = self.write_revision_file(
                root,
                source_prompt_hash="different-source-hash",
                revised_prompt="Synthetic revised prompt.",
            )
            revisions = image_providers.load_prompt_revisions(revisions_path)

            with self.assertRaisesRegex(image_providers.ProviderError, "source_prompt_hash"):
                image_providers.run_provider_generation(
                    ledger_path,
                    image_providers.FakeImageProvider(),
                    limit=1,
                    job_id="job-1",
                    prompt_revisions=revisions,
                )
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))

        self.assertEqual(raw["jobs"][0]["status"], "pending")
        self.assertFalse(Path(raw["jobs"][0]["image_path"]).exists())

    def test_pending_plan_excludes_revision_blocked_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=2)
            revisions_path = self.write_revision_file(
                root,
                status="draft",
                revised_prompt="Synthetic draft prompt.",
            )
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            revisions = image_providers.load_prompt_revisions(revisions_path)

            plan = image_providers.review_plan(
                raw,
                limit=5,
                status="pending",
                prompt_revisions=revisions,
            )

        self.assertEqual([job["id"] for job in plan["jobs"]], ["job-2"])
        self.assertNotIn("Synthetic draft prompt.", json.dumps(plan))

    def test_cli_generate_dry_run_is_read_only_and_does_not_require_provider_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            before = ledger_path.read_text(encoding="utf-8")

            self.assertEqual(
                cli.main(["generate", "--jobs", str(ledger_path), "--provider", "openai", "--dry-run"]),
                0,
            )
            after = ledger_path.read_text(encoding="utf-8")
            raw = json.loads(after)

        self.assertEqual(after, before)
        self.assertFalse(Path(raw["jobs"][0]["image_path"]).exists())

    def test_openai_request_payload_uses_configured_options(self) -> None:
        provider = image_providers.OpenAIImageProvider(
            api_key="unit-test-openai-key",
            model="test-image-model",
            size="1024x1024",
            quality="low",
            output_format="webp",
        )

        payload = provider.request_payload(
            {
                "id": "job-1",
                "prompt": "Synthetic provider prompt.",
                "prompt_hash": "hash-1",
            }
        )

        self.assertEqual(
            payload,
            {
                "model": "test-image-model",
                "prompt": "Synthetic provider prompt.",
                "n": 1,
                "size": "1024x1024",
                "quality": "low",
                "output_format": "webp",
            },
        )
        self.assertNotIn("prompt_hash", payload)

    def test_openai_provider_success_uses_generation_endpoint_and_metadata(self) -> None:
        image_bytes = image_providers.fake_png("openai-success")
        seen: dict[str, object] = {}

        def fake_urlopen(req: object, timeout: int) -> MockOpenAIResponse:
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            seen["authorization"] = req.get_header("Authorization")
            seen["content_type"] = req.get_header("Content-type")
            seen["payload"] = json.loads(req.data.decode("utf-8"))
            return mock_openai_success(image_bytes, request_id="req_success")

        provider = image_providers.OpenAIImageProvider(api_key="unit-test-openai-key", timeout_s=7)
        with patch("scriptboard.image_providers.request.urlopen", fake_urlopen):
            result = provider.generate(
                {
                    "id": "job-1",
                    "prompt": "Synthetic provider prompt.",
                    "prompt_hash": "hash-1",
                }
            )

        self.assertEqual(seen["url"], "https://api.openai.com/v1/images/generations")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["timeout"], 7)
        self.assertEqual(seen["authorization"], "Bearer unit-test-openai-key")
        self.assertEqual(seen["content_type"], "application/json")
        self.assertEqual(seen["payload"]["prompt"], "Synthetic provider prompt.")
        self.assertEqual(result.image_bytes, image_bytes)
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.provider_job_id, "req_success")
        self.assertEqual(result.request_metadata["prompt_hash"], "hash-1")
        self.assertNotIn("prompt", result.request_metadata)
        self.assertNotIn("unit-test-openai-key", json.dumps(result.request_metadata))

    def test_openai_provider_missing_api_key_fails_before_network(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = image_providers.OpenAIImageProvider()
            with patch("scriptboard.image_providers.request.urlopen") as urlopen:
                with self.assertRaisesRegex(image_providers.ProviderError, "OPENAI_API_KEY") as raised:
                    provider.generate({"id": "job-1", "prompt": "Synthetic provider prompt."})

        self.assertEqual(raised.exception.error_type, "missing_api_key")
        urlopen.assert_not_called()

    def test_openai_provider_http_error_classifies_safe_provider_fields(self) -> None:
        provider = image_providers.OpenAIImageProvider(api_key="unit-test-openai-key")
        http_error = mock_openai_http_error(
            status=429,
            body={"error": {"type": "rate_limit_error", "code": "rate_limit_exceeded"}},
            request_id="req_rate_limit",
        )

        with patch("scriptboard.image_providers.request.urlopen", side_effect=http_error):
            with self.assertRaises(image_providers.ProviderError) as raised:
                provider.generate({"id": "job-1", "prompt": "Synthetic provider prompt."})

        exc = raised.exception
        self.assertEqual(exc.error_type, "rate_limit_error")
        self.assertEqual(exc.error_code, "rate_limit_exceeded")
        self.assertEqual(exc.http_status, 429)
        self.assertEqual(exc.request_id, "req_rate_limit")
        self.assertIn("HTTP 429", str(exc))
        self.assertNotIn("Synthetic provider prompt.", str(exc))

    def test_openai_provider_http_error_redacts_unsafe_provider_fields_before_raise(self) -> None:
        api_key = "unit-test-openai-key-private"
        prompt = "Synthetic provider prompt that must not persist."
        provider = image_providers.OpenAIImageProvider(api_key=api_key)
        http_error = mock_openai_http_error(
            status=400,
            body={"error": {"type": f"type {prompt}", "code": f"code {api_key}"}},
            request_id=f"https://example.invalid/signed?token={api_key}",
        )

        with patch("scriptboard.image_providers.request.urlopen", side_effect=http_error):
            with self.assertRaises(image_providers.ProviderError) as raised:
                provider.generate({"id": "job-1", "prompt": prompt})

        exc = raised.exception
        self.assertEqual(exc.error_type, "provider_error")
        self.assertEqual(exc.error_code, "provider_error")
        self.assertEqual(exc.request_id, "request_id_redacted")
        self.assertNotIn(prompt, str(exc))
        self.assertNotIn(api_key, str(exc))
        self.assertNotIn("https://example.invalid", str(exc))

    def test_openai_provider_network_error_is_classified(self) -> None:
        provider = image_providers.OpenAIImageProvider(api_key="unit-test-openai-key")

        with patch(
            "scriptboard.image_providers.request.urlopen",
            side_effect=error.URLError("temporary failure"),
        ):
            with self.assertRaises(image_providers.ProviderError) as raised:
                provider.generate({"id": "job-1", "prompt": "Synthetic provider prompt."})

        self.assertEqual(raised.exception.error_type, "network_error")
        self.assertEqual(str(raised.exception), "OpenAI Image API request failed")

    def test_openai_provider_malformed_json_response_is_classified(self) -> None:
        provider = image_providers.OpenAIImageProvider(api_key="unit-test-openai-key")

        with patch(
            "scriptboard.image_providers.request.urlopen",
            return_value=MockOpenAIResponse(b"{not-json"),
        ):
            with self.assertRaises(image_providers.ProviderError) as raised:
                provider.generate({"id": "job-1", "prompt": "Synthetic provider prompt."})

        self.assertEqual(raised.exception.error_type, "malformed_response")
        self.assertEqual(str(raised.exception), "OpenAI Image API response was not valid JSON")

    def test_openai_provider_missing_image_data_is_classified(self) -> None:
        provider = image_providers.OpenAIImageProvider(api_key="unit-test-openai-key")

        with patch(
            "scriptboard.image_providers.request.urlopen",
            return_value=MockOpenAIResponse({"data": [{}]}),
        ):
            with self.assertRaises(image_providers.ProviderError) as raised:
                provider.generate({"id": "job-1", "prompt": "Synthetic provider prompt."})

        self.assertEqual(raised.exception.error_type, "missing_image_data")
        self.assertEqual(str(raised.exception), "OpenAI Image API response did not include data[0].b64_json")

    def test_openai_provider_invalid_base64_response_is_classified(self) -> None:
        provider = image_providers.OpenAIImageProvider(api_key="unit-test-openai-key")

        with patch(
            "scriptboard.image_providers.request.urlopen",
            return_value=MockOpenAIResponse({"data": [{"b64_json": "not base64!"}]}),
        ):
            with self.assertRaises(image_providers.ProviderError) as raised:
                provider.generate({"id": "job-1", "prompt": "Synthetic provider prompt."})

        self.assertEqual(raised.exception.error_type, "invalid_image_data")
        self.assertEqual(str(raised.exception), "OpenAI Image API response included invalid base64 image data")

    def test_openai_success_persistence_omits_prompt_api_key_and_signed_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            api_key = "unit-test-openai-key-private"
            provider = image_providers.OpenAIImageProvider(api_key=api_key)
            image_bytes = image_providers.fake_png("openai-persistence")

            with patch(
                "scriptboard.image_providers.request.urlopen",
                return_value=mock_openai_success(image_bytes, request_id=api_key),
            ):
                result = image_providers.run_provider_generation(ledger_path, provider, limit=1)

            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            job = raw["jobs"][0]
            provider_text = json.dumps(job["provider"], sort_keys=True)

        self.assertEqual(result, {"selected": 1, "completed": 1, "failed": 0})
        self.assertEqual(job["provider"]["provider"], "openai")
        self.assertEqual(job["provider"]["provider_job_id"], "provider_job_id_redacted")
        self.assertEqual(job["provider"]["request_metadata"]["prompt_hash"], "hash-1")
        self.assertNotIn(api_key, provider_text)
        self.assertNotIn("Storyboard prompt 1", provider_text)
        self.assertNotIn("https://", provider_text)

    def test_openai_error_persistence_omits_prompt_api_key_and_signed_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            api_key = "unit-test-openai-key-private"
            provider = image_providers.OpenAIImageProvider(api_key=api_key)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            prompt = raw["jobs"][0]["prompt"]
            http_error = mock_openai_http_error(
                status=400,
                body={
                    "error": {
                        "type": f"type {prompt}",
                        "code": "https://example.invalid/signed?token=abc",
                    }
                },
                request_id=f"https://example.invalid/signed?token={api_key}",
            )

            with patch("scriptboard.image_providers.request.urlopen", side_effect=http_error):
                result = image_providers.run_provider_generation(ledger_path, provider, limit=1)

            raw_text = ledger_path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            provider_text = json.dumps(raw["jobs"][0]["provider"], sort_keys=True)

        self.assertEqual(result, {"selected": 1, "completed": 0, "failed": 1})
        self.assertEqual(raw["jobs"][0]["provider"]["error_type"], "provider_error")
        self.assertEqual(raw["jobs"][0]["provider"]["error_code"], "provider_error")
        self.assertEqual(raw["jobs"][0]["provider"]["request_id"], "request_id_redacted")
        self.assertNotIn(api_key, provider_text)
        self.assertNotIn(prompt, provider_text)
        self.assertNotIn("https://example.invalid", provider_text)
        self.assertNotIn(api_key, raw_text)

    def test_provider_generation_targets_exact_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=2)

            result = image_providers.run_provider_generation(
                ledger_path,
                image_providers.FakeImageProvider(),
                limit=10,
                job_id="job-2",
            )
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            first_image_exists = Path(raw["jobs"][0]["image_path"]).exists()
            second_image_exists = Path(raw["jobs"][1]["image_path"]).exists()

        self.assertEqual(result, {"selected": 1, "completed": 1, "failed": 0})
        self.assertEqual([job["status"] for job in raw["jobs"]], ["pending", "done"])
        self.assertFalse(first_image_exists)
        self.assertTrue(second_image_exists)

    def test_ready_prompt_revision_feeds_provider_without_persisting_revised_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revised_prompt = "Synthetic revised provider prompt for one exact job."
            revised_hash = image_providers.prompt_text_hash(revised_prompt)
            revisions_path = self.write_revision_file(root, revised_prompt=revised_prompt)
            revisions = image_providers.load_prompt_revisions(revisions_path)

            result = image_providers.run_provider_generation(
                ledger_path,
                image_providers.FakeImageProvider(),
                limit=1,
                job_id="job-1",
                prompt_revisions=revisions,
            )
            raw_text = ledger_path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            job = raw["jobs"][0]

        self.assertEqual(result, {"selected": 1, "completed": 1, "failed": 0})
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["prompt_hash"], "hash-1")
        self.assertEqual(job["prompt"], "Storyboard prompt 1")
        self.assertEqual(job["provider"]["request_metadata"]["prompt_hash"], revised_hash)
        self.assertEqual(job["provider"]["prompt_revision"]["source_prompt_hash"], "hash-1")
        self.assertEqual(job["provider"]["prompt_revision"]["revised_prompt_hash"], revised_hash)
        self.assertNotIn(revised_prompt, raw_text)

    def test_provider_error_persistence_omits_revised_prompt_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revised_prompt = "Synthetic revised provider prompt should not persist after failure."
            revisions_path = self.write_revision_file(root, revised_prompt=revised_prompt)
            revisions = image_providers.load_prompt_revisions(revisions_path)

            result = image_providers.run_provider_generation(
                ledger_path,
                LeakyFailureProvider(),
                limit=1,
                job_id="job-1",
                prompt_revisions=revisions,
            )
            raw_text = ledger_path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            provider = raw["jobs"][0]["provider"]

        self.assertEqual(result, {"selected": 1, "completed": 0, "failed": 1})
        self.assertEqual(raw["jobs"][0]["notes"], "Provider leaky failed")
        self.assertEqual(provider["error"], "Provider leaky failed")
        self.assertEqual(provider["error_type"], "error_type_redacted")
        self.assertEqual(provider["error_code"], "error_code_redacted")
        self.assertEqual(provider["request_id"], "request_id_redacted")
        self.assertNotIn(revised_prompt, raw_text)
        self.assertNotIn("Provider echoed unsafe prompt", raw_text)

    def test_persisted_provider_error_message_and_http_status_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revised_prompt = "Synthetic revised provider prompt should not persist from structured errors."
            revisions_path = self.write_revision_file(root, revised_prompt=revised_prompt)
            revisions = image_providers.load_prompt_revisions(revisions_path)

            result = image_providers.run_provider_generation(
                ledger_path,
                UnsafePersistingProvider(),
                limit=1,
                job_id="job-1",
                prompt_revisions=revisions,
            )
            raw_text = ledger_path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            provider = raw["jobs"][0]["provider"]

        self.assertEqual(result, {"selected": 1, "completed": 0, "failed": 1})
        self.assertEqual(raw["jobs"][0]["notes"], "message_redacted")
        self.assertEqual(provider["error"], "message_redacted")
        self.assertEqual(provider["error_type"], "error_type_redacted")
        self.assertEqual(provider["error_code"], "error_code_redacted")
        self.assertEqual(provider["request_id"], "request_id_redacted")
        self.assertNotIn("http_status", provider)
        self.assertNotIn(revised_prompt, raw_text)
        self.assertNotIn("https://example.invalid", raw_text)
        self.assertNotIn("Persisted unsafe prompt", raw_text)

    def test_provider_request_metadata_is_allowlisted_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            revised_prompt = "Synthetic revised provider prompt should not persist as metadata."
            revisions_path = self.write_revision_file(root, revised_prompt=revised_prompt)
            revisions = image_providers.load_prompt_revisions(revisions_path)

            result = image_providers.run_provider_generation(
                ledger_path,
                LeakyMetadataProvider(),
                limit=1,
                job_id="job-1",
                prompt_revisions=revisions,
            )
            raw_text = ledger_path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            provider = raw["jobs"][0]["provider"]

        self.assertEqual(result, {"selected": 1, "completed": 1, "failed": 0})
        self.assertEqual(
            provider["request_metadata"],
            {
                "provider": "leaky",
                "job_id": "job-1",
                "prompt_hash": "prompt_hash_redacted",
                "model": "model_redacted",
                "size": ["size_redacted"],
            },
        )
        self.assertEqual(provider["provider_job_id"], "provider_job_id_redacted")
        self.assertEqual(provider["notes"], "Provider completed.")
        self.assertEqual(raw["jobs"][0]["notes"], "Provider completed.")
        self.assertNotIn(revised_prompt, raw_text)
        self.assertNotIn("sk-test-should-not-persist", raw_text)
        self.assertNotIn("signed", raw_text)

    def test_existing_image_after_interruption_is_recovered_without_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            image_path = Path(raw["jobs"][0]["image_path"])
            image_path.parent.mkdir(parents=True)
            image_bytes = b"existing-image-bytes"
            image_path.write_bytes(image_bytes)
            raw["jobs"][0]["status"] = "running"
            raw["jobs"][0]["provider"] = {
                "provider": "fake",
                "model": "fake-image-provider",
                "status": "running",
                "started_at": "2026-01-01T00:00:00+00:00",
                "completed_at": None,
            }
            ledger_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

            result = image_providers.run_provider_generation(
                ledger_path,
                image_providers.FakeImageProvider(),
                limit=1,
            )
            recovered = json.loads(ledger_path.read_text(encoding="utf-8"))
            provider = recovered["jobs"][0]["provider"]
            recovered_image_bytes = image_path.read_bytes()

        self.assertEqual(result, {"selected": 0, "completed": 0, "failed": 0})
        self.assertEqual(recovered["jobs"][0]["status"], "done")
        self.assertEqual(provider["status"], "done")
        self.assertEqual(provider["checksum_sha256"], hashlib.sha256(image_bytes).hexdigest())
        self.assertEqual(recovered_image_bytes, image_bytes)

    def test_cli_generate_routes_through_fake_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self.write_provider_ledger(root, count=1)

            self.assertEqual(
                cli.main(["generate", "--jobs", str(ledger_path), "--provider", "fake", "--limit", "1"]),
                0,
            )
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))

        self.assertEqual(raw["summary"], {"total": 1, "pending": 0, "done": 1, "failed": 0})
        self.assertEqual(raw["jobs"][0]["provider"]["provider"], "fake")

    def test_cli_build_jobs_board_and_cleanup_route_through_temp_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "Draft_Test.fdx"
            draft.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<FinalDraft><Content>
<Paragraph Type="Scene Heading"><Text>INT. TEST ROOM - DAY</Text></Paragraph>
<Paragraph Type="Action"><Text>A writer studies index cards across a table. The laptop glows beside a mug.</Text></Paragraph>
<Paragraph Type="Action"><Text>The cards shift into a clean storyboard order as morning light crosses the room.</Text></Paragraph>
</Content></FinalDraft>
""",
                encoding="utf-8",
            )

            self.assertEqual(cli.main(["build", "--input", str(root)]), 0)
            self.assertEqual(
                cli.main(
                    [
                        "jobs",
                        "--prompts",
                        str(root / "Storyboard_Prompts.json"),
                        "--images-dir",
                        str(root / "Storyboard_Images"),
                        "--jobs",
                        str(root / "Storyboard_Image_Jobs.json"),
                        "--catalog",
                        str(root / "Storyboard_Panel_Catalog.md"),
                        "--board",
                        str(root / "Storyboard_Board.html"),
                    ]
                ),
                0,
            )
            self.assertEqual(
                cli.main(
                    [
                        "board",
                        "--jobs",
                        str(root / "Storyboard_Image_Jobs.json"),
                        "--output",
                        str(root / "Storyboard_Board.html"),
                    ]
                ),
                0,
            )
            jobs = json.loads((root / "Storyboard_Image_Jobs.json").read_text(encoding="utf-8"))
            first_job_id = jobs["jobs"][0]["id"]
            (root / "Storyboard_Erased_Panels.json").write_text(
                json.dumps({"erased_panels": [{"job_id": first_job_id}]}),
                encoding="utf-8",
            )
            self.assertEqual(
                cli.main(
                    [
                        "cleanup",
                        "--jobs",
                        str(root / "Storyboard_Image_Jobs.json"),
                        "--removed",
                        str(root / "Storyboard_Erased_Panels.json"),
                        "--images-dir",
                        str(root / "Storyboard_Images"),
                    ]
                ),
                0,
            )
            cleaned = json.loads((root / "Storyboard_Image_Jobs.json").read_text(encoding="utf-8"))

            self.assertTrue((root / "Storyboard_Prompts.md").exists())
            self.assertTrue((root / "Storyboard_Panel_Catalog.md").exists())
            self.assertTrue((root / "Storyboard_Board.html").exists())
            self.assertNotIn(first_job_id, {job["id"] for job in cleaned["jobs"]})


if __name__ == "__main__":
    unittest.main()
