import pika
import os
import time
import uuid
from pydub import AudioSegment

class RabbitMQPublisher:
    def __init__(self, cloudamqp_url, queue_name):
        self.queue_name = queue_name
        self.params = pika.URLParameters(cloudamqp_url)
        self.params.socket_timeout = 5
        self.connection = pika.BlockingConnection(self.params)
        self.channel = self.connection.channel()
        self.channel.confirm_delivery()  # Enable confirmation mode
        self.declare_queue()
    
    def declare_queue(self, durable=True):
        try:
            self.channel.queue_declare(queue=self.queue_name, durable=durable)
            print(f"Queue '{self.queue_name}' declared successfully as durable={durable}.")
        except pika.exceptions.ChannelClosedByBroker as e:
            if 'PRECONDITION_FAILED' in str(e):
                print(f"Queue '{self.queue_name}' already exists with different properties. Skipping queue declaration.")
            else:
                raise
    
    def publish_message(self, audio_file_path):
        try:
            with open(audio_file_path, 'rb') as file:
                audio_data = file.read()
                self.channel.basic_publish(
                    exchange="",
                    routing_key=self.queue_name,
                    body=audio_data,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Ensure message persistence
                        content_type='audio/wav',
                        correlation_id=str(uuid.uuid4())
                    )
                )
                print(f"Published {audio_file_path} to queue '{self.queue_name}'.")
        except Exception as e:
            print(f"Failed to publish audio file: {e}")

    def close_connection(self):
        self.connection.close()
        print("Connection closed.")

def clear_chunks_folder(output_dir):
    """
    Deletes all files in the specified output directory.
    """
    if os.path.exists(output_dir):
        for filename in os.listdir(output_dir):
            file_path = os.path.join(output_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                    print(f"Deleted file: {file_path}")
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")

def split_audio_into_chunks(input_audio_path: str, chunk_length_ms=300, output_dir="chunks"):
    """
    Split the input audio file into chunks of size chunk_length_ms.
    Saves the chunks in the specified output directory.
    Returns a list of file paths for the generated chunks.
    """
    # Ensure the output directory exists.
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    else:
        # Clear the contents of the folder if it already exists.
        clear_chunks_folder(output_dir)
    
    # Load the input audio.
    audio = AudioSegment.from_wav(input_audio_path)
    audio_length_ms = len(audio)
    chunk_paths = []
    
    # Calculate the number of chunks.
    num_chunks = audio_length_ms // chunk_length_ms + (1 if audio_length_ms % chunk_length_ms > 0 else 0)
    
    for i in range(num_chunks):
        start_ms = i * chunk_length_ms
        end_ms = start_ms + chunk_length_ms
        chunk = audio[start_ms:end_ms]
        chunk_filename = os.path.join(output_dir, f"chunk_{i}.wav")
        chunk.export(chunk_filename, format="wav")
        chunk_paths.append(chunk_filename)
        print(f"Generated chunk {i} from {start_ms}ms to {end_ms}ms: {chunk_filename}")
    
    return chunk_paths

if __name__ == "__main__":
    # Configuration for RabbitMQ.
    CLOUDAMQP_URL = "amqps://keqzgbzz:ooZR8GlQRTtXg6V__RBZd0leDtVYZhrj@puffin.rmq2.cloudamqp.com/keqzgbzz"
    QUEUE_NAME = "ASR_input"
    
    input_audio_path = "input_audio.wav"  # Make sure this file exists in your working directory.
    
    # Split the input audio into 300ms chunks.
    chunk_files = split_audio_into_chunks(input_audio_path, chunk_length_ms=300, output_dir="chunks")
    
    # Initialize the RabbitMQ publisher.
    rabbitmq_client = RabbitMQPublisher(CLOUDAMQP_URL, QUEUE_NAME)
    
    # Publish each chunk to the queue.
    for chunk_file in chunk_files:
        rabbitmq_client.publish_message(chunk_file)
        time.sleep(0.3)  # Optional: small delay between messages.
    
    rabbitmq_client.close_connection()
