from pathlib import Path
import platform
import subprocess
import tempfile

import numpy as np
import soundfile as sf
from transformers import pipeline


AR_MODEL_ID = "facebook/mms-tts-ara"
EN_MODEL_ID = "facebook/mms-tts-eng"

_tts_ar = None
_tts_en = None


def _get_tts_pipeline(language: str):
    global _tts_ar, _tts_en

    language = (language or "ar").lower().strip()

    if language in ["ar", "arabic"]:
        if _tts_ar is None:
            print("[HF TTS] Loading Arabic model...")
            _tts_ar = pipeline(
                task="text-to-speech",
                model=AR_MODEL_ID
            )
            print("[HF TTS] Arabic model loaded.")
        return _tts_ar

    if language in ["en", "english"]:
        if _tts_en is None:
            print("[HF TTS] Loading English model...")
            _tts_en = pipeline(
                task="text-to-speech",
                model=EN_MODEL_ID
            )
            print("[HF TTS] English model loaded.")
        return _tts_en

    raise ValueError(f"Unsupported TTS language: {language}")


def generate_tts_file(text: str, language: str = "ar", output_file: str | None = None) -> str:
    if not text or not text.strip():
        raise ValueError("TTS text is empty.")

    tts = _get_tts_pipeline(language)

    print(f"[HF TTS] Generating speech, language={language}")
    output = tts(text)

    audio = np.squeeze(output["audio"])
    sampling_rate = output["sampling_rate"]

    if output_file is None:
        temp_dir = Path(tempfile.gettempdir())
        output_file = temp_dir / "robot_hf_tts_output.wav"
    else:
        output_file = Path(output_file)

    sf.write(str(output_file), audio, sampling_rate)

    print(f"[HF TTS] Audio saved: {output_file}")
    return str(output_file)


def play_audio_file(audio_file: str):
    system_name = platform.system().lower()

    if "windows" in system_name:
        import winsound
        winsound.PlaySound(audio_file, winsound.SND_FILENAME)
        return

    subprocess.run(["aplay", audio_file], check=False)


def speak(text: str, language: str = "ar", output_file: str | None = None, play: bool = True) -> str:
    audio_file = generate_tts_file(
        text=text,
        language=language,
        output_file=output_file
    )

    if play:
        play_audio_file(audio_file)

    return audio_file


if __name__ == "__main__":
    print("Testing Arabic...")
    speak(
        "أهلا بكم في المتحف المصري الكبير. أنا الروبوت المرشد الخاص بكم.",
        language="ar",
        output_file="test_robot_ar.wav"
    )

    print("Testing English...")
    speak(
        "Hello, welcome to the Grand Egyptian Museum. I am your smart tour guide robot.",
        language="en",
        output_file="test_robot_en.wav"
    )