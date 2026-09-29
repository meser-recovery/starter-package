"""Isolated 001–006 A/B/C review; never writes the existing full-build artifacts."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import inspect
import json
import math
import shutil
import subprocess
from pathlib import Path

from narration import cached, content_hash, generate, paths, request_body
from validate import ROOT, validate

OUT = ROOT / "generated/pilot"
IDS = ("001-purpose", "002-zoom-multitrack", "003-announcement-benefit",
       "004-speaker-benefit", "005-two-tools", "006-archive-open")
VARIANTS = ("a-current", "b-context", "c-tuned")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def selection(spec: dict) -> list[dict]:
    if tuple(spec["pilot"]["scene_ids"]) != IDS:
        raise RuntimeError("pilot is restricted to scenes 001–006")
    scenes = spec["scenes"][:6]
    if tuple(scene["id"] for scene in scenes) != IDS:
        raise RuntimeError("pilot scene order differs from canonical order")
    if set(spec["pilot"]["variants"]) != set(VARIANTS):
        raise RuntimeError("pilot requires exactly A/B/C")
    for variant in VARIANTS:
        config = spec["pilot"]["variants"][variant]
        if config["context"] != ("none" if variant == "a-current" else "neighbors"):
            raise RuntimeError("A must omit context; B/C must include neighbors")
        if variant != "c-tuned" and config["voice_settings"] is not None:
            raise RuntimeError("only C may override voice settings")
    if set(spec["pilot"]["visual_cues"]) != set(IDS[:5]):
        raise RuntimeError("pilot requires visual cues for exactly scenes 001–005")
    for scene in scenes[:5]:
        previous_index, previous_phase = -1, -1
        for cue in spec["pilot"]["visual_cues"][scene["id"]]:
            text, phase = cue["text"], cue["phase"]
            index = scene["narration"].find(text)
            if index <= previous_index or not previous_phase < phase < 1:
                raise RuntimeError(f"invalid visual cue: {scene['id']} {text}")
            previous_index, previous_phase = index, phase
    return scenes


def parameters(spec: dict, variant: str, scene: dict) -> tuple[dict, dict]:
    config = spec["pilot"]["variants"][variant]
    settings = {**spec["narration"]}
    if config["voice_settings"] is not None:
        settings["voice_settings"] = config["voice_settings"]
    context = {}
    if config["context"] == "neighbors":
        index = next(i for i, item in enumerate(spec["scenes"]) if item["id"] == scene["id"])
        if index:
            context["previous_text"] = spec["scenes"][index - 1]["narration"]
        if index + 1 < len(spec["scenes"]):
            context["next_text"] = spec["scenes"][index + 1]["narration"]
    return settings, context


def timing_for(spec: dict, variant: str, scene: dict) -> dict:
    settings, context = parameters(spec, variant, scene)
    timing = cached(scene, settings, context=context, cache_dir=OUT / variant / "narration")
    if not timing:
        raise RuntimeError(f"pilot narration missing/stale: {variant}/{scene['id']}")
    return timing


def preserve(spec: dict, *, initialize: bool = False) -> dict:
    path = OUT / "preservation-baseline.json"
    if not path.exists():
        if not initialize:
            raise RuntimeError("pilot preservation baseline missing")
        files = {str(p.relative_to(ROOT / "generated")):
                 {"sha256": sha(p), "mtime_ns": p.stat().st_mtime_ns}
                 for p in (ROOT / "generated").rglob("*") if p.is_file() and not p.is_relative_to(OUT)}
        write_json(path, {"repo_head": head(), "scenes_007_060": spec["scenes"][6:], "files": files})
    baseline = json.loads(path.read_text())
    if spec["scenes"][6:] != baseline["scenes_007_060"]:
        raise RuntimeError("pilot changed scenes 007–060")
    actual = {str(p.relative_to(ROOT / "generated")) for p in (ROOT / "generated").rglob("*")
              if p.is_file() and not p.is_relative_to(OUT)}
    if actual != set(baseline["files"]):
        raise RuntimeError("pilot added/removed artifacts outside its output directory")
    for name, expected in baseline["files"].items():
        p = ROOT / "generated" / name
        if not p.is_file() or sha(p) != expected["sha256"] or p.stat().st_mtime_ns != expected["mtime_ns"]:
            raise RuntimeError(f"pilot modified protected artifact: {name}")
    return {"status": "PASS", "protected_files": len(baseline["files"]),
            "scenes_007_060_unchanged": True, "sha256_and_mtime_unchanged": True,
            "baseline_head": baseline["repo_head"]}


def head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def plan(spec: dict) -> dict:
    rows = []
    for variant in VARIANTS:
        for scene in selection(spec):
            settings, context = parameters(spec, variant, scene)
            hit = cached(scene, settings, context=context, cache_dir=OUT / variant / "narration")
            legacy = cached(scene, settings) if variant == "a-current" else None
            visual = visual_cached(spec, variant, scene, hit or legacy) if hit or legacy else None
            rows.append({"variant": variant, "scene": scene["id"],
                         "cache": "HIT" if hit else "REUSE_CURRENT" if legacy else "MISS",
                         "characters_to_generate": 0 if hit or legacy else len(scene["narration"]),
                         "narration_hash": content_hash(scene, settings, context),
                         "context_fields": list(context),
                         "visual_cache": "HIT" if visual else "MISS",
                         "visual_recapture": not bool(visual),
                         "outputs": [str(OUT / variant / folder / f"{scene['id']}{suffix}")
                                     for folder, suffix in (("narration", ".mp3"), ("narration", ".timing.json"),
                                                            ("visuals", ".mp4"), ("clips", ".mp4"))]})
    return {"selected_scenes": list(IDS), "outputs_root": str(OUT), "scenes": rows,
            "characters_to_generate": sum(row["characters_to_generate"] for row in rows),
            "assembly_outputs": [str(OUT / variant / name) for variant in VARIANTS
                                 for name in ("pilot.mp4", "pilot.m4a", "pilot.ru.srt", "pilot.ru.vtt")] +
                                [str(OUT / name) for name in ("index.html", "manifest.json", "verification.json")]}


def narrate(spec: dict) -> None:
    ledger_path = OUT / "generation-ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    for variant in VARIANTS:
        folder = OUT / variant / "narration"
        folder.mkdir(parents=True, exist_ok=True)
        for scene in selection(spec):
            settings, context = parameters(spec, variant, scene)
            reused = False
            if variant == "a-current" and not cached(scene, settings, cache_dir=folder) and cached(scene, settings):
                for source, dest in zip(paths(scene), paths(scene, folder)):
                    shutil.copy2(source, dest)
                reused = True
            info, status = generate(scene, settings, context=context, cache_dir=folder)
            key = f"{variant}/{scene['id']}"
            row = {"variant": variant, "scene": scene["id"], "duration_seconds": info["duration_seconds"],
                   "narration_hash": info["narration_hash"], "voice_id": settings["voice_id"],
                   "output_format": settings["output_format"], "request": request_body(scene, settings, context),
                   "cache": "REUSED_CURRENT" if reused else status}
            if key not in ledger or ledger[key]["narration_hash"] != info["narration_hash"]:
                ledger[key] = row
            write_json(ledger_path, ledger)
            print(json.dumps({k: row[k] for k in ("variant", "scene", "cache", "duration_seconds")}), flush=True)


def cue_times(spec: dict, scene: dict, timing: dict) -> list[tuple[float, float]]:
    cues = [(0.0, 0.0)]
    starts = timing["alignment"]["character_start_times_seconds"]
    for cue in spec["pilot"]["visual_cues"][scene["id"]]:
        index = scene["narration"].index(cue["text"])
        cues.append((scene["padding"]["head"] + starts[index], cue["phase"]))
    cues.append((scene["padding"]["head"] + timing["duration_seconds"], 1.0))
    return cues


def phase_at(seconds: float, cues: list[tuple[float, float]]) -> float:
    for (a, start), (b, end) in zip(cues, cues[1:]):
        if seconds <= b:
            return start + (end - start) * max(0, (seconds - a) / max(.001, b - a))
    return 1.0


def archive_source(spec: dict) -> tuple[Path, dict]:
    from browser_capture import visual_hash
    from capture import output_paths, probe
    scene = selection(spec)[-1]
    source, meta_path = output_paths(scene)
    if not source.is_file() or not meta_path.is_file():
        raise RuntimeError("pilot needs the existing validated scene 006 local capture")
    meta = json.loads(meta_path.read_text())
    if (meta["visual_hash"] != visual_hash(scene) or meta["expected_state"] != "PASS"
            or meta["browser_errors"] or meta["production_mutation_requests"]):
        raise RuntimeError("existing scene 006 capture failed validation")
    probe(source)
    return source, meta


def visual_identity(spec: dict, variant: str, scene: dict, timing: dict) -> str:
    source, _ = archive_source(spec)
    payload = {"scene": scene, "visual_cues": spec["pilot"]["visual_cues"].get(scene["id"]),
               "html_sha256": sha(ROOT / spec["pilot"]["visual_source"]),
               "renderer_sha256": hashlib.sha256("\n".join(inspect.getsource(fn) for fn in
                   (render, cue_times, phase_at, archive_source)).encode()).hexdigest(),
               "archive_capture_sha256": sha(source),
               "narration_hash": timing["narration_hash"], "alignment": timing["alignment"],
               "duration_seconds": timing["duration_seconds"], "fps": 30, "resolution": [1920, 1080]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def visual_cached(spec: dict, variant: str, scene: dict, timing: dict) -> dict | None:
    from capture import probe
    path = OUT / variant / "visuals" / f"{scene['id']}.mp4"
    try:
        meta = json.loads(path.with_suffix(".json").read_text())
        if (meta["visual_hash"] == visual_identity(spec, variant, scene, timing)
                and meta["sha256"] == sha(path) and meta["browser_errors"] == 0
                and probe(path)["duration_seconds"] >= timing["duration_seconds"] + sum(scene["padding"].values()) - .04):
            return meta
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError):
        pass
    return None


async def render(spec: dict) -> None:
    from playwright.async_api import async_playwright
    from capture import probe
    source, source_meta = archive_source(spec)
    bridge = OUT / "archive-first-frame.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
                    "-frames:v", "1", str(bridge)], check=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        async def block(route):
            errors.append("unexpected network request in procedural pilot")
            await route.abort()
        await page.route("http://**/*", block)
        await page.route("https://**/*", block)
        await page.goto((ROOT / spec["pilot"]["visual_source"]).as_uri() + "?capture")
        await page.evaluate("data => window.setTransition(data)",
                            "data:image/jpeg;base64," + base64.b64encode(bridge.read_bytes()).decode())
        for variant in VARIANTS:
            for scene in selection(spec):
                timing = timing_for(spec, variant, scene)
                if visual_cached(spec, variant, scene, timing):
                    print(json.dumps({"visual": f"{variant}/{scene['id']}", "cache": "HIT"}), flush=True)
                    continue
                target = math.ceil((timing["duration_seconds"] + sum(scene["padding"].values())) * 30) / 30
                dest = OUT / variant / "visuals" / f"{scene['id']}.mp4"
                dest.parent.mkdir(parents=True, exist_ok=True)
                candidate = dest.with_suffix(".tmp.mp4")
                codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an"]
                if scene["id"] == IDS[-1]:
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vf",
                                    f"tpad=stop_mode=clone:stop_duration={target},fps=30", "-t", str(target),
                                    *codec, str(candidate)], check=True)
                else:
                    cues = cue_times(spec, scene, timing)
                    process = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", "30",
                        "-vcodec", "mjpeg", "-i", "pipe:0", *codec, str(candidate),
                        stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    try:
                        for frame in range(round(target * 30)):
                            second = frame / 30
                            blend = max(0.0, (second - (target - .65)) / .65) if scene["id"] == IDS[4] else 0
                            data = await page.evaluate("args => window.frameJpeg(...args)",
                                                       [scene["id"][:3], phase_at(second, cues), blend])
                            process.stdin.write(base64.b64decode(data))
                            await process.stdin.drain()
                        process.stdin.close()
                        error = await process.stderr.read()
                        if await process.wait():
                            raise RuntimeError(f"pilot render ffmpeg failed: {error.decode()[:500]}")
                    finally:
                        if process.returncode is None:
                            process.kill()
                            await process.wait()
                if errors:
                    raise RuntimeError(f"pilot browser errors: {errors}")
                info = probe(candidate)
                candidate.replace(dest)
                write_json(dest.with_suffix(".json"), {"scene_id": scene["id"], "variant": variant,
                    "visual_hash": visual_identity(spec, variant, scene, timing), "sha256": sha(dest),
                    **info, "browser_errors": len(errors), "production_mutation_requests": 0,
                    "source": "validated-local-browser-capture" if scene["id"] == IDS[-1] else "procedural-canvas",
                    "source_capture_sha256": sha(source), "source_browser_evidence": source_meta if scene["id"] == IDS[-1] else None})
                print(json.dumps({"visual": f"{variant}/{scene['id']}", "cache": "MISS", "duration_seconds": target}), flush=True)
        await browser.close()


def subtitle_files(folder: Path, all_cues: list) -> None:
    from assemble import timestamp
    (folder / "pilot.ru.srt").write_text("\n\n".join(
        f"{i}\n{timestamp(a, True)} --> {timestamp(b, True)}\n{text}"
        for i, (a, b, text) in enumerate(all_cues, 1)) + "\n")
    (folder / "pilot.ru.vtt").write_text("WEBVTT\n\n" + "\n\n".join(
        f"{timestamp(a, False)} --> {timestamp(b, False)}\n{text}" for a, b, text in all_cues) + "\n")


def assemble(spec: dict) -> None:
    from assemble import cues, duration, ffprobe
    manifest = {"kind": "pilot-only", "scene_ids": list(IDS), "repo_head_at_assembly": head(),
                "canonical_pack_sha256": spec["tutorial"]["canonical_content"]["sha256"],
                "tutorial_yaml_sha256": sha(ROOT / "tutorial.yaml"), "variants": {},
                "preservation": preserve(spec), "winner": None}
    for variant in VARIANTS:
        folder = OUT / variant
        rows, all_cues, offset = [], [], 0.0
        for scene in selection(spec):
            timing = timing_for(spec, variant, scene)
            meta = visual_cached(spec, variant, scene, timing)
            if not meta:
                raise RuntimeError(f"pilot visual stale: {variant}/{scene['id']}")
            visual = folder / "visuals" / f"{scene['id']}.mp4"
            mp3, _ = paths(scene, folder / "narration")
            clip = folder / "clips" / f"{scene['id']}.mp4"
            clip.parent.mkdir(exist_ok=True)
            candidate = clip.with_suffix(".tmp.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(visual), "-i", str(mp3),
                "-filter_complex", f"[1:a]adelay={round(scene['padding']['head'] * 1000)}:all=1,apad[a]",
                "-map", "0:v", "-map", "[a]", "-t", str(meta["duration_seconds"]), "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", str(candidate)], check=True)
            candidate.replace(clip)
            length = duration(ffprobe(clip))
            all_cues.extend(cues(scene, timing, offset))
            settings, context = parameters(spec, variant, scene)
            rows.append({"id": scene["id"], "start_seconds": offset, "duration_seconds": length,
                         "narration_seconds": timing["duration_seconds"], "narration_hash": timing["narration_hash"],
                         "clip": str(clip.relative_to(OUT)), "clip_sha256": sha(clip),
                         "visual_hash": meta["visual_hash"], "request": request_body(scene, settings, context)})
            offset += length
        concat = folder / "concat.txt"
        concat.write_text("".join(f"file 'clips/{scene['id']}.mp4'\n" for scene in selection(spec)))
        movie = folder / "pilot.mp4"
        candidate = folder / "pilot.tmp.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "1", "-i", str(concat),
                        "-c", "copy", "-movflags", "+faststart", str(candidate)], check=True)
        decode(candidate)
        candidate.replace(movie)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(movie), "-vn", "-c:a", "copy",
                        "-movflags", "+faststart", str(folder / "pilot.m4a")], check=True)
        subtitle_files(folder, all_cues)
        manifest["variants"][variant] = {"settings": parameters(spec, variant, selection(spec)[0])[0],
            "context_mode": spec["pilot"]["variants"][variant]["context"], "scenes": rows,
            "duration_seconds": duration(ffprobe(movie)), "mp4_sha256": sha(movie),
            "audio_sha256": sha(folder / "pilot.m4a"), "subtitle_cues": len(all_cues),
            "subtitle_sha256": {ext: sha(folder / f"pilot.ru.{ext}") for ext in ("srt", "vtt")}}
        print(json.dumps({"assembled": variant, "duration_seconds": manifest["variants"][variant]["duration_seconds"]}), flush=True)
    write_json(OUT / "manifest.json", manifest)
    review(spec, manifest)


def decode(path: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def review(spec: dict, manifest: dict) -> None:
    descriptions = {
        "a-current": "Прежний способ · без соседнего контекста. Сцены 002–006 взяты из валидного cache; вступление обновлено.",
        "b-context": "Те же голос, модель и текст · previous_text / next_text для каждого фрагмента.",
        "c-tuned": "Те же голос, модель и текст · контекст и один фиксированный набор voice settings."}
    cards = ""
    for variant in VARIANTS:
        label = spec["pilot"]["variants"][variant]["label"]
        data = manifest["variants"][variant]
        cards += f'''<section class="variant"><h2>{label}</h2><p>{descriptions[variant]}</p>
        <audio controls preload="metadata" aria-label="{label}: весь пилот" src="{variant}/pilot.m4a"></audio>
        <p class="meta">{data['duration_seconds']:.2f} сек · шесть сцен</p>
        <video controls preload="metadata" playsinline aria-label="{label}: видео" data-variant="{variant}" src="{variant}/pilot.mp4">
        <track kind="subtitles" srclang="ru" label="Русский" src="{variant}/pilot.ru.vtt"></video>
        <p><a href="{variant}/pilot.mp4" download>MP4</a> · <a href="{variant}/pilot.m4a" download>Аудио</a> ·
        <a href="{variant}/pilot.ru.srt" download>SRT</a></p></section>'''
    titles = ["Вступление", "Поканальная запись Zoom", "Материал для анонс-мейкера", "Обработка отдельных дорожек",
              "Архив и редактор", "Настоящий интерфейс Архива"]
    scene_rows = ""
    for index, scene in enumerate(selection(spec)):
        buttons = " ".join(f'<button type="button" data-listen="{variant}" data-scene="{index}">{variant[0].upper()} · слушать</button>' for variant in VARIANTS)
        scene_rows += f'<tr><th scope="row">{scene["id"][:3]} · {titles[index]}</th><td>{buttons}</td></tr>'
    report = {"voice_id": spec["narration"]["voice_id"], "model_id": spec["narration"]["model_id"],
              "output_format": spec["narration"]["output_format"],
              "C_voice_settings": spec["pilot"]["variants"]["c-tuned"]["voice_settings"]}
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Мэсэр · A/B/C pilot review</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f1f5fa;color:#142e40;font:17px/1.55 system-ui,sans-serif}
    main{max-width:1540px;margin:auto;padding:40px 28px}h1{font-size:clamp(28px,4vw,48px);line-height:1.15;margin:10px 0 24px}
    h2{font-size:23px}a{color:#0665c9}button,a{touch-action:manipulation}button{cursor:pointer;border:1px solid #b9cbda;background:white;color:#142e40;border-radius:8px;padding:9px 13px;font:inherit;margin:4px}
    button:focus-visible,a:focus-visible{outline:3px solid #087df1;outline-offset:3px}.eyebrow{letter-spacing:.12em;font-size:13px;font-weight:700;color:#526b80}
    .intro{max-width:920px}.variants{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;margin:32px 0}.variant{padding:24px;border:1px solid #d6e1eb;border-radius:16px;background:white}.variant p{min-height:80px}.variant .meta{min-height:0;color:#536d80;font-size:14px}audio,video{display:block;width:100%;max-width:100%;margin:14px 0}video{aspect-ratio:16/9;background:#102d40;border-radius:9px}.variant p:last-child{min-height:0}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:14px;border-bottom:1px solid #d6e1eb}th{font-weight:500}pre{overflow:auto;padding:20px;background:#e6eef6;border-radius:10px}summary{cursor:pointer;font-weight:650}.note{max-width:1000px;color:#4f687b}#now{min-height:1.6em}details{margin:24px 0}@media(max-width:1000px){.variants{grid-template-columns:1fr}.variant p{min-height:0}main{padding:24px 16px}th,td{display:block}}
    </style><main><div class="eyebrow">МЭСЭР / S11 / PILOT 001–006</div><h1>Один рассказ. Три варианта подачи.</h1>
    <p class="intro">Сначала прослушайте A, B и C целиком. Сравните интонацию и переходы между сценами. Затем посмотрите те же фрагменты с новыми визуальными объяснениями. Все варианты содержат одинаковый утверждённый текст и одинаковые визуальные действия, привязанные к своей озвучке.</p>
    <p class="note">Победитель не выбран. A/B используют прежние настройки запроса без явного voice_settings; исторические значения настроек голоса на стороне ElevenLabs в старом cache не сохранены. C использует параметры ниже.</p>
    <div class="variants">''' + cards + '''</div><h2>Сравнить одну сцену</h2><p id="now" role="status" aria-live="polite">Выберите сцену и вариант.</p>
    <table><caption>Переход к одной сцене в полной аудиодорожке; воспроизведение продолжается через её границу.</caption><tbody>''' + scene_rows + '''</tbody></table>
    <details><summary>Параметры озвучки и границы проверки</summary><pre>''' + html.escape(json.dumps(report, ensure_ascii=False, indent=2)) + '''</pre>
    <p>Endpoint: text-to-speech/{voice_id}/with-timestamps. B/C получают соседние фрагменты через previous_text и next_text; они не входят в произносимый text. Для 001 предыдущего текста нет; для 006 следующий контекст — текст 007. Аудио 007 не генерировалось.</p>
    <p>Все 18 alignment проверены на точное соответствие narration. Естественность и предпочтение оценивает слушатель; автоматическая проверка текста не заменяет прослушивание.</p>
    <p>C: stability 0.45 — умеренная вариативность; similarity_boost 0.75; style 0.0; use_speaker_boost true; speed 0.96 — немного более спокойный темп. Это проверяемый вариант, а не утверждённое улучшение.</p>
    <p><a href="https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps">ElevenLabs: параметры контекста</a></p></details>
    <h2>Визуальная проверка</h2><p><a href="visuals.html">Открыть анимации со scrubber</a> · <a href="manifest.json">Manifest</a> · <a href="generation-ledger.json">Запросы и cache</a> · <a href="verification.json">Проверки</a></p>
    <p class="note">Сцена 005 плавно переходит к реальному интерфейсу из проверенного локального capture 006. Старый полный ролик и все его артефакты сохранены без изменений и относятся к прежней версии вступления. Production не использовался.</p>
    </main><script>const manifest=MANIFEST;document.querySelectorAll('audio,video').forEach(media=>media.addEventListener('play',()=>document.querySelectorAll('audio,video').forEach(other=>{if(other!==media)other.pause()})));
    document.querySelectorAll('[data-listen]').forEach(button=>button.addEventListener('click',async()=>{const variant=button.dataset.listen,index=Number(button.dataset.scene);const audio=document.querySelector(`audio[src="${variant}/pilot.m4a"]`);audio.currentTime=manifest.variants[variant].scenes[index].start_seconds;try{await audio.play();document.querySelector('#now').textContent=`${variant.toUpperCase()} · ${manifest.variants[variant].scenes[index].id}`}catch{document.querySelector('#now').textContent='Нажмите Play в выбранном аудиоплеере.'}}));</script></html>'''
    # Only the short seek map is embedded in HTML; full request evidence stays in the manifest.
    seek_map = {"variants": {variant: {"scenes": [{"id": row["id"], "start_seconds": row["start_seconds"]}
                                                   for row in manifest["variants"][variant]["scenes"]]}
                            for variant in VARIANTS}}
    page = page.replace("MANIFEST", json.dumps(seek_map).replace("<", "\\u003c"))
    (OUT / "index.html").write_text(page)
    shutil.copy2(ROOT / spec["pilot"]["visual_source"], OUT / "visuals.html")


def verify(spec: dict) -> dict:
    from assemble import ffprobe
    manifest = json.loads((OUT / "manifest.json").read_text())
    if manifest["scene_ids"] != list(IDS) or set(manifest["variants"]) != set(VARIANTS):
        raise RuntimeError("pilot manifest coverage differs")
    if manifest["tutorial_yaml_sha256"] != sha(ROOT / "tutorial.yaml"):
        raise RuntimeError("pilot manifest does not match executable source")
    for variant in VARIANTS:
        row = manifest["variants"][variant]
        if [scene["id"] for scene in row["scenes"]] != list(IDS):
            raise RuntimeError("pilot variant scene coverage differs")
        for scene, recorded in zip(selection(spec), row["scenes"]):
            timing = timing_for(spec, variant, scene)
            visual = visual_cached(spec, variant, scene, timing)
            if (not visual or recorded["visual_hash"] != visual["visual_hash"] or
                    recorded["narration_hash"] != timing["narration_hash"] or
                    recorded["clip_sha256"] != sha(OUT / recorded["clip"])):
                raise RuntimeError("pilot scene artifact/hash mismatch")
        movie = OUT / variant / "pilot.mp4"
        if row["mp4_sha256"] != sha(movie) or row["audio_sha256"] != sha(OUT / variant / "pilot.m4a"):
            raise RuntimeError("pilot final media hash mismatch")
        for ext in ("srt", "vtt"):
            if row["subtitle_sha256"][ext] != sha(OUT / variant / f"pilot.ru.{ext}"):
                raise RuntimeError("pilot subtitle hash mismatch")
        streams = ffprobe(movie)["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        audio = next(s for s in streams if s["codec_type"] == "audio")
        if (video["codec_name"], video["width"], video["height"], video["r_frame_rate"], audio["codec_name"]) != (
                "h264", 1920, 1080, "30/1", "aac"):
            raise RuntimeError("pilot output codec/format mismatch")
        decode(movie)
    result = {"status": "PASS", "checked_commit_sha": head(), "variants": 3, "scene_artifacts": 18,
              "exact_spoken_text_alignment": "PASS", "full_decode": "PASS", "winner": None,
              "preservation": preserve(spec)}
    write_json(OUT / "verification.json", result)
    return result


def run(mode: str, spec: dict) -> None:
    selection(spec)
    if mode == "validate":
        print(json.dumps({**validate(), "pilot_scenes": list(IDS)}))
        return
    if mode == "dry-run":
        print(json.dumps(plan(spec), ensure_ascii=False, indent=2))
        return
    preserve(spec, initialize=mode != "verify")
    if mode in ("narration", "all"):
        narrate(spec)
    if mode in ("visual", "all"):
        asyncio.run(render(spec))
    if mode in ("assemble", "all"):
        assemble(spec)
    if mode in ("verify", "all"):
        print(json.dumps(verify(spec), ensure_ascii=False, indent=2))
    print(json.dumps({"preservation": preserve(spec)}), flush=True)
