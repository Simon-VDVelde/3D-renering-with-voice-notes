import json
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel

print("Audio inladen via soundfile...")
audio_data, sample_rate = sf.read("audio.wav")

# Omzetten naar mono float32 op 16kHz als dat nog niet zo is
if audio_data.ndim > 1:
    audio_data = audio_data.mean(axis=1)
audio_data = audio_data.astype(np.float32)

# Whisper vereist 16000Hz; als het afwijkt, resamplen we eenvoudig
if sample_rate != 16000:
    import scipy.signal
    num_samples = int(len(audio_data) * 16000 / sample_rate)
    audio_data = scipy.signal.resample(audio_data, num_samples)

print("Whisper-model laden...")
model = WhisperModel("small", device="auto", compute_type="int8")

print("Audio transcriberen met woord-tijdstempels...")
segments, info = model.transcribe(
    audio_data,
    language="nl",
    word_timestamps=True,
    vad_filter=True
)

transcript_data = {
    "language": info.language,
    "segments": []
}

for seg in segments:
    words = [
        {"word": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)}
        for w in (seg.words or [])
    ]
    print(f"[{seg.start:05.2f}s -> {seg.end:05.2f}s] {seg.text.strip()}")
    transcript_data["segments"].append({
        "start": round(seg.start, 2),
        "end": round(seg.end, 2),
        "text": seg.text.strip(),
        "words": words
    })

with open("output/transcript.json", "w", encoding="utf-8") as f:
    json.dump(transcript_data, f, indent=2, ensure_ascii=False)

print("\nKlaar! Transcriptie opgeslagen in output/transcript.json")
