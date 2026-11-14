import os
import json
import cv2
import numpy as np
from pathlib import Path
import struct
import time
from google import genai
from google.genai import types

# ==========================================================
# 0. OMGEVINGSVARIABELEN & B2B CONFIGURATIE INLADEN
# ==========================================================
def load_env_file():
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path(__file__).parent.parent / ".env"
    ]
    for env_path in candidates:
        if env_path.is_file():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception as e:
                print(f"⚠️ Waarschuwing bij inlezen {env_path}: {e}")
            break

load_env_file()

def get_genai_client(api_key):
    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1")
    if use_vertex:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west4")
        print(f"🔒 B2B Beveiliging: Google Cloud Vertex AI actief (Project: {project}, Regio: {location})")
        return genai.Client(vertexai=True, project=project, location=location)
    elif api_key:
        return genai.Client(api_key=api_key)
    return None

# ==========================================================
# 1. LAAD 3D PUNTWOLK (UIT COLMAP) EN CAMERA TRANSFORMS
# ==========================================================
def load_colmap_points(points_txt_path="colmap/sparse/0/points3D.txt"):
    points = []
    with open(points_txt_path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            # X, Y, Z staan op index 1, 2, 3
            points.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return np.array(points, dtype=np.float64)

def find_closest_registered_frame(frames, target_timestamp):
    return min(frames, key=lambda f: abs(f["timestamp"] - target_timestamp))

# ==========================================================
# 2. 2D PIXEL (u, v) NAAR 3D [X, Y, Z] CONE-RAYCASTER
# ==========================================================
def raycast_pixel_to_3d(u, v, frame_data, transforms, points_3d):
    fx, fy = transforms["fx"], transforms["fy"]
    cx, cy = transforms["cx"], transforms["cy"]
    c2w = np.array(frame_data["c2w_matrix"], dtype=np.float64)

    # Camera positie (origin) en rotatiematrix in wereldcoördinaten
    cam_origin = c2w[:3, 3]
    R_c2w = c2w[:3, :3]

    # Richtingsvector in cameracoördinaten (COLMAP: +X rechts, +Y omlaag, +Z vooruit)
    dir_cam = np.array([(u - cx) / fx, (v - cy) / fy, 1.0], dtype=np.float64)
    dir_cam /= np.linalg.norm(dir_cam)

    # Roteer richtingsvector naar wereldcoördinaten
    ray_dir = R_c2w @ dir_cam
    ray_dir /= np.linalg.norm(ray_dir)

    # Bereken vector vanaf camera origin naar elk punt in de sparse pointcloud
    vecs_to_points = points_3d - cam_origin

    # Projecteer op de kijkstraal (diepte langs de straal)
    depths = np.dot(vecs_to_points, ray_dir)

    # Filter punten: moeten vóór de camera liggen (positieve diepte)
    valid_mask = depths > 0.1
    if not np.any(valid_mask):
        print(f"⚠️ Geen punten vóór de camera gevonden voor pixel ({u}, {v}). Fallback op standaarddiepte.")
        fallback_3d = cam_origin + 0.8 * ray_dir
        return fallback_3d.tolist(), cam_origin.tolist(), 0.8

    valid_points = points_3d[valid_mask]
    valid_depths = depths[valid_mask]
    valid_vecs = vecs_to_points[valid_mask]

    # Bereken de loodrechte afstand (straal) van elk punt tot de centrale kijkstraal
    proj_points = cam_origin + np.outer(valid_depths, ray_dir)
    distances_to_ray = np.linalg.norm(valid_points - proj_points, axis=1)

    # Conische zoekstraal: toegestane fout groeit naarmate we verder kijken (tan(theta))
    cone_threshold = 0.05 * valid_depths

    cone_mask = distances_to_ray < cone_threshold

    if np.any(cone_mask):
        candidate_depths = valid_depths[cone_mask]
        hit_depth = np.percentile(candidate_depths, 20)
    else:
        closest_idx = np.argmin(distances_to_ray)
        hit_depth = valid_depths[closest_idx]

    hit_point_3d = cam_origin + hit_depth * ray_dir
    return hit_point_3d.tolist(), cam_origin.tolist(), round(hit_depth, 3)

# ==========================================================
# 3. AI DETECTIE (GEMINI) OF INTERACTIEVE MUIS-KLIK FALLBACK
# ==========================================================
def extract_steps_from_transcript(transcript_data, api_key):
    client = get_genai_client(api_key)
    if client:
        prompt = f"""
        Je bent een technisch analist voor industriële onderhoudsinstructies (SOPs).
        Haal uit deze gesproken transcriptie alle concrete onderdelen en handelingen die de monteur aanwijst of uitvoert.
        Geef uitsluitend een JSON-lijst terug met objecten met exact deze velden:
        - "part_name": korte, professionele naam van het onderdeel in het Nederlands (bijv. "Overdrukventiel")
        - "instruction": duidelijke onderhouds- of controle-instructie in het Nederlands (1-2 zinnen)
        - "timestamp": het exacte tijdstip in seconden (float) waarop het onderdeel genoemd wordt.
        - "translations": een JSON-object met professionele vertalingen naar Engels ("en"), Frans ("fr") en Duits ("de"), telkens met subvelden "part_name" en "instruction".

        Transcriptie:
        {json.dumps(transcript_data["segments"], ensure_ascii=False)}
        """

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    else:
        print("\n--- GEEN GEMINI_API_KEY GEVONDEN: HANDMATIGE STAP-SELECTIE ---")
        steps = []
        for idx, seg in enumerate(transcript_data["segments"], 1):
            mid_time = round((seg["start"] + seg["end"]) / 2.0, 2)
            print(f"\nSegment {idx} [{mid_time}s]: \"{seg['text']}\"")
            choice = input("Is dit een onderhoudsstap? Druk ENTER om over te slaan, of typ de naam van het onderdeel: ").strip()
            if choice:
                steps.append({
                    "part_name": choice,
                    "instruction": seg["text"],
                    "timestamp": mid_time
                })
        return steps


def get_pixel_coordinates(image_path, part_name, instruction, api_key):
    client = get_genai_client(api_key)

    # Lees de afmetingen van het frame uit voor exacte pixel-omrekening
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise FileNotFoundError(f"Kan afbeelding niet openen: {image_path}")
    h, w = img_bgr.shape[:2]

    # Lees de ruwe bytes van de JPEG in
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    prompt = (
        f"Waar bevindt zich '{part_name}' (context: '{instruction}') op deze afbeelding? "
        "Als er een hand of vinger naar een onderdeel wijst, kies dan het aangewezen punt. "
        "Geef uitsluitend een JSON-object terug met 'box_2d': [ymin, xmin, ymax, xmax] "
        "op een genormaliseerde schaal van 0 tot 1000."
    )

    max_pogingen = 3

    for poging in range(max_pogingen):
        try:
            print(f"   -> Frame naar AI sturen (poging {poging + 1}/{max_pogingen})...")

            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/jpeg",
            )

            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=[prompt, image_part],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )

            print("   -> Reactie ontvangen! Analyseren...")
            raw_text = response.text.strip()
            data = json.loads(raw_text)

            # Soms geeft Gemini een lijst van boxen terug in plaats van een enkel object
            if isinstance(data, list) and len(data) > 0:
                data = data[0]

            if "box_2d" in data:
                ymin, xmin, ymax, xmax = data["box_2d"]
                center_y = int(((ymin + ymax) / 2.0) * (h / 1000.0))
                center_x = int(((xmin + xmax) / 2.0) * (w / 1000.0))

                # Beveiliging: zorg dat de berekende pixels binnen de afbeeldingsgrenzen vallen
                center_x = max(0, min(w - 1, center_x))
                center_y = max(0, min(h - 1, center_y))

                print(f"   -> Gevonden coördinaten: pixel ({center_x}, {center_y})")
                return center_x, center_y
            else:
                print("   ⚠️ Geen 'box_2d' gevonden in het AI-antwoord.")

        except Exception as e:
            print(f"\n⚠️ API reageert niet of gaf een fout: {e}")
            if poging < max_pogingen - 1:
                print("⏳ We wachten 5 seconden en proberen het opnieuw...")
                time.sleep(5)
            else:
                print(f"❌ Het lukt niet om coördinaten voor '{part_name}' op te halen na 3 pogingen. We slaan dit punt over.")
                return None, None

    return None, None


# ==========================================================
# 4. EXPORTEER DEBUG-BOLLEN ALS .PLY OM TE TESTEN IN SUPERSPLAT
# ==========================================================
def export_debug_spheres_ply(annotations, out_path="output/debug_hotspots.ply"):
    with open(out_path, "wb") as f:
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            f"element vertex {len(annotations)}\n"
            "property float x\nproperty float y\nproperty float z\n"
            "property float f_dc_0\nproperty float f_dc_1\nproperty float f_dc_2\n"
            "property float opacity\n"
            "property float scale_0\nproperty float scale_1\nproperty float scale_2\n"
            "property float rot_0\nproperty float rot_1\nproperty float rot_2\nproperty float rot_3\n"
            "end_header\n"
        )
        f.write(header.encode('ascii'))

        for ann in annotations:
            x, y, z = ann["position_3d"]
            data = struct.pack('<14f',
                x, y, z,             # Positie
                1.77, -1.77, -1.77,  # Kleur (Rood in Spherical Harmonics)
                10.0,                # Opacity
                -2.0, -2.0, -2.0,    # Schaal
                1.0, 0.0, 0.0, 0.0   # Rotatie
            )
            f.write(data)

# ==========================================================
# 5. HOOFDPROGRAMMA
# ==========================================================
if __name__ == "__main__":
    transforms_path = "output/transforms.json"
    sparse_ply_path = "output/sparse_points.ply"
    transcript_path = "output/transcript.json"

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    with open(transforms_path, "r") as f:
        transforms = json.load(f)

    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    points_3d = load_colmap_points()

    print(f"Geladen: {len(points_3d)} 3D-oppervlaktepunten en {len(transforms['frames'])} geregistreerde frames.")
    os.makedirs("output/debug_frames", exist_ok=True)

    steps = extract_steps_from_transcript(transcript, api_key)

    print(f"\n--- AI vond {len(steps)} onderhoudsstappen ---")
    if len(steps) == 0:
        print("Waarschuwing: Controleer of 'output/transcript.json' wel gesproken tekst bevat over onderdelen!")

    annotations = []
    for i, step in enumerate(steps, 1):
        frame_data = find_closest_registered_frame(transforms["frames"], step["timestamp"])
        img_path = frame_data["file_path"]
        print(f"\n[Stap {i}] {step['part_name']} (t={step['timestamp']}s -> gekoppeld aan {img_path})")

        u, v = get_pixel_coordinates(img_path, step["part_name"], step["instruction"], api_key)

        if u is None or v is None:
            print(f"⚠️ 3D-projectie overgeslagen voor '{step['part_name']}' vanwege ontbrekende coördinaten.")
            continue

        pos_3d, cam_3d, depth = raycast_pixel_to_3d(u, v, frame_data, transforms, points_3d)

        # Sla een visuele debug-foto op met een rood vizier op pixel (u, v)
        debug_img = cv2.imread(img_path)
        cv2.circle(debug_img, (u, v), 18, (0, 0, 255), 3)
        cv2.drawMarker(debug_img, (u, v), (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
        cv2.putText(debug_img, f"{i}. {step['part_name']} (d={depth}m)", (u + 22, v - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        debug_out = f"output/debug_frames/step_{i:02d}_{frame_data['frame_index']:04d}.jpg"
        cv2.imwrite(debug_out, debug_img)

        annotations.append({
            "step": i,
            "title": step["part_name"],
            "description": step["instruction"],
            "timestamp": step["timestamp"],
            "matched_frame": img_path,
            "debug_snapshot": f"debug_frames/step_{i:02d}_{frame_data['frame_index']:04d}.jpg",
            "translations": step.get("translations", {}),
            "pixel_uv": [u, v],
            "position_3d": [round(c, 4) for c in pos_3d],
            "camera_position_3d": [round(c, 4) for c in cam_3d]
        })

    # B2B Enterprise metadata toevoegen
    metadata = {
        "organization": os.environ.get("SOP_ORGANIZATION", "Industrieel Beheer"),
        "confidentiality": os.environ.get("SOP_CONFIDENTIALITY", "Intern Vertrouwelijk"),
        "version": "1.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_steps": len(annotations)
    }

    output_payload = {
        "metadata": metadata,
        "annotations": annotations
    }

    with open("output/annotations.json", "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    export_debug_spheres_ply(annotations)
    print("\n==========================================================")
    print(f"SUCCES! {len(annotations)} 3D-annotaties opgeslagen in output/annotations.json")
    print("Check output/debug_frames/ om de 2D-detecties te bekijken.")
    print("Check output/debug_hotspots.ply samen met motor.ply in SuperSplat!")
    print("==========================================================")
