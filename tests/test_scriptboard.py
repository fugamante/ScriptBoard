from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scriptboard import board, builder, cli, image_jobs
from scriptboard.config import load_config


class ScriptBoardTests(unittest.TestCase):
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
