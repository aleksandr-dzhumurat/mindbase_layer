import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import mlx_whisper as whisper
import numpy as np
import scipy.signal as signal
import sounddevice as sd
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
_WHISPER_MODEL    = "mlx-community/whisper-medium"
BLACKHOLE_INDEX   = 0  # BlackHole 2ch
SAMPLE_RATE       = 48000
CHUNK_SECONDS     = 1
SILENCE_THRESHOLD = 0.0003
ANSWER_AFTER_SEC  = 4.0
SAY_VOICE         = "Lana"       # macOS Serbian voice — change to "Samantha" for English
GEMINI_MODEL      = "gemini-2.0-flash"

_SYSTEM_BASE = """You are a helpful voice assistant on a phone call.
The user is speaking Serbian. Reply in Serbian, briefly and naturally —
as if you are speaking out loud. No markdown, no bullet points, plain text only."""

# ── Use-case context (swap this for different scenarios) ──────────────────────
USECASE_PROMPT = """You are calling a courier service on behalf of the user.
The goal is to arrange a return of a package — find out the return procedure,
confirm the pickup address, and agree on a pickup date if possible.
Be polite, concise, and ask one question at a time."""

SYSTEM_PROMPT = f"{_SYSTEM_BASE}\n\n{USECASE_PROMPT}"

# ── Gemini setup ──────────────────────────────────────────────────────────────
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
chat = client.chats.create(
    model=GEMINI_MODEL,
    config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
)

# ── Shared state ──────────────────────────────────────────────────────────────
audio_queue      = queue.Queue()
transcript_lines = []
transcript_lock  = threading.Lock()
last_speech_time = [time.time()]
answer_triggered = [False]
bot_speaking      = threading.Event()  # set while TTS is playing
mute_until        = [0.0]              # epoch time until which audio input is muted (post-speak cooldown)

# ── Audio callback ─────────────────────────────────────────────────────────────
def callback(indata, frames, t, status):
    if bot_speaking.is_set() or time.time() < mute_until[0]:
        return  # drop audio while bot is speaking or during post-speak cooldown
    # mix down to mono if device returns multiple channels
    mono = indata.mean(axis=1, keepdims=True) if indata.ndim > 1 and indata.shape[1] > 1 else indata
    audio_queue.put(mono.copy())

# ── Transcriber thread ─────────────────────────────────────────────────────────
MAX_ACC_SAMPLES = SAMPLE_RATE * 30  # keep at most 30s of accumulated speech at 48kHz

_LOG_DIR = Path("/Users/adzhumurat/PycharmProjects/home_brain/data/call_logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _transcribe_and_commit(acc_buf: np.ndarray) -> str:
    """Transcribe acc_buf and append result to transcript_lines. Returns text."""
    audio_16k = signal.resample(acc_buf, len(acc_buf) // 3).astype(np.float32)
    result    = whisper.transcribe(audio_16k, path_or_hf_repo=_WHISPER_MODEL, language="sr")
    text      = result["text"].strip()
    words     = text.split()
    if text and len(set(words)) / max(len(words), 1) > 0.3:
        print(f"\n>>> {text}")
        with transcript_lock:
            transcript_lines.append(text)
        log_path = _LOG_DIR / f"{int(time.time())}.log"
        log_path.write_text(text)
    return text


def transcriber():
    chunk_buf = np.array([], dtype=np.float32)   # collects raw 1-second frames
    acc_buf   = np.array([], dtype=np.float32)   # accumulates speech between commits

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
                # transcribe whatever is left in acc_buf before answering
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

            # buffer full — commit this chunk and start fresh
            if len(acc_buf) >= MAX_ACC_SAMPLES:
                _transcribe_and_commit(acc_buf)
                acc_buf = np.array([], dtype=np.float32)

# ── Answer generator ───────────────────────────────────────────────────────────
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

# ── TTS via macOS say ──────────────────────────────────────────────────────────
def speak(text: str):
    bot_speaking.set()
    try:
        subprocess.run(["say", "-v", SAY_VOICE, "-r", "180", text])
    finally:
        bot_speaking.clear()
        mute_until[0] = time.time() + 1.0  # 1s cooldown to flush BlackHole echo
        last_speech_time[0] = time.time() + 1.0

def facetime_streaming():
    threading.Thread(target=transcriber, daemon=True).start()

    device_channels = sd.query_devices(BLACKHOLE_INDEX)["max_input_channels"]
    with sd.InputStream(
        device=BLACKHOLE_INDEX,
        samplerate=SAMPLE_RATE,
        channels=device_channels,
        blocksize=SAMPLE_RATE * CHUNK_SECONDS,
        callback=callback,
    ):
        print("Listening... Ctrl+C to stop\n")
        while True:
            sd.sleep(1000)


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(sd.query_devices())
    print(f"\nUsing Gemini model : {GEMINI_MODEL}")
    print(f"Using TTS voice    : {SAY_VOICE}")
    print(f"Answer triggers after {ANSWER_AFTER_SEC}s of silence\n")

    print("Loading Whisper model...")
    whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=_WHISPER_MODEL, language="sr")
    print("Whisper model ready.\n")

    facetime_streaming()
