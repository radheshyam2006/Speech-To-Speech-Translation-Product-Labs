# MT_API_MANAGER.py (Corrected and Final)

import json
import pika
import asyncio
import requests
from typing import Optional
from Config import MT_DICTIONARY, INPUT_LANG, OUTPUT_LANG, MT_API_TIMEOUT

class MTMessageProcessor:
    """Handles processing and management of RabbitMQ messages for Machine Translation."""

    def __init__(self, input_queue: str, output_queue: str, cloudamqp_url: str, log_queue: str = "log_queue"):
        """
        Initialize MTMessageProcessor with queue configuration.

        Args:
            input_queue: Name of the input queue (expected to receive ASR JSON messages)
            output_queue: Name of the output queue (to publish MT results)
            cloudamqp_url: URL for CloudAMQP connection
            log_queue: Name of the log queue
        """
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.cloudamqp_url = cloudamqp_url
        self.log_queue = log_queue
        mt_key = f"{INPUT_LANG}_to_{OUTPUT_LANG}"
        self.mt_config = MT_DICTIONARY.get(mt_key)
        if not self.mt_config:
            raise ValueError(f"No MT configuration found for language pair: {mt_key}")

    def extract_recognized_text(self, asr_json_response: dict) -> Optional[str]:
        """
        Extracts the recognized text from the simplified ASR response payload.
        This is the primary corrected function.

        Args:
            asr_json_response (dict): The parsed JSON from the input queue.

        Returns:
            Optional[str]: The recognized text if found, else None.
        """
        try:
            # --- THIS IS THE FIX ---
            # The ASR service sends a simple JSON: {"recognized_text": "..."}.
            # This line now correctly looks for the key at the top level,
            # instead of inside a nested "data" object.
            recognized_text = asr_json_response.get("recognized_text")

            if not recognized_text:
                print("No 'recognized_text' key found in the ASR response data.")
            return recognized_text
        except Exception as e:
            print(f"Error extracting recognized text: {e}")
            return None

    async def translate_text(self, channel: pika.channel.Channel, input_text: str) -> Optional[dict]:
        """
        Performs text translation using the Machine Translation API.

        Args:
            channel: RabbitMQ channel for logging.
            input_text: The text to be translated.

        Returns:
            The JSON response from the MT API on success, otherwise None.
        """
        url = self.mt_config["api_endpoint"]
        headers = {
            "access-token": self.mt_config["access_token"],
            "Content-Type": "application/json"
        }
        # [cite_start]Per API spec, the MT request payload is a JSON with the key 'input_text' [cite: 11, 13]
        payload = {"input_text": input_text}
        timeout_value = MT_API_TIMEOUT

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout_value)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

            await self.log_message(channel, "Translation successful.", "TRANSLATION_SUCCESS")
            return response.json()
        except requests.exceptions.Timeout:
            log_msg = f"Translation Error: Request timed out after {timeout_value} seconds."
            await self.log_message(channel, log_msg, "TRANSLATION_ERROR")
            return None
        except requests.exceptions.HTTPError as e:
            log_msg = f"Translation HTTP Error: {e}"
            await self.log_message(channel, log_msg, "TRANSLATION_ERROR")
            return None
        except requests.exceptions.RequestException as e:
            log_msg = f"Translation Request Error: {e}"
            await self.log_message(channel, log_msg, "TRANSLATION_ERROR")
            return None

    async def log_message(self, channel: pika.channel.Channel, log_msg: str, log_level: str):
        """Log a message to the log queue."""
        try:
            if channel is None:
                print(f"Log ({log_level}): {log_msg}")
                return
            log_entry = {"level": log_level, "message": log_msg}
            channel.basic_publish(
                exchange='',
                routing_key=self.log_queue,
                body=json.dumps(log_entry),
                properties=pika.BasicProperties(delivery_mode=2)
            )
        except Exception as e:
            print(f"Failed to publish log message to {self.log_queue}: {e}")

    async def process_message(self, channel: pika.channel.Channel, method_frame: pika.spec.Basic.Deliver, body: bytes) -> bool:
        """
        Processes a single message for Machine Translation.

        Returns:
            bool: True if the message should be acknowledged (ack), False if it should be requeued (nack).
        """
        try:
            await self.log_message(channel, "Received message for translation", "INFO")

            try:
                asr_json_response = json.loads(body)
            except json.JSONDecodeError as e:
                log_msg = f"Failed to decode input JSON: {e}. Discarding message."
                await self.log_message(channel, log_msg, "ERROR")
                return True # Acknowledge and remove malformed message from queue.

            text_to_translate = self.extract_recognized_text(asr_json_response)
            if not text_to_translate:
                log_msg = f"Could not extract 'recognized_text' from payload: {asr_json_response}. Discarding message."
                await self.log_message(channel, log_msg, "ERROR")
                return True # Acknowledge and remove malformed message.

            mt_response = await self.translate_text(channel, text_to_translate)
            if not mt_response or mt_response.get("status") != "success":
                log_msg = "MT API call failed or returned non-success status. Requeuing message."
                await self.log_message(channel, log_msg, "ERROR")
                return False # Requeue the message for a later attempt.

            channel.basic_publish(
                exchange='',
                routing_key=self.output_queue,
                body=json.dumps(mt_response),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            log_msg = f"Successfully published MT result to '{self.output_queue}'"
            await self.log_message(channel, log_msg, "INFO")
            return True # Acknowledge the message as successfully processed.

        except Exception as e:
            log_msg = f"Unexpected error in process_message: {e}. Requeuing message."
            await self.log_message(channel, log_msg, "ERROR")
            return False

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
                    channel.queue_declare(queue=self.input_queue, durable=True)
                    channel.queue_declare(queue=self.output_queue, durable=True)
                    channel.queue_declare(queue=self.log_queue, durable=True)
                    print("INFO:     RabbitMQ connection established for MT service.")
                    retry_delay = 1

                method_frame, _, body = channel.basic_get(queue=self.input_queue, auto_ack=False)

                if method_frame:
                    if await self.process_message(channel, method_frame, body):
                        channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    else:
                        channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                else:
                    await asyncio.sleep(1) # Wait if the queue is empty.

            except pika.exceptions.AMQPConnectionError as e:
                print(f"Log (ERROR): RabbitMQ Connection Error: {e}. Retrying in {retry_delay}s...")
                if connection and not connection.is_closed:
                    connection.close()
                connection = None
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60) # Exponential backoff.
            except Exception as e:
                print(f"Log (ERROR): Unexpected error in consumer loop: {e}. Retrying in 5s...")
                if connection and not connection.is_closed:
                    connection.close()
                connection = None
                await asyncio.sleep(5)