import asyncio
import io
import pika
from pydub import AudioSegment
from pydub.playback import play
from Config import CLOUDAMQP_URL  # Import the URL from config.py

BUFFER_QUEUE = "Buffer"

def connect_to_rabbitmq():
    """Establish and return a RabbitMQ connection and channel."""
    params = pika.URLParameters(CLOUDAMQP_URL)
    params.socket_timeout = 5
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    # Declare the BUFFER queue in case it doesn't exist
    channel.queue_declare(queue=BUFFER_QUEUE, durable=True)
    return connection, channel

async def monitor_and_play_audio():
    connection, channel = connect_to_rabbitmq()
    print("Connected to RabbitMQ, monitoring BUFFER queue for messages...")
    
    first_time = True  # Flag for the first run

    while True:
        try:
            # Retrieve current message count in the BUFFER queue.
            queue = channel.queue_declare(queue=BUFFER_QUEUE, passive=True)
            message_count = queue.method.message_count

            # On the first run, wait until there are at least 5 messages.
            if first_time:
                if message_count < 5:
                    await asyncio.sleep(0.05)
                    continue  # Skip processing until we have at least 5 messages
                else:
                    # Once we have at least 5 messages, process one message and mark first_time as False.
                    method_frame, header, body = channel.basic_get(queue=BUFFER_QUEUE, auto_ack=True)
                    if method_frame:
                        print(f"(First run) Message dequeued. Queue size now: {message_count - 1}")
                        try:
                            audio_segment = AudioSegment.from_file(io.BytesIO(body), format="wav")
                            print(f"Playing audio blob ({len(body)} bytes)...")
                            play(audio_segment)
                        except Exception as audio_error:
                            print(f"Error processing/playing audio blob: {audio_error}")
                    first_time = False
            else:
                # For subsequent runs, process any message that is available.
                if message_count > 0:
                    method_frame, header, body = channel.basic_get(queue=BUFFER_QUEUE, auto_ack=True)
                    if method_frame:
                        print(f"Message dequeued. Queue size now: {message_count - 1}")
                        try:
                            audio_segment = AudioSegment.from_file(io.BytesIO(body), format="wav")
                            print(f"Playing audio blob ({len(body)} bytes)...")
                            play(audio_segment)
                        except Exception as audio_error:
                            print(f"Error processing/playing audio blob: {audio_error}")

            # Use a very short sleep to keep checking continuously.
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"Error monitoring queue: {e}")
            try:
                connection.close()
            except Exception:
                pass
            await asyncio.sleep(0.05)
            # Attempt to reconnect if something goes wrong.
            connection, channel = connect_to_rabbitmq()

if __name__ == "__main__":
    asyncio.run(monitor_and_play_audio())
