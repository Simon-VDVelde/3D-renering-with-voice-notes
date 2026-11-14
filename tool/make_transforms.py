import json
import numpy as np
from pathlib import Path

def qvec2rotmat(qvec):
    return np.array([
        [1 - 2 * qvec[2]**2 - 2 * qvec[3]**2,
         2 * qvec[1] * qvec[2] - 2 * qvec[0] * qvec[3],
         2 * qvec[3] * qvec[1] + 2 * qvec[0] * qvec[2]],
        [2 * qvec[1] * qvec[2] + 2 * qvec[0] * qvec[3],
         1 - 2 * qvec[1]**2 - 2 * qvec[3]**2,
         2 * qvec[2] * qvec[3] - 2 * qvec[0] * qvec[1]],
        [2 * qvec[3] * qvec[1] - 2 * qvec[0] * qvec[2],
         2 * qvec[2] * qvec[3] + 2 * qvec[0] * qvec[1],
         1 - 2 * qvec[1]**2 - 2 * qvec[2]**2]
    ])

sparse_dir = Path("colmap/sparse/0")

# 1. Lees camera intrinsics (brandpuntsafstand en beeldmidden)
with open(sparse_dir / "cameras.txt") as f:
    for line in f:
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        width, height = int(parts[2]), int(parts[3])
        fx, fy, cx, cy = map(float, parts[4:8])
        break

# 2. Lees voor elk frame de exacte 3D positie en rotatie
frames = []
with open(sparse_dir / "images.txt") as f:
    lines = [l.strip() for l in f if not l.startswith("#") and l.strip()]
    for i in range(0, len(lines), 2):
        parts = lines[i].split()
        qvec = np.array(list(map(float, parts[1:5])))
        tvec = np.array(list(map(float, parts[5:8])))
        image_name = parts[9]

        # COLMAP slaat World-to-Camera op; voor raycasting willen we Camera-to-World (c2w)
        R_w2c = qvec2rotmat(qvec)
        R_c2w = R_w2c.T
        t_c2w = -R_c2w @ tvec

        c2w = np.eye(4)
        c2w[:3, :3] = R_c2w
        c2w[:3, 3] = t_c2w

        frame_idx = int(image_name.split("_")[1].split(".")[0])
        timestamp = round((frame_idx - 1) / 3.0, 3)

        frames.append({
            "file_path": f"frames/{image_name}",
            "frame_index": frame_idx,
            "timestamp": timestamp,
            "c2w_matrix": c2w.tolist()
        })

frames.sort(key=lambda x: x["frame_index"])

output_data = {
    "fps": 3.0,
    "width": width,
    "height": height,
    "fx": fx, "fy": fy, "cx": cx, "cy": cy,
    "frames": frames
}

with open("output/transforms.json", "w") as out:
    json.dump(output_data, out, indent=2)

print(f"Klaar! {len(frames)} geregistreerde camera-frames opgeslagen in output/transforms.json")
