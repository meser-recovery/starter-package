#!/usr/bin/env python3
"""Measure the real browser Speaker pipeline against local synthetic/user files."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


PROBE = """(() => {
  window.renderBenchmark = {operations: [], pending: new Map(), stages: []};
  const NativeWorker = window.Worker;
  window.Worker = class extends NativeWorker {
    constructor(...args) {
      super(...args);
      this.probeId = window.renderBenchmark.operations.filter(item => item.type === 'WORKER').length + 1;
      window.renderBenchmark.operations.push({type:'WORKER',worker:this.probeId,at:performance.now()});
      this.addEventListener('message', ({data}) => {
        const pending = window.renderBenchmark.pending.get(data.id);
        if (!pending) return;
        window.renderBenchmark.operations.push({...pending,completedAt:performance.now(),durationMs:performance.now()-pending.startedAt});
        window.renderBenchmark.pending.delete(data.id);
      });
    }
    postMessage(message, ...args) {
      window.renderBenchmark.pending.set(message.id, {type:message.type,worker:this.probeId,path:message.data?.path,
        args:message.data?.args,startedAt:performance.now()});
      return super.postMessage(message, ...args);
    }
  };
  document.addEventListener('DOMContentLoaded', () => {
    const status = document.getElementById('speaker-editor-render-status');
    if (status) new MutationObserver(() => window.renderBenchmark.stages.push({at:performance.now(),text:status.textContent}))
      .observe(status,{childList:true,subtree:true});
  });
})();"""


def summarize_operations(operations):
    completed = [item for item in operations if "durationMs" in item]
    def durations(kind, predicate=lambda item: True):
        return [round(item["durationMs"], 1) for item in completed if item["type"] == kind and predicate(item)]
    is_analysis = lambda item: any("print_format=json" in str(arg) for arg in (item.get("args") or []))
    is_final = lambda item: item.get("args") and "-filter_complex_script" in item["args"]
    is_waveform = lambda item: item.get("args") and "speaker-waveform.rgba" in item["args"]
    return {
        "engineLoadMs": durations("LOAD"),
        "inputWriteMs": durations("WRITE_FILE", lambda item: str(item.get("path") or "").startswith("speaker-input-")),
        "analysisExecMs": durations("EXEC", is_analysis),
        "finalExecMs": durations("EXEC", is_final),
        "waveformExecMs": durations("EXEC", is_waveform),
        "resultReadMs": durations("READ_FILE", lambda item: item.get("path") == "speaker-output.mp3"),
    }


def summarize_stages(stages):
    result = []
    first = stages[0]["at"] if stages else 0
    for item in stages:
        label = re.sub(r" Прошло \d+(?:\.\d+)? с\.$", "", item["text"])
        if result and result[-1]["label"] == label:
            result[-1]["lastAtMs"] = round(item["at"] - first, 1)
            continue
        result.append({"label": label, "firstAtMs": round(item["at"] - first, 1),
                       "lastAtMs": round(item["at"] - first, 1)})
    return result


def run_benchmark(base_url, inputs, label):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
        context.add_init_script(PROBE)
        site = urlparse(base_url)
        context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc == site.netloc else route.abort())
        page = context.new_page(); errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base_url.rstrip("/") + "/Audio-Editor.html")
        page.locator("#source-session-mode-device").click()
        page.locator("#processor-file").set_input_files([str(path) for path in inputs])
        page.locator("#open-local-speaker").click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=900000)
        for index in range(len(inputs)):
            row = page.locator(".speaker-track").nth(index)
            row.locator('[data-dsp-field="enhancement"]').check()
            row.locator('[data-dsp-field="leveling"]').check()
            compression = row.locator('[data-dsp-field="compression"]')
            compression.fill("1"); compression.dispatch_event("change")

        runs = []
        for temperature in ("cold", "warm"):
            marker = page.evaluate("window.renderBenchmark.operations.length")
            stage_marker = page.evaluate("window.renderBenchmark.stages.length")
            heap_before = page.evaluate("performance.memory?.usedJSHeapSize ?? null")
            started = page.evaluate("performance.now()")
            page.locator("#speaker-editor-render").click()
            page.get_by_text("Финальная версия готова. В архив ничего не передавалось.", exact=True).wait_for(timeout=1800000)
            elapsed = page.evaluate("started => performance.now() - started", started)
            result = page.evaluate("""async values => {
              const state=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
              const bytes=new Uint8Array(await state.candidate.blob.arrayBuffer());
              const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
              return {operations:window.renderBenchmark.operations.slice(values.marker),
                stages:window.renderBenchmark.stages.slice(values.stageMarker), profile:state.renderProfile,
                result:{sizeBytes:bytes.length,sha256:hash,durationSeconds:state.candidate.resultDurationSeconds},
                heapAfter:performance.memory?.usedJSHeapSize ?? null};
            }""", {"marker": marker, "stageMarker": stage_marker})
            runs.append({
                "temperature": temperature,
                "wallMs": round(elapsed, 1),
                "usedJsHeapBytesBefore": heap_before,
                "usedJsHeapBytesAfter": result["heapAfter"],
                "workerOperations": summarize_operations(result["operations"]),
                "stages": summarize_stages(result["stages"]),
                "applicationProfile": result["profile"],
                "result": result["result"],
            })
        result = {"label": label, "browser": browser.version, "baseUrl": base_url,
                  "inputs": [{"name": path.name, "sizeBytes": path.stat().st_size} for path in inputs],
                  "runs": runs, "pageErrors": errors}
        context.close(); browser.close()
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.base_url, args.input, args.label)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text, flush=True)
    if result["pageErrors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
