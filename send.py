# send_final_audio.py
import pika
import json
import requests
import time

# --- Configuration ---
# It's best practice to manage these settings in a central file.
try:
    from Config import CLOUDAMQP_URL
except ImportError:
    print("❌ ERROR: Could not import CLOUDAMQP_URL. Make sure it's defined in a Config.py file.")
    # Provide a placeholder so the script doesn't crash immediately.
    CLOUDAMQP_URL = "amqps://user:password@hostname/vhost" 

# --- IMPORTANT ---
# You MUST change this URL to the actual endpoint where your client application is waiting for the audio.
USER_ENDPOINT_URL = "http://localhost:8001/receive-final-audio"

# The queue this service will listen to for messages from the TTS service.
QUEUE_NAME = "TTS_output"


def on_message_received(ch, method, properties, body):
    """
    This is the core logic, called for each message from the TTS_output queue.
    It parses the message, downloads the audio from the S3 URL, and sends it.
    """
    print("Received a message. Processing...")
    try:
        # 1. Parse the incoming JSON message
        data = json.loads(body)
        
        # 2. **CRITICAL FIX**: Extract the S3 URL from the nested data structure.
        #    The reference code and API spec show the URL is inside a 'data' object.
        s3_url = data.get("data", {}).get("s3_url")

        if not s3_url:
            print("❌ ERROR: Message did not contain a nested 's3_url'. Discarding message.")
            # Acknowledge to remove the malformed message from the queue.
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        print(f"Downloading audio from: {s3_url}")
        
        # 3. Download the .wav file from the S3 URL
        download_response = requests.get(s3_url, timeout=30)
        download_response.raise_for_status()  # Raise an exception for HTTP errors (like 404, 500)
        audio_bytes = download_response.content

        print("Audio downloaded. Forwarding to user endpoint...")
        
        # 4. Send the downloaded .wav file to the user's waiting endpoint
        headers = {'Content-Type': 'audio/wav'}
        send_response = requests.post(USER_ENDPOINT_URL, data=audio_bytes, headers=headers, timeout=30)
        send_response.raise_for_status()
        
        print(f"✅ Successfully sent audio to {USER_ENDPOINT_URL}. Status: {send_response.status_code}")

    except json.JSONDecodeError:
        print("❌ ERROR: Could not decode the message from the queue. It is not valid JSON. Discarding.")
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR: A network error occurred (download or upload): {e}")
        # Requeue the message so the service can try again later, in case the endpoint is temporarily down.
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        return
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        # Don't requeue for unknown errors to avoid an infinite loop of a "poison" message.
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False) 
        return

    # If everything was successful, acknowledge the message to remove it from the queue.
    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_consumer():
    """Starts the service to continuously listen for and process messages with auto-reconnect."""
    print("Starting the final audio sending service...")
    
    while True:
        try:
            connection = pika.BlockingConnection(pika.URLParameters(CLOUDAMQP_URL))
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1) # Process one message at a time
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message_received)

            print(f"[*] Waiting for messages on queue '{QUEUE_NAME}'. To exit press CTRL+C")
            print(f"[*] Forwarding final audio to: {USER_ENDPOINT_URL}")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            print("Connection to RabbitMQ lost. Retrying in 5 seconds...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nService stopped by user.")
            break
        except Exception as e:
            print(f"A critical error occurred: {e}. Restarting consumer in 10 seconds...")
            time.sleep(10)


if __name__ == "__main__":
    start_consumer()