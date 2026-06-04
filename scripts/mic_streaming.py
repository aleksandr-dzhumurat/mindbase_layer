import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import mlx_whisper as whisper
import numpy as np
import scipy.signal as sig
import sounddevice as sd
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
_WHISPER_MODEL    = "mlx-community/whisper-medium"
MIC_INDEX         = 1   # None = system default microphone
SAMPLE_RATE       = 48000  # MacBook mic native rate; resampled to 16kHz for Whisper
CHUNK_SECONDS     = 1
SILENCE_THRESHOLD = 0.002
ANSWER_AFTER_SEC  = 5.0
SAY_VOICE         = "Lana"
GEMINI_MODEL      = "gemini-2.0-flash"

_SYSTEM_BASE = """You are a helpful voice assistant.
The user is speaking Serbian. Reply in Serbian, briefly and naturally —
as if you are speaking out loud. No markdown, no bullet points, plain text only."""

USECASE_PROMPT = """You are calling a courier service on behalf of the user.
The goal is to arrange a return of a package — find out the return procedure,
confirm the pickup address, and agree on a pickup date if possible.
Be polite, concise, and ask one question at a time."""

prompts = [
    _SYSTEM_BASE,
 #    USECASE_PROMPT
]

SYSTEM_PROMPT = "\n\n".join(prompts)

# ── Gemini setup ──────────────────────────────────────────────────────────────
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
chat   = client.chats.create(
    model=GEMINI_MODEL,
    config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
)

# ── Shared state ──────────────────────────────────────────────────────────────
audio_queue      = queue.Queue()
transcript_lines = []
transcript_lock  = threading.Lock()
last_speech_time = [time.time()]
answer_triggered = [False]
bot_speaking     = threading.Event()

# ── Audio callback ────────────────────────────────────────────────────────────
def callback(indata, frames, t, status):
    if bot_speaking.is_set():
        return
    audio_queue.put(indata.copy())

# ── Transcriber ───────────────────────────────────────────────────────────────
MAX_ACC_SAMPLES = SAMPLE_RATE * 30

_LOG_DIR = Path("/Users/adzhumurat/PycharmProjects/home_brain/data/call_logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _transcribe_and_commit(acc_buf: np.ndarray) -> str:
    audio_16k = sig.resample(acc_buf, len(acc_buf) // 3).astype(np.float32)
    result = whisper.transcribe(audio_16k, path_or_hf_repo=_WHISPER_MODEL, language="sr")
    text   = result["text"].strip()
    words  = text.split()
    if text and len(set(words)) / max(len(words), 1) > 0.3:
        print(f"\n>>> {text}")
        with transcript_lock:
            transcript_lines.append(text)
        (_LOG_DIR / f"{int(time.time())}.log").write_text(text)
    return text


def transcriber():
    chunk_buf = np.array([], dtype=np.float32)
    acc_buf   = np.array([], dtype=np.float32)

    while True:
        chunk_buf = np.append(chunk_buf, np.squeeze(audio_queue.get()))

        if len(chunk_buf) < SAMPLE_RATE * CHUNK_SECONDS:
            continue

        rms       = np.sqrt(np.mean(chunk_buf ** 2))
        chunk     = chunk_buf
        chunk_buf = np.array([], dtype=np.float32)

        if rms < SILENCE_THRESHOLD:
            silence_duration = time.time() - last_speech_time[0]
            if silence_duration >= ANSWER_AFTER_SEC and not answer_triggered[0]:
                if len(acc_buf) > 0:
                    _transcribe_and_commit(acc_buf)
                    acc_buf = np.array([], dtype=np.float32)
                if transcript_lines:
                    answer_triggered[0] = True
                    with transcript_lock:
                        full_transcript = " ".join(transcript_lines)
                    print(f"\n{'─'*60}")
                    print(f"[{ANSWER_AFTER_SEC}s silence] generating answer...")
                    print(f"{'─'*60}\n")
                    threading.Thread(target=generate_answer, args=(full_transcript,), daemon=True).start()
        else:
            last_speech_time[0] = time.time()
            answer_triggered[0] = False
            acc_buf = np.append(acc_buf, chunk)

            acc_sec = len(acc_buf) / SAMPLE_RATE
            print(f"\r● {acc_sec:.1f}s", end="", flush=True)

            if len(acc_buf) >= MAX_ACC_SAMPLES:
                _transcribe_and_commit(acc_buf)
                acc_buf = np.array([], dtype=np.float32)

# ── Answer generator ──────────────────────────────────────────────────────────
def generate_answer(transcript: str):
    try:
        print(f"[USER] {transcript}")
        response = chat.send_message(transcript)
        answer   = response.text.strip()
        print(f"[BOT]  {answer}\n")
        speak(answer)
    except Exception as e:
        print(f"[ERROR] Gemini call failed: {e}")
    finally:
        with transcript_lock:
            transcript_lines.clear()

# ── TTS ───────────────────────────────────────────────────────────────────────
def speak(text: str):
    bot_speaking.set()
    try:
        subprocess.run(["say", "-v", SAY_VOICE, "-r", "180", text])
    finally:
        time.sleep(0.2)  # let speaker ring out before re-opening mic
        bot_speaking.clear()
        last_speech_time[0] = time.time()

# ── Entry point ───────────────────────────────────────────────────────────────
def mic_streaming():
    threading.Thread(target=transcriber, daemon=True).start()

    with sd.InputStream(
        device=MIC_INDEX,
        samplerate=SAMPLE_RATE,
        channels=1,
        blocksize=SAMPLE_RATE * CHUNK_SECONDS,
        callback=callback,
    ):
        print("Listening on mic... Ctrl+C to stop\n")
        while True:
            sd.sleep(1000)


if __name__ == "__main__":
    print(sd.query_devices())
    print(f"\nUsing Gemini model : {GEMINI_MODEL}")
    print(f"Using TTS voice    : {SAY_VOICE}")
    print(f"Answer triggers after {ANSWER_AFTER_SEC}s of silence\n")

    print("Loading Whisper model...")
    whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=_WHISPER_MODEL, language="sr")
    print("Whisper model ready.\n")

    mic_streaming()
