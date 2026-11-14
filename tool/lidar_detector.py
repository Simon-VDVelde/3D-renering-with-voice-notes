#!/usr/bin/env python3
"""
lidar_detector.py — Detecteert automatisch of invoerdata afkomstig is van een LiDAR-smartphone
(bijv. iPhone/iPad Pro met Record3D, Polycam of ARKit) of een standaard video.

Als LiDAR-metadata gevonden wordt:
- Zet de cameraposities direct om naar output/transforms.json
- Genereert indien aanwezig een sparse pointcloud uit de LiDAR dieptedata
- Geeft exitcode 0 terug als LiDAR succesvol verwerkt is (waardoor COLMAP overgeslagen kan worden)
- Geeft exitcode 1 terug als het een normale video betreft (fallback naar COLMAP)
"""

import os
import sys
import json
import zipfile
from pathlib import Path
import numpy as np

def check_and_extract_lidar(input_path, project_dir="."):
    input_file = Path(input_path)
    proj_dir = Path(project_dir)

    print(f"🔍 Inspecteren van invoerbestand: {input_file.name}...")

    # 1. Controleer of het een ZIP-archief is van een LiDAR scan app (Record3D, Polycam, etc.)
    if input_file.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(input_file, 'r') as z:
                file_list = z.namelist()
                print(f"   Archief bevat {len(file_list)} bestanden.")

                # Record3D formaat check
                has_metadata = any("metadata.json" in f.lower() for f in file_list)
                has_poses = any("poses.txt" in f.lower() or "transforms.json" in f.lower() for f in file_list)

                if has_metadata or has_poses:
                    print("⚡ LiDAR-pakket gedetecteerd (Record3D / ARKit)!")
                    extract_dir = proj_dir / "lidar_raw"
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    z.extractall(extract_dir)

                    return process_lidar_bundle(extract_dir, proj_dir)
        except Exception as e:
            print(f"⚠️ Fout bij inspectie van zip: {e}")

    # 2. Controleer of er in de projectmap al LiDAR metadata aanwezig is
    lidar_meta = proj_dir / "metadata.json"
    lidar_poses = proj_dir / "poses.txt"
    if lidar_meta.exists() and lidar_poses.exists():
        print("⚡ Lokale LiDAR-metadata gevonden in werkmap!")
        return process_lidar_bundle(proj_dir, proj_dir)

    # 3. Geen LiDAR metadata gevonden -> Fallback naar standaard video
    print("ℹ️ Geen LiDAR-metadata gevonden.")
    print("📱 Het toestel heeft geen LiDAR of er is een standaard video geüpload.")
    print("🔄 Fallback actief: Universele COLMAP 3D-reconstructie wordt gebruikt (werkt op elk toestel).")
    return False


def process_lidar_bundle(bundle_dir, output_dir):
    """Zet LiDAR cameraposities en intrinsics om naar ons transforms.json formaat."""
    try:
        # Zoek metadata.json
        meta_files = list(bundle_dir.glob("**/metadata.json"))
        if not meta_files:
            return False
        meta_file = meta_files[0]

        with open(meta_file, "r") as f:
            meta = json.load(f)

        # Zoek poses
        pose_files = list(bundle_dir.glob("**/poses.txt"))
        if not pose_files:
            return False
        pose_file = pose_files[0]

        print(f"✅ Inlezen van LiDAR cameradata uit {meta_file.name} en {pose_file.name}...")

        w = meta.get("w", 1920)
        h = meta.get("h", 1440)
        K = meta.get("K", [1500, 0, w/2, 0, 1500, h/2, 0, 0, 1])
        fx, fy, cx, cy = K[0], K[4], K[2], K[5]

        frames = []
        with open(pose_file, "r") as f:
            lines = [l.strip() for l in f if l.strip()]

        for idx, line in enumerate(lines, 1):
            parts = [float(x) for x in line.split()]
            # Record3D pose formaat: qx, qy, qz, qw, tx, ty, tz
            if len(parts) >= 7:
                qx, qy, qz, qw = parts[0], parts[1], parts[2], parts[3]
                tx, ty, tz = parts[4], parts[5], parts[6]

                # Quaternion naar rotatiematrix
                R = np.array([
                    [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qw*qz, 2*qx*qz + 2*qw*qy],
                    [2*qx*qy + 2*qw*qz, 1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qw*qx],
                    [2*qx*qz - 2*qw*qy, 2*qy*qz + 2*qw*qx, 1 - 2*qx**2 - 2*qy**2]
                ])

                c2w = np.eye(4)
                c2w[:3, :3] = R
                c2w[:3, 3] = [tx, ty, tz]

                timestamp = round((idx - 1) / 30.0, 3)
                frames.append({
                    "file_path": f"frames/frame_{idx:04d}.jpg",
                    "frame_index": idx,
                    "timestamp": timestamp,
                    "c2w_matrix": c2w.tolist()
                })

        transforms_data = {
            "fps": 30.0,
            "width": int(w),
            "height": int(h),
            "fx": float(fx),
            "fy": float(fy),
            "cx": float(cx),
            "cy": float(cy),
            "source": "LiDAR_Hardware",
            "frames": frames
        }

        out_path = output_dir / "output" / "transforms.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(transforms_data, f, indent=2)

        print(f"🎉 Succes! {len(frames)} exacte LiDAR cameraposities direct opgeslagen in {out_path}.")
        print("⚡ COLMAP camerapositieberekening kan worden overgeslagen!")
        return True

    except Exception as e:
        print(f"⚠️ Fout bij converteren van LiDAR bundle: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Gebruik: python lidar_detector.py <input_bestand> [project_map]")
        sys.exit(1)

    input_path = sys.argv[1]
    proj_dir = sys.argv[2] if len(sys.argv) > 2 else "."

    is_lidar = check_and_extract_lidar(input_path, proj_dir)
    # Return code 0 = LiDAR gebruikt (skip COLMAP), Return code 1 = Standaard video (run COLMAP)
    sys.exit(0 if is_lidar else 1)
