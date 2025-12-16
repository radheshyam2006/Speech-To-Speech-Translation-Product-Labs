# receive.py

import pika
import json
import uvicorn
import re
from io import BytesIO
from pydub import AudioSegment
from pydub.silence import split_on_silence

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

# Import the RabbitMQ URL from your config file.
from Config import CLOUDAMQP_URL

app = FastAPI(title="Continuous Translation Input Server")

class TranslationConfig(BaseModel):
    """Defines the structure for the configuration JSON."""
    input_lang: str
    output_lang: str
    gender: str

def overwrite_config_file(config: TranslationConfig):
    """
    Reads, modifies, and overwrites the Config.py file.
    WARNING: Unsafe for concurrent requests. Implemented for a single-user scenario.
    """
    config_path = 'Config.py'
    try:
        with open(config_path, 'r') as f:
            content = f.read()

        content = re.sub(r"^(INPUT_LANG\s*=\s*).*$", f"\\1\"{config.input_lang}\"", content, flags=re.MULTILINE)
        content = re.sub(r"^(OUTPUT_LANG\s*=\s*).*$", f"\\1\"{config.output_lang}\"", content, flags=re.MULTILINE)
        content = re.sub(r"^(GENDER\s*=\s*).*$", f"\\1\"{config.gender}\"", content, flags=re.MULTILINE)
        
        with open(config_path, 'w') as f:
            f.write(content)
        
        print(f"✅ Config.py overwritten: IN={config.input_lang}, OUT={config.output_lang}, GENDER={config.gender}")
        return True
    except Exception as e:
        print(f"❌ ERROR: Failed to overwrite Config.py: {e}")
        return False

def chunk_and_push_audio(audio_bytes: bytes):
    """
    Performs optimal chunking on audio and pushes each chunk to the ASR_input queue.
    """
    connection = None
    try:
        connection = pika.BlockingConnection(pika.URLParameters(CLOUDAMQP_URL))
        channel = connection.channel()
        queue_name = 'ASR_input'
        channel.queue_declare(queue=queue_name, durable=True)

        audio = AudioSegment.from_file(BytesIO(audio_bytes), format="wav")

        # Split audio on pauses of at least 700ms.
        # keep_silence is removed to not add any extra pauses, as requested.
        chunks = split_on_silence(
            audio,
            min_silence_len=2000,
            silence_thresh=audio.dBFS - 14
        )

        if not chunks:
            print("No speech detected in audio.")
            return 0
        
        for chunk in chunks:
            chunk_io = BytesIO()
            chunk.export(chunk_io, format="wav")
            
            message = { "audio_bytes_hex": chunk_io.getvalue().hex() }
            
            channel.basic_publish(
                exchange='',
                routing_key=queue_name,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
        
        print(f"✅ Pushed {len(chunks)} audio chunks to '{queue_name}'.")
        return len(chunks)
    except Exception as e:
        print(f"❌ ERROR: Failed to chunk and push audio: {e}")
        return -1
    finally:
        if connection and connection.is_open:
            connection.close()

@app.post("/config/")
async def set_configuration(config: TranslationConfig):
    """
    Receives a JSON payload to overwrite the language and gender settings in Config.py.
    """
    if overwrite_config_file(config):
        return {"status": "success", "message": "Configuration updated."}
    else:
        raise HTTPException(status_code=500, detail="Failed to write to configuration file.")

@app.post("/process-audio/")
async def process_audio_stream(audio_file: UploadFile = File(...)):
    """
    Receives a WAV audio file, chunks it, and pushes the chunks to the pipeline.
    This is a "fire and forget" endpoint.
    """
    if audio_file.content_type not in ["audio/wav", "audio/x-wav"]:
        raise HTTPException(status_code=400, detail="Please upload a WAV file.")

    chunks_pushed = chunk_and_push_audio(await audio_file.read())
    
    if chunks_pushed >= 0:
        return {"status": "success", "message": f"{chunks_pushed} audio chunks pushed."}
    else:
        raise HTTPException(status_code=500, detail="Error processing audio.")
    
if __name__ == "__main__":
    uvicorn.run("receive:app", host="0.0.0.0", port=8010, reload=True)