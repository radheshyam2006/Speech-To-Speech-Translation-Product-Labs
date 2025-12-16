import json
import pika
import asyncio
import requests
from typing import Optional
from Config import ASR_DICTIONARY, INPUT_LANG, ASR_API_TIMEOUT

class ASRMessageProcessor:
    """Handles processing and management of RabbitMQ messages for ASR."""

    def __init__(self, input_queue: str, output_queue: str, cloudamqp_url: str, log_queue: str = "log_queue"):
        """Initializes the message processor with queue and API configurations."""
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.cloudamqp_url = cloudamqp_url
        self.log_queue = log_queue
        self.asr_config = ASR_DICTIONARY.get(INPUT_LANG)
        if not self.asr_config:
            raise ValueError(f"No ASR configuration found for input language: {INPUT_LANG}")

    async def asr_inference(self, channel: pika.channel.Channel, audio_data: bytes) -> Optional[dict]:
        """
        Performs ASR inference by sending audio data to the external API.

        [cite_start]The request is sent as form-data with an 'audio_file' field[cite: 26, 27].
        [cite_start]Headers must include an 'access-token' for authentication[cite: 4, 7].

        Returns:
            Optional[dict]: The JSON response from the API on success, otherwise None.
        """
        url = self.asr_config["api_endpoint"]
        headers = {"access-token": self.asr_config["access_token"]}
        files = {"audio_file": ("audio.wav", audio_data, "audio/wav")}
        timeout_value = ASR_API_TIMEOUT

        try:
            response = requests.post(url, headers=headers, files=files, timeout=timeout_value)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

            log_msg = f"ASR Inference successful for {url}."
            await self.log_message(channel, log_msg, "ASR_INFERENCE")
            return response.json()

        except requests.exceptions.Timeout:
            log_msg = f"ASR Inference Error: Request timed out after {timeout_value} seconds."
            await self.log_message(channel, log_msg, "ASR_INFERENCE")
            return None

        except requests.exceptions.HTTPError as e:
            log_msg = f"ASR Inference HTTP Error: {e}"
            await self.log_message(channel, log_msg, "ASR_INFERENCE")
            return None

        except requests.exceptions.RequestException as e:
            log_msg = f"ASR Inference Request Error: {e}"
            await self.log_message(channel, log_msg, "ASR_INFERENCE")
            return None

    async def log_message(self, channel: pika.channel.Channel, log_msg: str, log_level: str):
        """Publishes a log message to the designated log queue."""
        try:
            if channel is None:
                # Fallback for logging when channel is not available (e.g., during connection loss)
                print(f"Log ({log_level}): {log_msg}")
                return

            log_entry = {"level": log_level, "message": log_msg}
            channel.basic_publish(
                exchange='',
                routing_key=self.log_queue,
                body=json.dumps(log_entry),
                properties=pika.BasicProperties(delivery_mode=2)  # Make log messages persistent
            )
        except Exception as e:
            print(f"Failed to publish log message to '{self.log_queue}': {e}")

    async def process_message(self, channel: pika.channel.Channel, method_frame: pika.spec.Basic.Deliver, body: bytes) -> bool:
        """
        Processes a single message from the input queue.

        Returns:
            bool: True if the message was processed successfully and should be acknowledged.
                  False if processing failed and the message should be requeued.
        """
        await self.log_message(channel, "Received audio file for ASR inference", "INFO")

        asr_response = await self.asr_inference(channel, body)

        # **CRITICAL FIX**: Check for None to prevent crashes on API failure.
        if not asr_response:
            log_msg = "ASR inference failed (e.g., timeout or HTTP error). Message will be requeued."
            await self.log_message(channel, log_msg, "ERROR")
            return False

        # [cite_start]Check for success status in the API response payload[cite: 31].
        if asr_response.get("status") != "success":
            log_msg = f"API returned non-success status: {asr_response.get('message', 'Unknown API error')}"
            await self.log_message(channel, log_msg, "ERROR")
            return False

        # [cite_start]Extract the recognized text according to the API specification[cite: 33, 35].
        data = asr_response.get("data", {})
        recognized_text = data.get("recognized_text")

        if recognized_text is None:
            log_msg = f"API response successful but missing 'recognized_text'. Response: {asr_response}"
            await self.log_message(channel, log_msg, "ERROR")
            return False

        try:
            # Publish the successful result to the output queue.
            output_payload = json.dumps({"recognized_text": recognized_text})
            channel.basic_publish(
                exchange='',
                routing_key=self.output_queue,
                body=output_payload,
                properties=pika.BasicProperties(delivery_mode=2)
            )
            log_msg = f"Successfully published recognized text to '{self.output_queue}'"
            await self.log_message(channel, log_msg, "INFO")
            return True  # Acknowledge the message.

        except Exception as e:
            log_msg = f"Failed to publish result to output queue: {e}"
            await self.log_message(channel, log_msg, "ERROR")
            return False # Requeue if publishing fails.

    async def consume_messages(self):
        """Continuously consumes messages with a robust reconnection loop."""
        retry_delay = 1
        connection = None
        while True:
            try:
                if not connection or connection.is_closed:
                    params = pika.URLParameters(self.cloudamqp_url)
                    connection = pika.BlockingConnection(params)
                    channel = connection.channel()
                    # Ensure all necessary queues exist.
                    channel.queue_declare(queue=self.input_queue, durable=True)
                    channel.queue_declare(queue=self.output_queue, durable=True)
                    channel.queue_declare(queue=self.log_queue, durable=True)
                    await self.log_message(None, "RabbitMQ connection established.", "INFO")
                    retry_delay = 1 # Reset delay after successful connection.

                method_frame, _, body = channel.basic_get(queue=self.input_queue, auto_ack=False)

                if method_frame:
                    if await self.process_message(channel, method_frame, body):
                        channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    else:
                        # Requeue the message upon any processing failure.
                        channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                else:
                    # Wait if the queue is empty to avoid busy-waiting.
                    await asyncio.sleep(1)

            except pika.exceptions.AMQPConnectionError as e:
                log_msg = f"RabbitMQ Connection Error: {e}. Retrying in {retry_delay}s..."
                await self.log_message(None, log_msg, "ERROR")
                if connection and not connection.is_closed:
                    connection.close()
                connection = None
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Exponential backoff up to 60 seconds.

            except Exception as e:
                log_msg = f"Unexpected error in consumer loop: {e}. Retrying in 5s..."
                await self.log_message(None, log_msg, "ERROR")
                if connection and not connection.is_closed:
                    connection.close()
                connection = None
                await asyncio.sleep(5)