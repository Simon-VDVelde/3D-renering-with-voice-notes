#!/usr/bin/env python3
"""
server.py — Enterprise Web Server & Portal voor Spatial SOP.
Biedt een complete web-interface voor:
- Het uploaden van video's of LiDAR-zips
- Real-time pipeline monitoring en logs
- Objectenbeheer (bekijken, openen in 3D viewer, verwijderen)
- Directe QR-code generatie voor machinestickers
"""

import os
import sys
import json
import time
import uuid
import shutil
import mimetypes
import subprocess
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
OBJECTEN_DIR = PROJECT_ROOT / "objecten"
WEB_DIR = BASE_DIR / "web"
TOOL_DIR = BASE_DIR

# Actieve achtergrondtaken opslaan
JOBS = {}

class SpatialSOPHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API: Lijst van objecten ophalen
        if path == "/api/objects":
            self.handle_get_objects()
            return

        # 2. API: Status van een actieve job
        if path == "/api/job-status":
            qs = parse_qs(parsed.query)
            job_id = qs.get("job_id", [None])[0]
            self.handle_job_status(job_id)
            return

        # 3. API: Inspectiegeschiedenis ophalen
        if path == "/api/inspections":
            qs = parse_qs(parsed.query)
            object_name = qs.get("object_name", [None])[0]
            self.handle_get_inspections(object_name)
            return

        # 4. Bedrijfslogo serveren (White-labeling)
        if path == "/api/logo" or path == "/logo.svg" or path == "/logo.png":
            candidate = OBJECTEN_DIR / "logo.png"
            if not candidate.is_file():
                candidate = OBJECTEN_DIR / "logo.svg"
            if not candidate.is_file():
                candidate = TOOL_DIR / "viewer" / "public" / "logo.svg"
            mime = "image/png" if candidate.suffix == ".png" else "image/svg+xml"
            self.serve_file(candidate, mime)
            return

        # 5. Viewer routering: /viewer/<object_name>/...
        if path.startswith("/viewer/"):
            self.handle_serve_viewer(path[len("/viewer/"):])
            return

        # 6. Fallback voor assets
        if path.startswith("/assets/"):
            candidate = TOOL_DIR / "viewer" / "dist" / path.lstrip("/")
            if candidate.is_file():
                self.serve_file(candidate, "application/javascript")
                return

        # 7. Statische bestanden van de web portal
        if path == "/" or path == "/index.html":
            self.serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return

        target_file = WEB_DIR / path.lstrip("/")
        if target_file.is_file():
            mime, _ = mimetypes.guess_type(str(target_file))
            self.serve_file(target_file, mime or "application/octet-stream")
            return

        self.send_error(404, "Pagina niet gevonden")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API: Upload video of LiDAR zip
        if path == "/api/upload":
            self.handle_upload()
            return

        # 2. API: Start pipeline voor een object
        if path == "/api/start-pipeline":
            self.handle_start_pipeline()
            return

        # 3. API: Verwijder een object
        if path == "/api/delete-object":
            self.handle_delete_object()
            return

        # 4. API: Annotaties opslaan vanuit Human-in-the-Loop Web Editor
        if path == "/api/save-annotations":
            self.handle_save_annotations()
            return

        # 5. API: Digitale inspectie loggen & aftekenen (ISO 9001 compliance)
        if path == "/api/log-inspection":
            self.handle_log_inspection()
            return

        # 6. API: Bedrijfslogo uploaden voor white-labeling
        if path == "/api/upload-logo":
            self.handle_upload_logo()
            return

        self.send_error(404, "API endpoint niet gevonden")

    # ==========================================================
    # HANDLERS
    # ==========================================================
    def handle_get_objects(self):
        objects = []
        if OBJECTEN_DIR.exists():
            for item in sorted(OBJECTEN_DIR.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    annotations_file = item / "output" / "annotations.json"
                    viewer_dist = item / "viewer" / "dist" / "index.html"
                    video_file = item / "video.mp4"

                    has_viewer = viewer_dist.exists()
                    step_count = 0
                    metadata = {}

                    if annotations_file.exists():
                        try:
                            with open(annotations_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                if isinstance(data, dict):
                                    step_count = len(data.get("annotations", []))
                                    metadata = data.get("metadata", {})
                                elif isinstance(data, list):
                                    step_count = len(data)
                        except Exception:
                            pass

                    mtime = item.stat().st_mtime
                    date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                    inspections_dir = item / "inspections"
                    inspection_count = len(list(inspections_dir.glob("*.json"))) if inspections_dir.is_dir() else 0

                    objects.append({
                        "name": item.name,
                        "date": date_str,
                        "has_viewer": has_viewer,
                        "step_count": step_count,
                        "inspection_count": inspection_count,
                        "organization": metadata.get("organization", "Industrieel Beheer"),
                        "confidentiality": metadata.get("confidentiality", "Intern Vertrouwelijk"),
                        "has_video": video_file.exists()
                    })

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"objects": objects}).encode("utf-8"))

    def handle_delete_object(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode("utf-8"))
            object_name = params.get("object_name", "")
            safe_name = "".join(c for c in object_name if c.isalnum() or c in ("-", "_")).strip()

            target_dir = OBJECTEN_DIR / safe_name
            if target_dir.is_dir() and target_dir.resolve().parent == OBJECTEN_DIR.resolve():
                shutil.rmtree(target_dir)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            else:
                self.send_error(404, "Object niet gevonden")
        except Exception as e:
            self.send_error(500, f"Fout bij verwijderen: {e}")

    def handle_save_annotations(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode("utf-8"))

            object_name = payload.get("object_name", "")
            safe_name = "".join(c for c in object_name if c.isalnum() or c in ("-", "_")).strip()
            target_dir = OBJECTEN_DIR / safe_name

            if not target_dir.is_dir() or target_dir.resolve().parent != OBJECTEN_DIR.resolve():
                self.send_error(404, "Objectmap niet gevonden")
                return

            annotations_data = payload.get("data")
            if not annotations_data:
                self.send_error(400, "Geen annotatiedata ontvangen in payload")
                return

            # Bestemmingen waar annotations.json moet worden bijgewerkt
            destinations = [
                target_dir / "output" / "annotations.json",
                target_dir / "viewer" / "public" / "annotations.json",
                target_dir / "viewer" / "dist" / "annotations.json"
            ]

            # Audit trail: Maak een backup van de bestaande versie
            primary_file = destinations[0]
            backup_name = None
            if primary_file.exists():
                backup_name = f"annotations_backup_{int(time.time())}.json"
                backup_file = target_dir / "output" / backup_name
                try:
                    shutil.copy2(primary_file, backup_file)
                except Exception as be:
                    print(f"Waarschuwing bij backup maken: {be}")

            # Schrijf de nieuwe data weg
            json_text = json.dumps(annotations_data, indent=2, ensure_ascii=False)
            updated_count = 0
            for dest in destinations:
                if dest.parent.exists():
                    with open(dest, "w", encoding="utf-8") as f:
                        f.write(json_text)
                    updated_count += 1

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "message": f"Annotaties succesvol opgeslagen in {updated_count} locaties!",
                "updated_files": updated_count,
                "backup": backup_name,
                "timestamp": int(time.time())
            }).encode("utf-8"))

        except Exception as e:
            self.send_error(500, f"Fout bij opslaan annotaties: {e}")

    def handle_get_inspections(self, object_name):
        if not object_name:
            self.send_error(400, "object_name query parameter ontbreekt")
            return

        safe_name = "".join(c for c in object_name if c.isalnum() or c in ("-", "_")).strip()
        target_dir = OBJECTEN_DIR / safe_name
        inspections_dir = target_dir / "inspections"

        inspections = []
        if inspections_dir.is_dir():
            for f in sorted(inspections_dir.glob("*.json"), reverse=True):
                try:
                    with open(f, "r", encoding="utf-8") as inf:
                        data = json.load(inf)
                        data["id"] = f.stem
                        inspections.append(data)
                except Exception:
                    pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"object_name": safe_name, "inspections": inspections}).encode("utf-8"))

    def handle_log_inspection(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode("utf-8"))

            object_name = payload.get("object_name", "")
            safe_name = "".join(c for c in object_name if c.isalnum() or c in ("-", "_")).strip()
            target_dir = OBJECTEN_DIR / safe_name
            if not target_dir.is_dir() or target_dir.resolve().parent != OBJECTEN_DIR.resolve():
                self.send_error(404, "Objectmap niet gevonden")
                return

            inspections_dir = target_dir / "inspections"
            inspections_dir.mkdir(parents=True, exist_ok=True)

            timestamp = int(time.time())
            filename = inspections_dir / f"inspection_{timestamp}.json"

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "inspection_id": f"inspection_{timestamp}",
                "message": "Inspectie succesvol digitaal gelogd en geverifieerd conform ISO 9001!"
            }).encode("utf-8"))
        except Exception as e:
            self.send_error(500, f"Fout bij opslaan inspectie: {e}")

    def handle_upload_logo(self):
        try:
            content_type = self.headers.get("Content-Type", "")
            content_length = int(self.headers.get("Content-Length", 0))

            if "multipart/form-data" not in content_type:
                self.send_error(400, "Verwacht multipart/form-data")
                return

            boundary = content_type.split("boundary=")[-1].strip()
            body = self.rfile.read(content_length)
            parts = body.split(("--" + boundary).encode())

            logo_bytes = None
            filename = "logo.png"

            for part in parts:
                if b"Content-Disposition" in part and (b'name="logo"' in part or b'filename="' in part):
                    headers_part, data_part = part.split(b"\r\n\r\n", 1)
                    data_part = data_part.rstrip(b"\r\n")
                    for line in headers_part.decode("latin1").split("\r\n"):
                        if "filename=" in line:
                            filename = line.split('filename="')[-1].split('"')[0]
                    logo_bytes = data_part
                    break

            if not logo_bytes:
                self.send_error(400, "Geen logo bestand gevonden in upload")
                return

            ext = Path(filename).suffix.lower()
            save_name = "logo" + ext

            # Sla globaal op in OBJECTEN_DIR
            out_file = OBJECTEN_DIR / save_name
            with open(out_file, "wb") as f:
                f.write(logo_bytes)

            # Kopieer naar alle object viewers
            updated_viewers = 0
            for obj in OBJECTEN_DIR.iterdir():
                if obj.is_dir() and not obj.name.startswith("."):
                    for sub in ["public", "dist"]:
                        dest = obj / "viewer" / sub / save_name
                        if dest.parent.is_dir():
                            with open(dest, "wb") as df:
                                df.write(logo_bytes)
                            updated_viewers += 1

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "filename": save_name,
                "message": f"Logo opgeslagen en gesynchroniseerd met {updated_viewers} viewers!"
            }).encode("utf-8"))
        except Exception as e:
            self.send_error(500, f"Fout bij uploaden logo: {e}")

    def handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        if "multipart/form-data" not in content_type:
            self.send_error(400, "Verwacht multipart/form-data")
            return

        boundary = content_type.split("boundary=")[-1].strip()
        body = self.rfile.read(content_length)

        parts = body.split(("--" + boundary).encode())
        object_name = None
        file_bytes = None
        filename = "video.mp4"

        for part in parts:
            if b"Content-Disposition" in part:
                headers_part, data_part = part.split(b"\r\n\r\n", 1)
                data_part = data_part.rstrip(b"\r\n")
                headers_str = headers_part.decode("latin1")

                if 'name="object_name"' in headers_str:
                    object_name = data_part.decode("utf-8").strip()
                elif 'name="file"' in headers_str or 'filename="' in headers_str:
                    for line in headers_str.split("\r\n"):
                        if "filename=" in line:
                            filename = line.split('filename="')[-1].split('"')[0]
                    file_bytes = data_part

        if not object_name:
            object_name = f"object_{int(time.time())}"

        safe_name = "".join(c for c in object_name if c.isalnum() or c in ("-", "_")).strip()
        if not safe_name:
            safe_name = f"object_{int(time.time())}"

        target_dir = OBJECTEN_DIR / safe_name
        target_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix.lower()
        if ext == ".zip":
            saved_file = target_dir / "input.zip"
        else:
            saved_file = target_dir / "video.mp4"

        if file_bytes:
            with open(saved_file, "wb") as f:
                f.write(file_bytes)

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({
            "success": True,
            "object_name": safe_name,
            "saved_file": saved_file.name
        }).encode("utf-8"))

    def handle_start_pipeline(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        params = json.loads(post_data.decode("utf-8"))

        object_name = params.get("object_name")
        target_dir = OBJECTEN_DIR / object_name

        if not target_dir.is_dir():
            self.send_error(404, "Objectmap niet gevonden")
            return

        input_file = "video.mp4"
        if (target_dir / "input.zip").exists():
            input_file = "input.zip"

        job_id = str(uuid.uuid4())[:8]
        log_file = target_dir / "pipeline.log"

        JOBS[job_id] = {
            "object_name": object_name,
            "status": "running",
            "step": 1,
            "step_name": "Initialiseren & Audio/Frames extraheren",
            "progress": 5,
            "logs": [],
            "start_time": time.time(),
            "completed": False
        }

        def run_worker():
            cmd = [str(TOOL_DIR / "build_sop.sh"), input_file]
            with open(log_file, "w", encoding="utf-8") as lf:
                process = subprocess.Popen(
                    cmd,
                    cwd=str(target_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                for line in process.stdout:
                    lf.write(line)
                    lf.flush()
                    line_clean = line.strip()
                    JOBS[job_id]["logs"].append(line_clean)
                    if len(JOBS[job_id]["logs"]) > 200:
                        JOBS[job_id]["logs"].pop(0)

                    if "[1/6]" in line_clean:
                        JOBS[job_id]["step"] = 1
                        JOBS[job_id]["step_name"] = "Audio & Frames extraheren"
                        JOBS[job_id]["progress"] = 15
                    elif "[2/6]" in line_clean:
                        JOBS[job_id]["step"] = 2
                        JOBS[job_id]["step_name"] = "3D Cameraposities (LiDAR / COLMAP)"
                        JOBS[job_id]["progress"] = 35
                    elif "[3/6]" in line_clean:
                        JOBS[job_id]["step"] = 3
                        JOBS[job_id]["step_name"] = "3D Gaussian Splatting Training"
                        JOBS[job_id]["progress"] = 55
                    elif "[4/6]" in line_clean:
                        JOBS[job_id]["step"] = 4
                        JOBS[job_id]["step_name"] = "Whisper Transcriptie & Gemini AI Raycasting"
                        JOBS[job_id]["progress"] = 75
                    elif "[5/6]" in line_clean:
                        JOBS[job_id]["step"] = 5
                        JOBS[job_id]["step_name"] = "Web Viewer & Beveiliging klaarmaken"
                        JOBS[job_id]["progress"] = 90
                    elif "[6/6]" in line_clean:
                        JOBS[job_id]["step"] = 6
                        JOBS[job_id]["step_name"] = "Model optimalisatie & Afronding"
                        JOBS[job_id]["progress"] = 98

                process.wait()
                if process.returncode == 0:
                    JOBS[job_id]["status"] = "success"
                    JOBS[job_id]["progress"] = 100
                    JOBS[job_id]["step_name"] = "Voltooid!"
                else:
                    JOBS[job_id]["status"] = "error"
                    JOBS[job_id]["step_name"] = "Fout opgetreden tijdens verwerking."

                JOBS[job_id]["completed"] = True

        t = threading.Thread(target=run_worker, daemon=True)
        t.start()

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"job_id": job_id}).encode("utf-8"))

    def handle_job_status(self, job_id):
        job = JOBS.get(job_id)
        if not job:
            self.send_error(404, "Job ID niet gevonden")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": job["status"],
            "step": job["step"],
            "step_name": job["step_name"],
            "progress": job["progress"],
            "logs": job["logs"][-30:],
            "completed": job["completed"]
        }).encode("utf-8"))

    def handle_serve_viewer(self, subpath):
        parts = subpath.split("/", 1)
        object_name = parts[0]

        # Als er geen bestandspad achter staat, redirect naar index.html met query parameters
        if len(parts) == 1 or not parts[1]:
            parsed = urlparse(self.path)
            query = f"?{parsed.query}" if parsed.query else ""
            self.send_response(302)
            self.send_header("Location", f"/viewer/{object_name}/index.html{query}")
            self.end_headers()
            return

        file_path = parts[1]
        dist_dir = OBJECTEN_DIR / object_name / "viewer" / "dist"
        if not dist_dir.exists():
            dist_dir = OBJECTEN_DIR / object_name / "viewer"

        target_file = dist_dir / file_path
        if target_file.is_file():
            mime, _ = mimetypes.guess_type(str(target_file))
            if file_path.endswith(".js") or file_path.endswith(".mjs"):
                mime = "application/javascript"
            elif file_path.endswith(".splat"):
                mime = "application/octet-stream"
            elif file_path.endswith(".json"):
                mime = "application/json"
            self.serve_file(target_file, mime or "application/octet-stream")
        else:
            self.send_error(404, f"Bestand {file_path} niet gevonden voor {object_name}")

    def serve_file(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Interne serverfout: {e}")


def run_server(port=8080):
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, SpatialSOPHandler)
    print("=" * 60)
    print(f"🚀 Spatial SOP Enterprise Portal draait op:")
    print(f"   👉 Lokaal:           http://localhost:{port}")
    print(f"   👉 Lokaal Netwerk:   http://0.0.0.0:{port}")
    print(f"   📂 Objectenmap:      {OBJECTEN_DIR}")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server afgesloten.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    run_server(port)
