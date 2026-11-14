#!/usr/bin/env bash
set -e

# --- PADEN & LOCATIES ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="$SCRIPT_DIR"
PROJECT_DIR="$(pwd)"
VIDEO_INPUT=${1:-"video.mp4"}

# 0. Omgevingsvariabelen inladen (.env) voor B2B beveiliging
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "🔒 Configuratie geladen uit $PROJECT_DIR/.env"
    set -a
    source "$PROJECT_DIR/.env"
    set +a
elif [ -f "$TOOL_DIR/.env" ]; then
    echo "🔒 Configuratie geladen uit $TOOL_DIR/.env"
    set -a
    source "$TOOL_DIR/.env"
    set +a
fi

# Zoek naar Brush engine (standaard in engines/brush relatief aan tool)
BRUSH_DIR=${BRUSH_DIR:-"$TOOL_DIR/../engines/brush"}
if [ ! -d "$BRUSH_DIR" ]; then
    if [ -d "$HOME/project/engines/brush" ]; then
        BRUSH_DIR="$HOME/project/engines/brush"
    elif [ -d "$HOME/spatial-sop/brush" ]; then
        BRUSH_DIR="$HOME/spatial-sop/brush"
    fi
fi

echo "=== [0/6] Software dependencies controleren ==="
MISSING_TOOLS=0
for cmd in ffmpeg colmap python cargo; do
    if ! command -v $cmd &> /dev/null; then
        echo "❌ Fout: '$cmd' is niet geïnstalleerd of niet vindbaar in je PATH."
        MISSING_TOOLS=1
    fi
done

if [ $MISSING_TOOLS -eq 1 ]; then
    echo "Installeer de ontbrekende software voordat je dit script uitvoert."
    exit 1
else
    echo "✅ Alle benodigde software (ffmpeg, colmap, python, cargo) is aanwezig."
fi

# Controleer API key voor AI
if [ -z "$GEMINI_API_KEY" ] && [ "$GOOGLE_GENAI_USE_VERTEXAI" != "true" ]; then
    echo "⚠️ Waarschuwing: GEMINI_API_KEY is niet ingesteld in je .env bestand."
    echo "Stel deze in via 'tool/.env' of exporteer GEMINI_API_KEY=\"jouw_sleutel\"."
fi

echo "=== [1/6] Schoonmaken & Audio/Frames extraheren uit $VIDEO_INPUT ==="
rm -rf frames/*.jpg colmap/database.db colmap/sparse/*
mkdir -p frames colmap/sparse output/debug_frames viewer/public

ffmpeg -y -i "$VIDEO_INPUT" -vn -acodec pcm_s16le -ar 16000 -ac 1 audio.wav
ffmpeg -y -i "$VIDEO_INPUT" -vf "fps=3,scale=1920:-2" -qscale:v 2 frames/frame_%04d.jpg

echo "=== [2/6] Cameraposities & 3D Reconstructie (Auto-LiDAR Check) ==="
LIDAR_ACTIVE=0

# Python environment activeren voor LiDAR detectie
if [ ! -d ".venv" ]; then
    if [ -d "$TOOL_DIR/.venv" ]; then
        ln -sfn "$TOOL_DIR/.venv" .venv
    fi
fi
source .venv/bin/activate

# Automatische LiDAR controle
if python "$TOOL_DIR/lidar_detector.py" "$VIDEO_INPUT" "$PROJECT_DIR"; then
    echo "⚡ LiDAR Hardware-data gedetecteerd! COLMAP camerapositieberekening wordt overgeslagen."
    LIDAR_ACTIVE=1
else
    echo "📱 Geen LiDAR gedetecteerd (standaard smartphone video)."
    echo "🔄 Universele COLMAP 3D-reconstructie gestart (werkt op elk toestel)..."

    colmap feature_extractor \
        --database_path colmap/database.db \
        --image_path frames \
        --ImageReader.camera_model PINHOLE \
        --ImageReader.single_camera 1

    colmap sequential_matcher \
        --database_path colmap/database.db \
        --SequentialMatching.overlap 15

    MAX_POGINGEN=3
    POGING=1
    MAPPER_GELUKT=0

    while [ $POGING -le $MAX_POGINGEN ]; do
        echo "-> Start COLMAP mapper (Poging $POGING van $MAX_POGINGEN)..."
        colmap mapper \
            --database_path colmap/database.db \
            --image_path frames \
            --output_path colmap/sparse \
            --Mapper.ba_local_max_num_iterations 15 \
            --Mapper.ba_global_max_num_iterations 20 \
            --Mapper.ba_global_ignore_redundant_points3D 1 \
            --Mapper.num_threads 1
        if [ $? -eq 0 ]; then
            echo "✅ COLMAP mapper is succesvol afgerond!"
            MAPPER_GELUKT=1
            break
        else
            echo "⚠️ COLMAP mapper is gecrasht (waarschijnlijk een SIGSEGV geheugenfout)."
            if [ $POGING -lt $MAX_POGINGEN ]; then
                echo "⏳ 5 seconden wachten voordat we het opnieuw proberen..."
                sleep 5
            fi
            POGING=$((POGING+1))
        fi
    done

    if [ $MAPPER_GELUKT -eq 0 ]; then
        echo "❌ Fout: COLMAP mapper faalt consistent na $MAX_POGINGEN pogingen. Sluit andere programma's af om RAM vrij te maken en probeer opnieuw."
        exit 1
    fi

    colmap model_converter \
        --input_path colmap/sparse/0 \
        --output_path colmap/sparse/0 \
        --output_type TXT

    colmap model_converter \
        --input_path colmap/sparse/0 \
        --output_path output/sparse_points.ply \
        --output_type PLY
fi

echo "=== [3/6] Transforms genereren & 3D Model klaarmaken ==="
source .venv/bin/activate

if [ $LIDAR_ACTIVE -eq 0 ]; then
    python "$TOOL_DIR/make_transforms.py"
fi

echo "Symlinks aanmaken voor de 3D-dataset map..."
mkdir -p dataset
ln -sfn "$PROJECT_DIR/frames" "$PROJECT_DIR/dataset/images"
if [ -d "$PROJECT_DIR/colmap/sparse" ]; then
    ln -sfn "$PROJECT_DIR/colmap/sparse" "$PROJECT_DIR/dataset/sparse"
fi

echo "Brush (OpenSplat) starten voor 3D-training..."
if [ -d "$BRUSH_DIR" ]; then
    if [ ! -f "$PROJECT_DIR/dataset_export/point_cloud.ply" ]; then
        echo "Geen bestaande point_cloud.ply gevonden in dataset_export/, start Brush training..."
        cd "$BRUSH_DIR"
        cargo run --release -- "$PROJECT_DIR/dataset" \
            --total-train-iters 15000 \
            --export-every 15000 \
            --export-path "$PROJECT_DIR/dataset_export" \
            --export-name "point_cloud.ply"
        cd "$PROJECT_DIR"
    else
        echo "point_cloud.ply bestaat al in dataset_export/, training overgeslagen (verwijder dit bestand om opnieuw te trainen)."
    fi
else
    echo "⚠️ Waarschuwing: Map '$BRUSH_DIR' niet gevonden. Brush training wordt overgeslagen."
fi

echo "=== [4/6] Audio transcriberen & 3D-Raycasting uitvoeren ==="
source .venv/bin/activate
python "$TOOL_DIR/transcribe.py"
python "$TOOL_DIR/build_annotations.py"

echo "=== [5/6] Bestanden kopiëren naar Web-Viewer & Beveiliging configureren ==="
# Kopieer de web-viewer template als deze nog niet in de werkmap staat
if [ ! -f "viewer/package.json" ]; then
    echo "Website-template ontbreekt in deze map. Kopiëren vanuit tool..."
    mkdir -p viewer
    cp -a "$TOOL_DIR/viewer/." "viewer/"
else
    # Update bronbestanden met de nieuwste viewer template
    cp -r "$TOOL_DIR/viewer/src" "$TOOL_DIR/viewer/index.html" "$TOOL_DIR/viewer/vite.config.js" "viewer/"
fi

mkdir -p viewer/public
cp output/annotations.json viewer/public/annotations.json
ffmpeg -y -i audio.wav -codec:a libmp3lame -qscale:a 4 viewer/public/audio.mp3
cp -r output/debug_frames viewer/public/ 2>/dev/null || true

# B2B Beveiliging: Operator PIN en Admin PIN hashes genereren (PIN staat NOOIT in plain text in config)
PIN_ENABLED=false
PIN_HASH=""
ADMIN_HASH=""
if [ -n "$VIEWER_ACCESS_PIN" ]; then
    PIN_ENABLED=true
    PIN_HASH=$(echo -n "$VIEWER_ACCESS_PIN" | sha256sum | awk '{print $1}')
fi
if [ -n "$VIEWER_ADMIN_PIN" ]; then
    ADMIN_HASH=$(echo -n "$VIEWER_ADMIN_PIN" | sha256sum | awk '{print $1}')
else
    ADMIN_HASH=$(echo -n "9999" | sha256sum | awk '{print $1}')
fi

cat <<EOF > viewer/public/config.json
{
  "pin_enabled": $PIN_ENABLED,
  "pin_hash": "$PIN_HASH",
  "admin_hash": "$ADMIN_HASH",
  "organization": "${SOP_ORGANIZATION:-"Industriële Klant"}",
  "confidentiality": "${SOP_CONFIDENTIALITY:-"Intern Vertrouwelijk"}"
}
EOF
echo "🔒 Beveiligingsconfiguratie weggeschreven (Operator PIN: $PIN_ENABLED, Admin PIN actief: true)"

echo "=== [6/6] Model kopiëren, converteren & Server starten ==="

BRUSH_PLY="$PROJECT_DIR/dataset_export/point_cloud.ply"

if [ -f "$BRUSH_PLY" ]; then
    echo "PLY model gevonden! Kopiëren naar de web-viewer map..."
    cp "$BRUSH_PLY" viewer/public/point_cloud.ply
    
    echo "Eventuele oude splat-bestanden verwijderen om errors te voorkomen..."
    rm -f viewer/public/point_cloud.splat
    
    echo "PLY omzetten naar het veel lichtere .splat formaat..."
    SPLAT_BIN=""
    if [ -x "$TOOL_DIR/viewer/node_modules/.bin/splat-transform" ]; then
        SPLAT_BIN="$TOOL_DIR/viewer/node_modules/.bin/splat-transform"
    elif [ -x "$PROJECT_DIR/viewer/node_modules/.bin/splat-transform" ]; then
        SPLAT_BIN="$PROJECT_DIR/viewer/node_modules/.bin/splat-transform"
    elif [ -x "$HOME/.npm/_npx/b2244d78553f83d5/node_modules/.bin/splat-transform" ]; then
        SPLAT_BIN="$HOME/.npm/_npx/b2244d78553f83d5/node_modules/.bin/splat-transform"
    elif command -v splat-transform &> /dev/null; then
        SPLAT_BIN="splat-transform"
    fi

    if [ -n "$SPLAT_BIN" ]; then
        "$SPLAT_BIN" viewer/public/point_cloud.ply viewer/public/point_cloud.splat
    else
        npx --yes @playcanvas/splat-transform viewer/public/point_cloud.ply viewer/public/point_cloud.splat
    fi
    
    rm -f viewer/public/point_cloud.ply
    
    echo "✅ Model succesvol gecomprimeerd en klaargezet als point_cloud.splat!"
else
    echo "⚠️ Kon het 3D model niet automatisch vinden (dataset_export/point_cloud.ply ontbreekt)."
fi

echo "🚀 Web Viewer bouwen..."
cd viewer
if [ ! -d "node_modules" ]; then
    npm install
fi
npm run build

# Controleer deployment target voor veilige publicatie
DEPLOY_TARGET=${DEPLOY_TARGET:-"none"}
CLOUDFLARE_PROJECT=${CLOUDFLARE_PROJECT:-"spatial-sop-demo"}

if [ "$DEPLOY_TARGET" = "cloudflare" ]; then
    echo "🌐 Publiceren naar Cloudflare Pages project: $CLOUDFLARE_PROJECT..."
    npx wrangler pages deploy dist --project-name "$CLOUDFLARE_PROJECT"
else
    echo "🔒 Lokale B2B modus: bestand gebouwd in 'viewer/dist/'."
    echo "Om de viewer veilig lokaal te starten, voer uit:"
    echo "   cd viewer && npm run preview"
    echo "(Zet DEPLOY_TARGET=cloudflare in je .env bestand als je publiek wilt deployen)"
fi
