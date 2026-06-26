# Voice-Enabled RAG Chatbot

An intelligent Arabic voice chatbot that uses Retrieval-Augmented Generation (RAG) to answer questions based on your PDF documents.

## Features

- 🎤 **Voice Input**: Record questions in Arabic using your microphone
- 🤖 **RAG System**: Retrieves relevant context from your PDF documents
- 🧠 **AI-Powered**: Uses Groq's LLaMA 3.3 70B model for intelligent responses
- 🔊 **Voice Output**: Responds with natural Arabic speech using ElevenLabs
- 🌐 **Web Interface**: Simple and elegant web UI

## Project Structure

```
NLP1.1/
├── Data/                           # Your PDF documents (input data)
│   ├── IJMSHR-Volume 5-Issue 2- Page 69-96.pdf
│   ├── IJMSHR-Volume 5-Issue 2- Page 97-131.pdf
│   ├── Not to be confused with.pdf
│   └── SHEDET-Volume 13-Issue 13- Page 195-216.pdf
├── vectorstore/                    # FAISS vector database (generated)
├── templates/
│   └── index.html                  # Web frontend
├── backend.py                      # Flask API server
├── rag_utils.py                    # Vector store creation utilities
└── requirements.txt                # Python dependencies
```

## Prerequisites

1. **Python 3.8+**
2. **FFmpeg** (for audio conversion)
   - Windows: Download from https://ffmpeg.org/download.html and add to PATH
   - Or install via: `choco install ffmpeg`

## API Keys Required

You need to obtain (free/trial) API keys from:

1. **ElevenLabs** (Speech-to-Text & Text-to-Speech)
   - Sign up: https://elevenlabs.io/
   - Get API key and Voice ID from your dashboard

2. **Groq** (LLM)
   - Sign up: https://console.groq.com/
   - Get API key from API Keys section

3. **DeepL** (Translation)
   - Sign up: https://www.deepl.com/pro-api
   - Get free API key (500,000 characters/month)

## Setup Instructions

### Step 1: Install Dependencies

```powershell
pip install -r requirements.txt
```

### Step 2: Configure API Keys

Open `backend.py` and add your API keys:

```python
ELEVEN_API_KEY = "your_elevenlabs_api_key_here"
VOICE_ID = "your_voice_id_here"
GROQ_API_KEY = "your_groq_api_key_here"
DEEPL_API_KEY = "your_deepl_api_key_here"
```

### Step 3: Build Vector Store

Process your PDF documents and create the vector database:

```powershell
python rag_utils.py
```

This will:
- Load all PDFs from the `Data/` folder
- Split them into chunks
- Create embeddings using sentence-transformers
- Save the FAISS vector store to `vectorstore/`

### Step 4: Run the Application

```powershell
python backend.py
```

The server will start at `http://localhost:5000`

### Step 5: Use the Chatbot

1. Open your browser and go to `http://localhost:5000`
2. Click "ابدأ التحدث" (Start Speaking)
3. Allow microphone access
4. Ask your question in Arabic
5. Click "أوقف التسجيل" (Stop Recording)
6. Wait for the AI response with voice output

## How It Works

1. **Voice Recording**: User records question in Arabic through the browser
2. **Speech-to-Text**: ElevenLabs transcribes Arabic audio to text
3. **Translation**: DeepL translates Arabic question to English
4. **RAG Retrieval**: FAISS searches for relevant document chunks
5. **Answer Generation**: Groq's LLaMA model generates answer with context
6. **Translation**: DeepL translates English answer back to Arabic
7. **Text-to-Speech**: ElevenLabs converts Arabic text to natural speech
8. **Response**: Audio and text are displayed to the user

## Customization

### Change Chunk Size

Edit `rag_utils.py`:

```python
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,      # Adjust chunk size
    chunk_overlap=100    # Adjust overlap
)
```

### Change LLM Model

Edit `backend.py`:

```python
"model": "llama-3.3-70b-versatile",  # Try other Groq models
```

### Change Voice Settings

Edit `backend.py`:

```python
"voice_settings": {
    "stability": 0.5,           # 0.0 to 1.0
    "similarity_boost": 0.75    # 0.0 to 1.0
}
```

## Troubleshooting

### FFmpeg not found
- Make sure FFmpeg is installed and in your PATH
- Test: `ffmpeg -version`

### Vector store not found
- Run `python rag_utils.py` to build the vector store first

### Microphone not working
- Grant microphone permissions in your browser
- Use HTTPS or localhost only (browsers restrict mic on HTTP)

### API errors
- Verify all API keys are correct
- Check your API usage limits
- Ensure you have internet connection

## Notes

- The application processes questions in Arabic but uses English for RAG retrieval (better performance)
- First run will download the sentence-transformers model (~90MB)
- Voice generation requires good internet connection
- Keep your API keys secure and never commit them to version control

## License

This project is for educational purposes.
