# Assistant-Robot-Grad — Plan B Grand Egyptian Museum Robot Guide

Standalone Raspberry Pi touchscreen software for the manually driven museum robot. The visitor UI contains no driving instructions, encoder diagnostics, or operator controls. Plan B uses no Nav2, maps, coordinates, waypoints, LiDAR navigation, or automatic navigation.

## Architecture

The main Python process is the only owner of the Arduino serial port:

```text
SSH keyboard → KeyboardDriver → ArduinoSerialManager → motor commands
                                      ↑
Arduino encoders → background reader ─┘→ ArrivalDetector → visitor UI flow
```

`ArduinoSerialManager` writes motor commands and continuously reads the newest encoder ticks on one connection. Do not run Arduino Serial Monitor or another motor script during the demo.

## Arduino wiring

| Device | Arduino Uno pin |
|---|---:|
| MDD10A DIR1 | D4 |
| MDD10A PWM1 | D5 |
| MDD10A DIR2 | D7 |
| MDD10A PWM2 | D6 |
| Left encoder A | D2 (interrupt) |
| Left encoder B | D8 |
| Right encoder A | D3 (interrupt) |
| Right encoder B | D9 |

Connect Raspberry Pi/Arduino, motor driver, and encoder grounds together. Power motors from the appropriate external supply—not the Arduino 5 V pin. A 5–24 V encoder must provide a **5 V logic-safe signal** to the Uno; use the correct pull-up, divider, or level-shifting interface for the actual encoder output. Never feed 12 V or 24 V into an Uno input.

If a motor turns backward, change `INVERT_LEFT_MOTOR` or `INVERT_RIGHT_MOTOR` in the sketch instead of swapping behavior in Python.

## Upload the Arduino sketch

Open [arduino/plan_b_motor_encoder/plan_b_motor_encoder.ino](arduino/plan_b_motor_encoder/plan_b_motor_encoder.ino) in Arduino IDE, select **Arduino Uno** and its USB port, then click Upload. Alternatively, with `arduino-cli` configured:

```bash
arduino-cli compile --fqbn arduino:avr:uno arduino/plan_b_motor_encoder
arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:uno arduino/plan_b_motor_encoder
```

The protocol is:

```text
Pi → Arduino: CMD F 120
Arduino → Pi: ENC L=12345 R=12350
```

The sketch reports encoders every 100 ms and includes a 1.2-second command watchdog. Python refreshes the active driving command; if the process or SSH control fails, the watchdog stops PWM.

## Raspberry Pi installation

```bash
sudo apt update
sudo apt install python3-tk python3-pip fonts-noto-core fonts-noto-extra -y
python3 -m pip install -r requirements.txt
```

The requirements include Arabic shaping and bidirectional display support. They can also be installed directly:

```bash
pip install arabic-reshaper python-bidi
sudo apt install fonts-noto-core fonts-noto-extra -y
```

Arabic remains normal UTF-8 in the JSON and source files. The UI reshapes it only when assigning text to Tkinter widgets, using `Noto Naskh Arabic`, `Noto Sans Arabic`, then `DejaVu Sans` as the font fallback order.

Optional TTS:

```bash
sudo apt install espeak-ng
python3 -m pip install pyttsx3
```

## API Keys Setup

Plan B reads API keys from the process environment or from a `.env` file in this project folder. Never put real keys in Python source, JSON, screenshots, or shared logs. Never commit `.env`; if a key is shared accidentally, revoke or rotate it.

Option 1: temporary PowerShell variables for the current terminal:

```powershell
$env:GROQ_API_KEY="your_real_groq_key"
$env:ELEVEN_API_KEY="your_real_elevenlabs_key"
$env:ELEVEN_VOICE_ID="your_real_voice_id"
```

Alternative ElevenLabs names are also supported:

```powershell
$env:ELEVENLABS_API_KEY="your_real_elevenlabs_key"
$env:ELEVENLABS_VOICE_ID="your_real_voice_id"
```

Option 2: `.env` file in the Plan B folder:

```text
GROQ_API_KEY=your_real_groq_key
ELEVEN_API_KEY=your_real_elevenlabs_key
ELEVEN_VOICE_ID=your_real_voice_id
```

Alternative `.env` names:

```text
ELEVENLABS_API_KEY=your_real_elevenlabs_key
ELEVENLABS_VOICE_ID=your_real_voice_id
```

Option 3: permanent Windows Environment Variables:

```text
Windows Search -> Environment Variables -> User variables -> New
```

Install `.env` support when setting up the laptop:

```powershell
python -m pip install python-dotenv
```

TTS uses one centralized `TextToSpeech` path for artifact explanations and chatbot answers. When ElevenLabs keys and voice ID exist, both English and Arabic use the same ElevenLabs voice ID. If ElevenLabs fails, English can fall back to `pyttsx3`, Arabic can fall back to `espeak-ng` on Raspberry Pi OS, and the final fallback is timed simulation so the tour keeps moving.

Optional Vosk speech recognition requires `vosk`, `PyAudio`, and compatible unpacked language models. Typed questions remain the reliable fallback.
STT is off by default. Pass `--enable-stt` to try microphone input; if a dependency or model is missing, the app warns once and keeps the typed Q&A available.

On Windows laptop simulation, install optional speech packages with:

```powershell
pip install pyttsx3 vosk pyaudio
```

For STT, download Vosk models that match the languages you want to test, unpack them, and use these final folder paths:

```text
models/vosk_en
models/vosk_ar
```

English uses `models/vosk_en` when present, otherwise it falls back to `models/vosk` for backward compatibility. Arabic uses `models/vosk_ar` only; it does not pretend an English model can recognize Arabic. If a selected model is missing, the app prints a clear STT error and keeps typed input working.

Expected model folder structure:

```text
models/vosk_en/am
models/vosk_en/conf
models/vosk_en/graph
models/vosk_en/ivector

models/vosk_ar/am
models/vosk_ar/conf
models/vosk_ar/graph
```

On Raspberry Pi OS, install optional speech packages with:

```bash
sudo apt update
sudo apt install espeak-ng python3-pyaudio portaudio19-dev -y
python3 -m pip install pyttsx3 vosk
```

Direct speech diagnostics:

```powershell
python main.py --test-integrated-chatbot-env
python main.py --test-stt-env
python main.py --test-stt-once --stt-language en --mic-device-index 1
python main.py --test-stt-once --stt-language ar --mic-device-index 1
python main.py --test-tts-en
python main.py --test-tts-ar
python main.py --test-integrated-chatbot-typed --language en --question "Talk about the Grand Egyptian Museum" --speak-answer
python main.py --test-integrated-chatbot-typed --language ar --question "تحدث عن المتحف المصري الكبير" --speak-answer
```

On Raspberry Pi OS, use `python3` instead of `python`. Arabic TTS prefers `espeak-ng -v ar` when available; otherwise the app falls back to timed simulation and keeps the tour moving.

List PyAudio devices before starting the UI:

```bash
python3 main.py --list-audio-devices
```

If the desired microphone is not PyAudio's default input, select the index shown by that command:

```bash
python3 main.py --enable-stt --mic-device-index 2
```

On the Q&A screen, **Ask** starts continuous recording and **Submit** stops recording, runs Vosk against the captured audio, and sends the recognized question to the local chatbot. The text box is used whenever recognition is empty.

## Local Q&A and Gemini fallback

Questions are matched against `data/qa.json` in this order: the current artifact, then the other demo artifacts. English and Arabic are normalized before fuzzy matching. A sufficiently close local answer is always preferred and works without internet.

Gemini is attempted only when local data has no good match. Set API keys using the **API Keys Setup** section above; never put real keys in source or JSON.

The default model is `gemini-2.5-flash`. It can be changed without editing code:

```bash
export GEMINI_MODEL="gemini-2.5-flash"
```

Gemini network work runs outside the Tkinter thread. A missing key, unavailable internet, API error, or empty response produces the bilingual no-data message and does not stop the tour.

Find the stable Arduino device name after plugging it in:

```bash
ls /dev/serial/by-id/
```

The SSH user may need serial permission:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing group membership.

## Real demo

SSH into the Raspberry Pi with a terminal that provides a TTY, then run:

```bash
DISPLAY=:0 python3 main.py --demo \
  --serial-port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --keyboard-drive
```

The UI appears on the Pi touchscreen while that same SSH terminal accepts:

| Key | Action |
|---|---|
| W | Drive forward |
| S | Drive backward |
| A | Turn left |
| D | Turn right |
| Space | Stop motors |
| Q | Stop motors, quit keyboard driving, and show emergency screen |

A direction remains active until another direction or Space is pressed. Always test with the wheels raised first and keep a physical power cutoff within reach. The touchscreen emergency button stops application flow and sends a motor stop during shutdown, but it is not a substitute for a hardware emergency cutoff.

Use `--drive-speed 120 --turn-speed 100` to adjust PWM values from 0 to 255.

## Encoder arrival

Arrival monitoring starts only on the robot-pharaoh face screen between points. It cannot trigger from stationary startup values. The detector must first observe both encoder readings changing beyond the noise threshold; after movement, four seconds with no meaningful change marks arrival. Monitoring then stops until the next movement phase.

The normal `--demo` visitor UI never displays an Arrived button, encoder state, or operator instructions.

## Test modes

Laptop UI test without Arduino:

```bash
python main.py --simulate --debug-arrived-button --no-fullscreen
```

Chatbot and spoken-answer test without robot movement or STT:

```bash
DISPLAY=:0 python3 main.py --simulate --debug-arrived-button --enable-tts --no-fullscreen
```

Press **Arrived**, wait for the artifact explanation to finish, type a question on the Q&A screen, and press **Submit**. The answer is displayed and spoken, then **Continue** advances to the movement face. Add `--enable-stt` only when Vosk, PyAudio, and the model are installed.

Raspberry Pi touchscreen test:

```bash
DISPLAY=:0 python3 main.py --simulate --debug-arrived-button
```

Dedicated Arabic rendering test screen:

```bash
python3 main.py --test-arabic-ui --no-fullscreen
```

This screen shows the welcome phrase, Arabic language button text, both tour names, the question prompt, and goodbye text after applying shaping and RTL display order.

The simulation produces encoder movement and then stable ticks. The debug button is intentionally visible only when `--debug-arrived-button` is supplied.

Run automated tests:

```bash
python -m unittest discover -s tests -v
```

## Visitor flow and feedback

The visitor sees Welcome → Language → Tour Type → animated face → artifact explanation → question/answer → feedback → return animation → Goodbye. The face mouth animates from the non-blocking speaking state and returns to idle after speech.

After the third artifact, feedback is appended to:

```text
data/feedback/feedback.xlsx
```

Each row contains timestamp, language, tour type, three ratings, and the optional comment. Close the workbook in Excel before the demo so Python can append to it.

## Limitations

- Motor direction and encoder direction must be verified on the assembled hardware.
- Arduino disconnection is handled without crashing and reconnect is attempted, but the tour cannot auto-arrive without encoder telemetry.
- The touchscreen emergency action is software-only; use a physical motor-power cutoff for real safety.
- Arabic TTS depends on voices installed in Raspberry Pi OS.
- Vosk needs separately installed language models and audio configuration.
