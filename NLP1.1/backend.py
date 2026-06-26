from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import tempfile
import subprocess
import base64
import requests
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
import os
import re
from gtts import gTTS
from deep_translator import GoogleTranslator

app = Flask(__name__)
CORS(app)

def get_env_first(*names):
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return ""


try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except Exception:
    pass


ELEVEN_API_KEY = get_env_first("ELEVEN_API_KEY", "ELEVENLABS_API_KEY")
VOICE_ID = get_env_first("ELEVEN_VOICE_ID", "ELEVENLABS_VOICE_ID")
GROQ_API_KEY = get_env_first("GROQ_API_KEY")

# Convert webm audio to wav format
def convert_to_wav(input_path):
    output_path = input_path.replace(".webm", ".wav")
    command = ["ffmpeg", "-y", "-i", input_path, "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", output_path]
    subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_path

# Transcribe audio using Groq's Whisper API (Free!) - Auto-detect language
def transcribe_audio(file_path):
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    with open(file_path, "rb") as f:
        files = {"file": (file_path, f, "audio/wav")}
        # Remove language parameter to auto-detect
        data = {"model": "whisper-large-v3"}
        response = requests.post(url, headers=headers, files=files, data=data)
        print(f"Transcription response status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Transcribed text: {result.get('text', '')}")
            return result.get("text", "")
        else:
            print(f"ERROR: Transcription failed - {response.text}")
            return ""

# Detect if text is Arabic or English
def detect_language(text):
    # Simple detection: if more than 30% of characters are Arabic, it's Arabic
    arabic_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF')
    total_chars = len([c for c in text if c.isalpha()])
    if total_chars == 0:
        return 'en'
    ratio = arabic_chars / total_chars
    return 'ar' if ratio > 0.3 else 'en'

# Translate text using Google Translate (Free!)
def translate_to_english(text):
    try:
        translator = GoogleTranslator(source='auto', target='en')
        result = translator.translate(text)
        return result
    except Exception as e:
        print(f"Translation to English failed: {e}")
        return text

def translate_to_arabic(text):
    try:
        translator = GoogleTranslator(source='auto', target='ar')
        result = translator.translate(text)
        return result
    except Exception as e:
        print(f"Translation to Arabic failed: {e}")
        return text

# Convert numbers to Arabic words for better TTS pronunciation
def convert_numbers_to_arabic_words(text):
    """Convert English/Arabic numerals to Arabic words for better TTS"""
    # Dictionary for number conversion (0-1000000)
    ones = ['', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة']
    teens = ['عشرة', 'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر', 
             'ستة عشر', 'سبعة عشر', 'ثمانية عشر', 'تسعة عشر']
    tens = ['', '', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون', 'ستون', 'سبعون', 'ثمانون', 'تسعون']
    hundreds = ['', 'مائة', 'مئتان', 'ثلاثمائة', 'أربعمائة', 'خمسمائة', 'ستمائة', 'سبعمائة', 'ثمانمائة', 'تسعمائة']
    
    def number_to_arabic_words(n):
        if n == 0:
            return 'صفر'
        if n < 0:
            return 'سالب ' + number_to_arabic_words(-n)
        
        if n < 10:
            return ones[n]
        elif n < 20:
            return teens[n - 10]
        elif n < 100:
            return tens[n // 10] + (' و' + ones[n % 10] if n % 10 != 0 else '')
        elif n < 1000:
            return hundreds[n // 100] + (' و' + number_to_arabic_words(n % 100) if n % 100 != 0 else '')
        elif n < 1000000:
            thousands = n // 1000
            remainder = n % 1000
            if thousands == 1:
                result = 'ألف'
            elif thousands == 2:
                result = 'ألفان'
            elif thousands < 11:
                result = ones[thousands] + ' آلاف'
            else:
                result = number_to_arabic_words(thousands) + ' ألف'
            
            if remainder != 0:
                result += ' و' + number_to_arabic_words(remainder)
            return result
        else:
            millions = n // 1000000
            remainder = n % 1000000
            if millions == 1:
                result = 'مليون'
            elif millions == 2:
                result = 'مليونان'
            else:
                result = number_to_arabic_words(millions) + ' مليون'
            
            if remainder != 0:
                result += ' و' + number_to_arabic_words(remainder)
            return result
    
    # Find all numbers in the text and replace them
    def replace_number(match):
        number = int(match.group())
        return number_to_arabic_words(number)
    
    # Replace numbers with Arabic words
    text = re.sub(r'\d+', replace_number, text)
    return text

# Convert text to speech using ElevenLabs with your custom voice
def synthesize_audio_base64(text, language='ar'):
    try:
        # Convert numbers to words only for Arabic
        if language == 'ar':
            text = convert_numbers_to_arabic_words(text)
        print(f"Text for TTS ({language}): {text}")
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
        headers = {
            "xi-api-key": ELEVEN_API_KEY,
            "Content-Type": "application/json"
        }
        data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        response = requests.post(url, headers=headers, json=data)
        print(f"TTS response status: {response.status_code}")
        
        if response.status_code == 200:
            audio_bytes = response.content
            audio_b64 = f"data:audio/mpeg;base64,{base64.b64encode(audio_bytes).decode()}"
            print("✅ ElevenLabs TTS generation successful")
            return audio_b64
        else:
            print(f"ElevenLabs TTS Error: {response.text}")
            # Fallback to gTTS if ElevenLabs fails
            print(f"Falling back to Google TTS ({language})...")
            tts = gTTS(text=text, lang=language, slow=False)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
                temp_audio_path = fp.name
                tts.save(temp_audio_path)
            with open(temp_audio_path, 'rb') as audio_file:
                audio_bytes = audio_file.read()
                audio_b64 = f"data:audio/mpeg;base64,{base64.b64encode(audio_bytes).decode()}"
            os.unlink(temp_audio_path)
            return audio_b64
            
    except Exception as e:
        print(f"TTS Error: {str(e)}")
        return None

# Query Groq LLM
def ask_groq(prompt):
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
    )
    result = response.json()
    return result.get("choices", [{}])[0].get("message", {}).get("content", "No answer.")


@app.route("/ask", methods=["POST"])
def ask():
    try:
        # Receive audio file from frontend
        audio = request.files["audio"]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as f:
            audio.save(f.name)
            webm_path = f.name

        # Convert to WAV format
        wav_path = convert_to_wav(webm_path)
        print(f"Converted to wav: {wav_path}")

        # Transcribe audio to text
        user_text = transcribe_audio(wav_path)
        print(f"Transcribed text: {user_text}")

        if not user_text.strip():
            return jsonify({"error": "No text detected from audio"}), 400

        # Detect language
        detected_lang = detect_language(user_text)
        print(f"Detected language: {detected_lang}")

        # Translate to English only if Arabic
        if detected_lang == 'ar':
            question_for_rag = translate_to_english(user_text)
            print(f"Translated to English: {question_for_rag}")
        else:
            question_for_rag = user_text
            print(f"Using English directly: {question_for_rag}")

        # Load vector store for RAG
        print("Loading vector store...")
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        vectordb = FAISS.load_local("vectorstore", embeddings, allow_dangerous_deserialization=True)
        retriever = vectordb.as_retriever()

        # Retrieve relevant context
        print("Retrieving relevant context...")
        docs = retriever.invoke(question_for_rag)
        context = "\n".join([doc.page_content for doc in docs[:5]])
        print(f"Retrieved {len(docs)} context chunks.")

        # Create prompt with context
        prompt = f"""You are an expert assistant. Use the following context to answer in 50 words the question.\n\nContext:\n{context}\n\nQuestion:\n{question_for_rag}"""

        # Get answer from Groq
        print("Sending prompt to Groq...")
        english_answer = ask_groq(prompt)
        print(f"English answer: {english_answer}")

        # Translate answer back to original language
        if detected_lang == 'ar':
            assistant_text = translate_to_arabic(english_answer)
            print(f"Translated to Arabic: {assistant_text}")
        else:
            assistant_text = english_answer
            print(f"Keeping English answer")

        # Convert answer to audio in the detected language
        audio_b64 = synthesize_audio_base64(assistant_text, detected_lang)
        if audio_b64:
            return jsonify({
                "user_text": user_text,
                "assistant_text": assistant_text,
                "audio_base64": audio_b64
            })
        else:
            return jsonify({"error": "Failed to synthesize audio"}), 500

    except Exception as e:
        print("Error:", str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/ask_text", methods=["POST"])
def ask_text():
    try:
        data = request.get_json(force=True)
        user_text = data.get("question", "").strip()

        if not user_text:
            return jsonify({"error": "No question received"}), 400

        detected_lang = detect_language(user_text)
        print(f"Text question: {user_text}")
        print(f"Detected language: {detected_lang}")

        if detected_lang == "ar":
            question_for_rag = translate_to_english(user_text)
            print(f"Translated to English: {question_for_rag}")
        else:
            question_for_rag = user_text
            print(f"Using English directly: {question_for_rag}")

        print("Loading vector store...")
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        vectordb = FAISS.load_local("vectorstore", embeddings, allow_dangerous_deserialization=True)
        retriever = vectordb.as_retriever()

        print("Retrieving relevant context...")
        docs = retriever.invoke(question_for_rag)
        context = "\n".join([doc.page_content for doc in docs[:5]])
        print(f"Retrieved {len(docs)} context chunks.")

        prompt = f"""You are an expert assistant for a museum tour guide robot.
Use the following context to answer the question in about 50 words.

Context:
{context}

Question:
{question_for_rag}
"""

        print("Sending prompt to Groq...")
        english_answer = ask_groq(prompt)
        print(f"English answer: {english_answer}")

        if detected_lang == "ar":
            assistant_text = translate_to_arabic(english_answer)
            print(f"Translated to Arabic: {assistant_text}")
        else:
            assistant_text = english_answer
            print("Keeping English answer")

        return jsonify({
            "user_text": user_text,
            "assistant_text": assistant_text
        })

    except Exception as e:
        print("ask_text error:", str(e))
        return jsonify({"error": str(e)}), 500
    
@app.route("/")
def serve_index():
    return send_file("templates/index.html")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
