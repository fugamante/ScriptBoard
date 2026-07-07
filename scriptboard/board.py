#!/usr/bin/env python3
"""Build a local storyboard board from Storyboard_Image_Jobs.json."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from scriptboard.config import ScriptBoardConfig, load_config


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower() or "scene"


def rel_path(path: str, root: Path) -> str:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return target.as_posix()


def image_src(path: str, root: Path) -> str:
    src = rel_path(path, root)
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    if target.exists():
        src = f"{src}?v={int(target.stat().st_mtime)}"
    return src


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def json_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def multiline_html(value: str) -> str:
    return "<br>".join(esc(line) for line in value.splitlines())


def group_jobs(jobs: list[dict]) -> OrderedDict[str, list[dict]]:
    scenes: OrderedDict[str, list[dict]] = OrderedDict()
    for job in jobs:
        scenes.setdefault(job.get("scene_id", "scene"), []).append(job)
    return scenes


def scene_number(scene_id: str, fallback: int) -> int:
    match = re.match(r"scene_(\d+)_", scene_id)
    return int(match.group(1)) if match else fallback


def panel_card(job: dict, root: Path) -> str:
    image_path = job.get("image_path", "")
    exists = Path(image_path).exists() if image_path else False
    done = job.get("status") == "done" and exists
    status = "done" if done else "pending"
    img = (
        f'<img src="{esc(image_src(image_path, root))}" alt="{esc(job.get("panel_label", "Storyboard panel"))}">'
        if done
        else '<div class="panel-placeholder">Pending image</div>'
    )
    raw_passage = str(job.get("script_passage", ""))
    passage = esc(raw_passage)
    panel_index = int(job.get("panel_index") or 0)
    panel_label = esc(job.get("panel_label") or f"Panel {panel_index}")
    job_id = esc(job.get("id", ""))
    return f"""
          <article class="panel-card {status}" data-status="{status}" data-panel="{panel_index}" data-job-id="{job_id}" data-script-passage="{esc(raw_passage)}">
            <div class="panel-image">
              {img}
              <canvas class="mark-layer" aria-hidden="true"></canvas>
            </div>
            <div class="panel-meta">
              <div class="panel-kicker">Panel {panel_index:03d}<span class="mark-badge" hidden>Annotated</span></div>
              <h3>{panel_label}</h3>
              <div class="script-segment">
                <strong>Script segment</strong>
                <p>{passage}</p>
              </div>
              <div class="panel-actions">
                <button class="annotate-button" data-annotate="true" type="button">Annotate revision</button>
                <button data-clear-panel-annotations="true" type="button">Clear annotations</button>
                <button data-erase-panel="true" type="button">Erase panel</button>
              </div>
            </div>
          </article>"""


def scene_section(scene_id: str, jobs: list[dict], index: int, root: Path) -> str:
    title = jobs[0].get("scene_title") or scene_id.replace("_", " ").title()
    done = sum(1 for job in jobs if job.get("status") == "done" and Path(job.get("image_path", "")).exists())
    total = len(jobs)
    cards = "\n".join(panel_card(job, root) for job in jobs)
    anchor = slug(scene_id)
    return f"""
      <section class="scene" id="{esc(anchor)}" data-scene="{esc(scene_id)}">
        <header class="scene-header">
          <div>
            <span>Scene {scene_number(scene_id, index):03d}</span>
            <h2>{esc(title)}</h2>
          </div>
          <strong>{done}/{total} complete</strong>
        </header>
        <div class="panel-grid">
{cards}
        </div>
      </section>"""


def scene_nav(scenes: OrderedDict[str, list[dict]]) -> str:
    links = []
    for index, (scene_id, jobs) in enumerate(scenes.items(), start=1):
        title = jobs[0].get("scene_title") or scene_id.replace("_", " ").title()
        links.append(f'<a href="#{esc(slug(scene_id))}">{scene_number(scene_id, index):03d} {esc(title)}</a>')
    return "\n".join(links)


def build_html(payload: dict, root: Path, config: ScriptBoardConfig | None = None) -> str:
    config = config or ScriptBoardConfig()
    jobs = payload.get("jobs", [])
    scenes = group_jobs(jobs)
    total = len(jobs)
    done = sum(1 for job in jobs if job.get("status") == "done" and Path(job.get("image_path", "")).exists())
    pending = total - done
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = "\n".join(scene_section(scene_id, scene_jobs, index, root) for index, (scene_id, scene_jobs) in enumerate(scenes.items(), start=1))
    nav = scene_nav(scenes)
    job_lookup = {
        job.get("id", ""): {
            "id": job.get("id", ""),
            "scene_id": job.get("scene_id", ""),
            "scene_title": job.get("scene_title", ""),
            "panel_index": job.get("panel_index", ""),
            "panel_label": job.get("panel_label", ""),
            "script_passage": job.get("script_passage", ""),
            "prompt": job.get("prompt", ""),
            "image_path": job.get("image_path", ""),
        }
        for job in jobs
        if job.get("id")
    }
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(config.board.html_title)}</title>
  <style>
    :root {{
      --paper: #f4f1eb;
      --ink: #1f2523;
      --muted: #6d716b;
      --line: #c9c3b7;
      --rail: #24322f;
      --accent: #b24a34;
      --surface: #fffdf8;
      --shadow: 0 18px 44px rgba(38, 35, 29, .14);
      --panel-min: 280px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(90deg, rgba(36,50,47,.06) 1px, transparent 1px),
        linear-gradient(180deg, rgba(36,50,47,.05) 1px, transparent 1px),
        var(--paper);
      background-size: 28px 28px;
      font-family: Avenir Next, Optima, Trebuchet MS, sans-serif;
    }}
    .shell {{ min-height: 100vh; display: grid; grid-template-columns: 280px 1fr; }}
    aside {{
      position: sticky; top: 0; height: 100vh; overflow: auto;
      padding: 24px 18px; background: var(--rail); color: #f6f1e7;
      border-right: 1px solid rgba(255,255,255,.12);
    }}
    .brand {{ font-family: Georgia, serif; font-size: 28px; line-height: 1; margin: 0 0 18px; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 18px 0; }}
    .stat {{ padding: 10px; border: 1px solid rgba(255,255,255,.18); background: rgba(255,255,255,.06); }}
    .stat strong {{ display: block; font-size: 20px; }}
    .stat span {{ display: block; color: rgba(246,241,231,.72); font-size: 11px; text-transform: uppercase; }}
    .controls {{ display: grid; gap: 12px; margin: 22px 0; }}
    button {{
      border: 1px solid rgba(255,255,255,.2); color: #f6f1e7; background: transparent;
      padding: 10px 12px; text-align: left; cursor: pointer; font: inherit;
    }}
    button.active, button:hover {{ background: rgba(255,255,255,.12); }}
    .panel-actions {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }}
    .panel-actions button {{
      width: 100%; border-color: var(--line); color: var(--ink);
      background: #f7efe4; text-align: center; padding: 8px 10px; font-size: 12px;
    }}
    .panel-actions .annotate-button {{ grid-column: 1 / -1; }}
    .panel-actions button:hover {{ background: #efe0d0; }}
    label {{ display: grid; gap: 8px; color: rgba(246,241,231,.78); font-size: 12px; }}
    input[type="range"] {{ width: 100%; accent-color: var(--accent); }}
    nav {{ display: grid; gap: 6px; padding-top: 10px; }}
    nav a {{ color: rgba(246,241,231,.78); text-decoration: none; font-size: 13px; line-height: 1.25; padding: 7px 0; border-top: 1px solid rgba(255,255,255,.08); }}
    nav a:hover {{ color: #fff; }}
    main {{ padding: 34px; }}
    .topbar {{
      display: flex; align-items: end; justify-content: space-between; gap: 20px;
      padding-bottom: 24px; border-bottom: 2px solid var(--ink);
    }}
    h1 {{ font-family: Georgia, serif; font-size: clamp(36px, 5vw, 68px); line-height: .94; margin: 0; letter-spacing: 0; }}
    .topbar p {{ max-width: 620px; margin: 0; color: var(--muted); line-height: 1.5; }}
    .scene {{ margin: 34px 0 58px; scroll-margin-top: 20px; }}
    .scene-header {{
      display: flex; align-items: end; justify-content: space-between; gap: 18px;
      margin-bottom: 16px; border-bottom: 1px solid var(--line); padding-bottom: 10px;
    }}
    .scene-header span, .panel-kicker {{ color: var(--accent); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; font-weight: 700; }}
    .scene-header h2 {{ margin: 3px 0 0; font-family: Georgia, serif; font-size: 28px; letter-spacing: 0; }}
    .scene-header strong {{ color: var(--muted); font-weight: 600; }}
    .panel-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(var(--panel-min), 1fr)); gap: 18px; align-items: start; }}
    .panel-card {{
      background: var(--surface); border: 1px solid var(--line); box-shadow: var(--shadow);
      display: grid; grid-template-rows: auto 1fr;
    }}
    .panel-image {{ position: relative; aspect-ratio: 3 / 2; background: #ded8ca; overflow: hidden; border-bottom: 1px solid var(--line); }}
    .panel-image img {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
    .mark-layer {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }}
    .panel-placeholder {{ height: 100%; display: grid; place-items: center; color: var(--muted); background: repeating-linear-gradient(-45deg, #e7e1d5 0 12px, #f1ece2 12px 24px); font-weight: 700; }}
    .panel-meta {{ padding: 13px 14px 16px; }}
    .panel-meta h3 {{ margin: 4px 0 8px; font-size: 16px; }}
    .panel-meta p {{ margin: 0; color: var(--muted); font-size: 13px; line-height: 1.42; }}
    .script-segment {{ display: grid; gap: 5px; margin-top: 8px; }}
    .script-segment strong {{ color: var(--ink); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }}
    .mark-badge {{ margin-left: 8px; color: #fff; background: var(--accent); padding: 3px 6px; font-size: 10px; letter-spacing: .04em; }}
    .pending {{ opacity: .72; }}
    .modal-backdrop {{ position: fixed; inset: 0; z-index: 20; display: none; place-items: center; padding: 22px; background: rgba(31,37,35,.62); }}
    .modal-backdrop.open {{ display: grid; }}
    .modal {{
      width: min(1180px, 100%); max-height: min(900px, 94vh); overflow: auto;
      background: var(--surface); border: 1px solid var(--line); box-shadow: var(--shadow);
    }}
    .modal-head, .modal-actions {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid var(--line); }}
    .modal-actions {{ border-top: 1px solid var(--line); border-bottom: 0; flex-wrap: wrap; }}
    .modal h2 {{ margin: 0; font-family: Georgia, serif; font-size: 22px; }}
    .modal button {{ color: var(--ink); border-color: var(--line); background: #f7efe4; text-align: center; }}
    .modal button:hover {{ background: #efe0d0; }}
    .modal button.primary {{ color: #fff; background: var(--rail); }}
    .modal button.danger {{ color: #fff; background: var(--accent); }}
    .annotator {{ display: grid; grid-template-columns: minmax(320px, 3fr) minmax(280px, 2fr); gap: 16px; padding: 16px; }}
    .draw-wrap {{ position: relative; aspect-ratio: 3 / 2; background: #ded8ca; overflow: hidden; border: 1px solid var(--line); }}
    .draw-wrap img {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
    .draw-wrap canvas {{ position: absolute; inset: 0; width: 100%; height: 100%; cursor: crosshair; }}
    .annotator label {{ color: var(--muted); font-size: 12px; }}
    textarea {{ width: 100%; min-height: 160px; resize: vertical; padding: 10px; border: 1px solid var(--line); background: #fff; color: var(--ink); font: inherit; line-height: 1.4; }}
    .prompt-preview {{ max-height: 240px; overflow: auto; white-space: pre-wrap; border: 1px solid var(--line); background: #f7f3eb; color: var(--muted); padding: 10px; font-size: 12px; line-height: 1.4; }}
    .hint {{ margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.35; }}
    body.filter-done .panel-card.pending, body.filter-pending .panel-card.done {{ display: none; }}
    @media (max-width: 860px) {{
      .shell {{ grid-template-columns: 1fr; }}
      aside {{ position: relative; height: auto; }}
      main {{ padding: 22px; }}
      .topbar, .scene-header {{ align-items: start; flex-direction: column; }}
      .annotator {{ grid-template-columns: 1fr; }}
    }}
    @media print {{
      body {{ background: white; }}
      .shell {{ display: block; }}
      aside {{ display: none; }}
      main {{ padding: 0; }}
      .topbar {{ margin-bottom: 20px; }}
      .scene {{ break-after: page; }}
      .panel-card {{ box-shadow: none; break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <p class="brand">{esc(config.board.brand)}</p>
      <div class="stats">
        <div class="stat"><strong>{total}</strong><span>Panels</span></div>
        <div class="stat"><strong>{done}</strong><span>Done</span></div>
        <div class="stat"><strong>{pending}</strong><span>Pending</span></div>
      </div>
      <div class="controls" aria-label="Board controls">
        <button class="active" data-filter="all">Show all panels</button>
        <button data-filter="done">Generated only</button>
        <button data-filter="pending">Pending only</button>
        <button data-print="true">Print board</button>
        <label>Panel width
          <input id="size" type="range" min="220" max="520" value="280">
        </label>
      </div>
      <nav aria-label="Scenes">
{nav}
      </nav>
    </aside>
    <main>
      <header class="topbar">
        <div>
          <h1>{multiline_html(config.board.heading)}</h1>
        </div>
        <p>{esc(config.board.intro)}</p>
      </header>
{sections}
    </main>
  </div>
  <div class="modal-backdrop" id="annotation-modal" role="dialog" aria-modal="true" aria-labelledby="annotation-title">
    <div class="modal">
      <div class="modal-head">
        <h2 id="annotation-title">Panel annotation</h2>
        <button data-close-annotation="true" type="button">Close</button>
      </div>
      <div class="annotator">
        <div>
          <div class="draw-wrap">
            <img id="annotation-image" alt="">
            <canvas id="annotation-canvas"></canvas>
          </div>
          <p class="hint">Click the part of the panel you want to annotate. A red marker circle will appear there; notes and marks are saved in this browser.</p>
        </div>
        <div>
          <label>Revision notes
            <textarea id="annotation-notes" placeholder="{esc(config.board.annotation_placeholder)}"></textarea>
          </label>
          <label>Regeneration prompt
            <div class="prompt-preview" id="prompt-preview"></div>
          </label>
        </div>
      </div>
      <div class="modal-actions">
        <button data-clear-marks="true" type="button">Clear red marks</button>
        <button data-copy-prompt="true" type="button">Copy prompt</button>
        <button data-export-one="true" type="button">Export this panel</button>
        <button data-export-all="true" type="button">Export all annotations</button>
        <button class="primary" data-save-annotation="true" type="button">Save annotation</button>
      </div>
    </div>
  </div>
  <script type="application/json" id="storyboard-jobs">{json_script(job_lookup)}</script>
  <script>
    const jobs = JSON.parse(document.querySelector('#storyboard-jobs').textContent);
    const storageKey = 'storyboard-panel-annotations-v1';
    const erasedStorageKey = 'storyboard-panel-erased-v1';
    let annotations = JSON.parse(localStorage.getItem(storageKey) || '{{}}');
    let erasedPanels = JSON.parse(localStorage.getItem(erasedStorageKey) || '{{}}');
    let currentId = null;

    const buttons = document.querySelectorAll('[data-filter]');
    buttons.forEach((button) => {{
      button.addEventListener('click', () => {{
        buttons.forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        document.body.classList.remove('filter-done', 'filter-pending');
        if (button.dataset.filter !== 'all') {{
          document.body.classList.add(`filter-${{button.dataset.filter}}`);
        }}
      }});
    }});
    document.querySelector('[data-print]').addEventListener('click', () => window.print());
    document.querySelector('#size').addEventListener('input', (event) => {{
      document.documentElement.style.setProperty('--panel-min', `${{event.target.value}}px`);
    }});

    const modal = document.querySelector('#annotation-modal');
    const annotationTitle = document.querySelector('#annotation-title');
    const annotationImage = document.querySelector('#annotation-image');
    const annotationCanvas = document.querySelector('#annotation-canvas');
    const annotationNotes = document.querySelector('#annotation-notes');
    const promptPreview = document.querySelector('#prompt-preview');
    const drawContext = annotationCanvas.getContext('2d');

    function saveAnnotations() {{
      localStorage.setItem(storageKey, JSON.stringify(annotations));
      renderCards();
    }}

    function saveErasedPanels() {{
      localStorage.setItem(erasedStorageKey, JSON.stringify(erasedPanels));
      renderCards();
    }}

    function buildPrompt(job, annotation) {{
      const notes = (annotation?.notes || '').trim();
      const markText = annotation?.marks ? ' Use the attached red marker circle as a visual correction guide; the circled area identifies what needs revision and the red circle must not appear in the final generated image.' : '';
      const noteText = notes ? ` Additional revision notes: ${{notes}}` : '';
      return `${{job.prompt}}${{markText}}${{noteText}}`;
    }}

    function resizeCanvas(canvas) {{
      const rect = canvas.getBoundingClientRect();
      const scale = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * scale));
      canvas.height = Math.max(1, Math.round(rect.height * scale));
      const context = canvas.getContext('2d');
      context.setTransform(scale, 0, 0, scale, 0, 0);
    }}

    function drawStored(canvas, dataUrl) {{
      resizeCanvas(canvas);
      const context = canvas.getContext('2d');
      context.clearRect(0, 0, canvas.width, canvas.height);
      if (!dataUrl) return;
      const image = new Image();
      image.onload = () => {{
        const rect = canvas.getBoundingClientRect();
        context.clearRect(0, 0, rect.width, rect.height);
        context.drawImage(image, 0, 0, rect.width, rect.height);
      }};
      image.src = dataUrl;
    }}

    function renderCards() {{
      document.querySelectorAll('.panel-card').forEach((card) => {{
        if (erasedPanels[card.dataset.jobId]) {{
          card.remove();
          return;
        }}
        const annotation = annotations[card.dataset.jobId];
        const badge = card.querySelector('.mark-badge');
        badge.hidden = !(annotation?.notes || annotation?.marks);
        drawStored(card.querySelector('.mark-layer'), annotation?.marks);
      }});
    }}

    function updatePreview() {{
      if (!currentId) return;
      const job = jobs[currentId];
      const current = {{ ...(annotations[currentId] || {{}}), notes: annotationNotes.value }};
      promptPreview.textContent = buildPrompt(job, current);
    }}

    function openAnnotation(card) {{
      currentId = card.dataset.jobId;
      const job = jobs[currentId];
      const annotation = annotations[currentId] || {{}};
      annotationTitle.textContent = `${{job.scene_title || job.scene_id}} · Panel ${{String(job.panel_index).padStart(3, '0')}}`;
      annotationImage.src = card.querySelector('img')?.getAttribute('src') || '';
      annotationImage.alt = job.panel_label || 'Storyboard panel';
      annotationNotes.value = annotation.notes || '';
      modal.classList.add('open');
      requestAnimationFrame(() => {{
        drawStored(annotationCanvas, annotation.marks);
        updatePreview();
      }});
    }}

    function closeAnnotation() {{
      modal.classList.remove('open');
      currentId = null;
    }}

    function saveCurrent() {{
      if (!currentId) return;
      annotations[currentId] = {{
        ...(annotations[currentId] || {{}}),
        job_id: currentId,
        scene_id: jobs[currentId].scene_id,
        panel_index: jobs[currentId].panel_index,
        notes: annotationNotes.value.trim(),
        prompt: buildPrompt(jobs[currentId], {{ ...(annotations[currentId] || {{}}), notes: annotationNotes.value }}),
        updated_at: new Date().toISOString(),
      }};
      if (!annotations[currentId].notes && !annotations[currentId].marks) {{
        delete annotations[currentId];
      }}
      saveAnnotations();
      updatePreview();
    }}

    function downloadJson(filename, value) {{
      const blob = new Blob([JSON.stringify(value, null, 2) + '\\n'], {{ type: 'application/json' }});
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      link.click();
      URL.revokeObjectURL(link.href);
    }}

    function exportPayload(ids) {{
      return {{
        generated_at: new Date().toISOString(),
        source: 'Storyboard_Board.html local annotations',
        annotations: ids.map((id) => {{
          const job = jobs[id];
          const annotation = annotations[id] || {{}};
          return {{
            job_id: id,
            scene_id: job.scene_id,
            scene_title: job.scene_title,
            panel_index: job.panel_index,
            panel_label: job.panel_label,
            script_passage: job.script_passage,
            image_path: job.image_path,
            notes: annotation.notes || '',
            marked_image_data_url: annotation.marks || '',
            revised_prompt: buildPrompt(job, annotation),
            updated_at: annotation.updated_at || null,
          }};
        }}),
      }};
    }}

    document.querySelectorAll('[data-annotate]').forEach((button) => {{
      button.addEventListener('click', () => openAnnotation(button.closest('.panel-card')));
    }});
    document.querySelectorAll('[data-clear-panel-annotations]').forEach((button) => {{
      button.addEventListener('click', () => {{
        const card = button.closest('.panel-card');
        const jobId = card.dataset.jobId;
        if (!annotations[jobId]) return;
        if (!confirm('Clear annotations for this panel?')) return;
        delete annotations[jobId];
        saveAnnotations();
      }});
    }});
    document.querySelectorAll('[data-erase-panel]').forEach((button) => {{
      button.addEventListener('click', () => {{
        const card = button.closest('.panel-card');
        const jobId = card.dataset.jobId;
        if (!confirm('Remove this panel from the board collection? Resource cleanup is applied by the local cleanup script.')) return;
        erasedPanels[jobId] = {{
          job_id: jobId,
          scene_id: jobs[jobId]?.scene_id || '',
          panel_index: jobs[jobId]?.panel_index || '',
          image_path: jobs[jobId]?.image_path || '',
          erased_at: new Date().toISOString(),
        }};
        delete annotations[jobId];
        saveErasedPanels();
        saveAnnotations();
        card.remove();
      }});
    }});
    document.querySelector('[data-close-annotation]').addEventListener('click', closeAnnotation);
    modal.addEventListener('click', (event) => {{
      if (event.target === modal) closeAnnotation();
    }});
    annotationNotes.addEventListener('input', updatePreview);
    document.querySelector('[data-save-annotation]').addEventListener('click', () => {{
      saveCurrent();
      closeAnnotation();
    }});
    document.querySelector('[data-clear-marks]').addEventListener('click', () => {{
      if (!currentId) return;
      drawStored(annotationCanvas, '');
      if (annotations[currentId]) delete annotations[currentId].marks;
      saveCurrent();
    }});
    document.querySelector('[data-copy-prompt]').addEventListener('click', async () => {{
      saveCurrent();
      await navigator.clipboard.writeText(promptPreview.textContent);
    }});
    document.querySelector('[data-export-one]').addEventListener('click', () => {{
      saveCurrent();
      if (currentId) downloadJson(`storyboard_annotation_${{currentId}}.json`, exportPayload([currentId]));
    }});
    document.querySelector('[data-export-all]').addEventListener('click', () => {{
      saveCurrent();
      downloadJson('Storyboard_Annotations.json', exportPayload(Object.keys(annotations)));
    }});

    function drawMarkerCircle(context, x, y) {{
      context.save();
      context.strokeStyle = '#d12c1f';
      context.lineWidth = 6;
      context.lineCap = 'round';
      context.lineJoin = 'round';
      context.globalAlpha = 0.9;
      context.beginPath();
      context.ellipse(x, y, 38, 25, -0.18, 0.15, Math.PI * 2 - 0.25);
      context.stroke();
      context.beginPath();
      context.ellipse(x + 3, y - 1, 35, 22, -0.05, 0.35, Math.PI * 2 + 0.1);
      context.stroke();
      context.restore();
    }}

    function pointerPoint(event) {{
      const rect = annotationCanvas.getBoundingClientRect();
      return {{ x: event.clientX - rect.left, y: event.clientY - rect.top }};
    }}

    annotationCanvas.addEventListener('pointerdown', (event) => {{
      const point = pointerPoint(event);
      drawStored(annotationCanvas, '');
      drawMarkerCircle(drawContext, point.x, point.y);
      if (!currentId) return;
      annotations[currentId] = {{
        ...(annotations[currentId] || {{}}),
        marks: annotationCanvas.toDataURL('image/png'),
      }};
      saveCurrent();
    }});
    window.addEventListener('resize', renderCards);
    renderCards();
  </script>
</body>
</html>
"""


def build(jobs_path: Path, output_path: Path, config: ScriptBoardConfig | None = None) -> None:
    config = config or ScriptBoardConfig()
    root = jobs_path.parent.resolve()
    payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    output_path.write_text(build_html(payload, root, config), encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Optional ScriptBoard_Config.json path.")
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    config = load_config(args.config, base_dir=Path.cwd())
    jobs_path = (args.jobs or Path(config.outputs.image_jobs)).expanduser()
    if not jobs_path.is_absolute():
        jobs_path = Path.cwd() / jobs_path
    output_path = (args.output or Path(config.outputs.board_html)).expanduser()
    if not output_path.is_absolute():
        output_path = jobs_path.parent / output_path
    if args.config is None:
        config = load_config(None, base_dir=jobs_path.parent)
    build(jobs_path, output_path, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
