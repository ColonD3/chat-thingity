#!/usr/bin/env python3
import json
import os
import subprocess
import base64
import ssl
import urllib.request
import urllib.error
import urllib.parse
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = "127.0.0.1"
PORT = 8791


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def do_GET(self):
        if self.path == "/api/health":
            self._send_json(200, {"ok": True, "service": "terminal_api"})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/api/image/pollinations":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                prompt = (data.get("prompt") or "").strip()
                model = (data.get("model") or "flux").strip()
                seed = int(data.get("seed") or 0) or 1
                if not prompt:
                    self._send_json(400, {"error": "Missing prompt"})
                    return
                encoded_prompt = urllib.parse.quote(prompt, safe="")
                encoded_model = urllib.parse.quote(model, safe="")
                url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model={encoded_model}&nologo=true&seed={seed}"
                def fetch_image(fetch_url):
                    with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                        curl_cmd = [
                            "curl",
                            "-L",
                            "--fail",
                            "--silent",
                            "--show-error",
                            "--max-time",
                            "60",
                            "-A",
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                            url if fetch_url is None else fetch_url,
                            "-o",
                            tmp.name,
                        ]
                        result = subprocess.run(curl_cmd, capture_output=True, text=True)
                        if result.returncode != 0:
                            raise RuntimeError(result.stderr.strip() or f"curl exited {result.returncode}")
                        tmp.seek(0)
                        return tmp.read()

                def compress_prompt(text):
                    words = [w for w in text.replace(",", " ").split() if w]
                    stop = {
                        "a", "an", "the", "and", "or", "of", "in", "on", "with", "to", "for", "at",
                        "from", "by", "about", "into", "over", "under", "near", "a", "an",
                        "cinematic", "dramatic", "detailed", "beautiful", "highly", "detailed"
                    }
                    kept = [w for w in words if w.lower() not in stop]
                    if not kept:
                        kept = words
                    if "selfie" in text.lower():
                        base = ["selfie", "portrait"]
                    elif "portrait" in text.lower():
                        base = ["portrait"]
                    else:
                        base = []
                    condensed = base + kept[:6]
                    return " ".join(condensed).strip()[:120]

                try:
                    image_bytes = fetch_image(url)
                except Exception as first_error:
                    short_prompt = compress_prompt(prompt)
                    short_encoded = urllib.parse.quote(short_prompt, safe="")
                    short_url = f"https://image.pollinations.ai/prompt/{short_encoded}?nologo=true&seed={seed}"
                    time.sleep(1.5)
                    try:
                        image_bytes = fetch_image(short_url)
                    except Exception:
                        raise first_error
                content_type = "image/jpeg"
                b64 = base64.b64encode(image_bytes).decode("ascii")
                image_url = f"data:{content_type};base64,{b64}"
                self._send_json(200, {"ok": True, "image_url": image_url, "model": model})
            except Exception as exc:
                self._send_json(502, {"error": f"Pollinations image failed: {exc}"})
            return

        if self.path == "/api/image/local-sdxl/health":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                base_url = (data.get("base_url") or "http://127.0.0.1:7860").rstrip("/")
                req = urllib.request.Request(
                    f"{base_url}/sdapi/v1/options",
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=10):
                    pass
                self._send_json(200, {"ok": True, "base_url": base_url})
            except Exception as exc:
                self._send_json(502, {"error": f"Could not reach local SD API: {exc}"})
            return

        if self.path == "/api/image/local-sdxl":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                prompt = (data.get("prompt") or "").strip()
                model = (data.get("model") or "sdxl").strip()
                base_url = (data.get("base_url") or "http://127.0.0.1:7860").rstrip("/")
                width = int(data.get("width") or 1024)
                height = int(data.get("height") or 1024)
                steps = int(data.get("steps") or 28)
                if not prompt:
                    self._send_json(400, {"error": "Missing prompt"})
                    return

                payload = {
                    "prompt": prompt,
                    "width": max(256, min(width, 1536)),
                    "height": max(256, min(height, 1536)),
                    "steps": max(10, min(steps, 60)),
                    "sampler_name": "DPM++ 2M Karras",
                    "cfg_scale": 7,
                    "override_settings": {"sd_model_checkpoint": model},
                    "override_settings_restore_afterwards": True,
                }
                req = urllib.request.Request(
                    f"{base_url}/sdapi/v1/txt2img",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=180) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                image_b64 = (raw.get("images") or [None])[0]
                if not image_b64:
                    self._send_json(502, {"error": "No image returned from local SD API"})
                    return
                image_url = f"data:image/png;base64,{image_b64}"
                self._send_json(200, {"ok": True, "image_url": image_url, "model": model})
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="ignore")
                self._send_json(502, {"error": f"Local SD API HTTP {exc.code}: {details}"})
            except Exception as exc:
                self._send_json(502, {"error": f"Local SD generation failed: {exc}"})
            return

        if self.path != "/api/run":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            command = (data.get("command") or "").strip()
            cwd = (data.get("cwd") or "").strip()
            timeout = int(data.get("timeout") or 90)
            if not command:
                self._send_json(400, {"error": "Missing command"})
                return
            if not cwd or not os.path.isabs(cwd):
                self._send_json(400, {"error": "cwd must be an absolute path"})
                return
            if not os.path.isdir(cwd):
                self._send_json(400, {"error": f"cwd does not exist: {cwd}"})
                return
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=max(1, min(timeout, 300)),
            )
            self._send_json(
                200,
                {
                    "ok": True,
                    "command": command,
                    "cwd": cwd,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        except subprocess.TimeoutExpired:
            self._send_json(408, {"error": "Command timed out"})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"terminal_api listening on http://{HOST}:{PORT}")
    server.serve_forever()
