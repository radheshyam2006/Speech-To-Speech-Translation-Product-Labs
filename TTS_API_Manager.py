import json
import pika
import asyncio
import requests
from typing import Optional
from Utils import JSONFixer
from Config import TTS_DICTIONARY, OUTPUT_LANG,GENDER, TTS_API_TIMEOUT

class TTSMessageProcessor:
    """Handles processing and management of RabbitMQ messages for Text-to-Speech."""
    
    def __init__(self, input_queue: str, output_queue: str, cloudamqp_url: str, log_queue: str = "log_queue"):
        """
        Initialize TTSMessageProcessor with queue configuration.

        Args:
            input_queue: Name of the input queue (expected to receive translation JSON messages)
            output_queue: Name of the output queue (to publish TTS results)
            cloudamqp_url: URL for CloudAMQP connection
            log_queue: Name of the log queue
        """
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.cloudamqp_url = cloudamqp_url
        self.log_queue = log_queue
        # Choose the TTS model based on the output language.
        self.tts_config = TTS_DICTIONARY.get(OUTPUT_LANG)
        if not self.tts_config:
            raise ValueError(f"No TTS configuration found for output language: {OUTPUT_LANG}")

    def extract_translated_text(self, translation_json) -> str:
        """
        Extract the translated text from the translation API response.

        Args:
            translation_json (dict or str): The JSON response from translation API
            
        Returns:
            str or None: The translated text if successful, None otherwise
        """
        if isinstance(translation_json, str):
            try:
                translation_json = json.loads(translation_json)
            except json.JSONDecodeError as e:
                print(f"Error parsing translation JSON: {e}")
                return None
        
        try:
            translated_text = translation_json.get("data", {}).get("output_text")
            if translated_text:
                return translated_text
            else:
                print("No translated text found in the response")
                return None
        except Exception as e:
            print(f"Error extracting translated text: {e}")
            return None

    async def tts_inference(self, channel: pika.channel.Channel, text: str) -> dict:
        """
        Perform Text-to-Speech (TTS) inference using the TTS API with a timeout.

        Args:
            channel (pika.channel.Channel): RabbitMQ channel for logging
            text (str): The text to convert to speech

        Returns:
            dict: The JSON response from the TTS API if successful, or None on error
        """
        url = self.tts_config["api_endpoint"]
        headers = {
            "access-token": self.tts_config["access_token"],
            "Content-Type": "application/json"
        }
        timeout_value = TTS_API_TIMEOUT

        try:
            payload = {"text": text, "gender": GENDER}
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_value
            )
            response.raise_for_status()

            log_msg = f"TTS Inference successful for {url}."
            await self.log_message(channel, log_msg, "TTS_SUCCESS")
            return response.json()

        except requests.exceptions.Timeout:
            log_msg = f"TTS Error: Request timed out after {timeout_value} seconds."
            await self.log_message(channel, log_msg, "TTS_ERROR")
            return None

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                log_msg = "TTS Error: Too Many Requests (429)."
            else:
                log_msg = f"TTS HTTP Error: {e}"
            await self.log_message(channel, log_msg, "TTS_ERROR")
            return None

        except requests.exceptions.RequestException as e:
            log_msg = f"TTS Error: {e}"
            await self.log_message(channel, log_msg, "TTS_ERROR")
            return None

        except Exception as e:
            log_msg = f"Unexpected TTS Error: {e}"
            await self.log_message(channel, log_msg, "TTS_ERROR")
            return None

    async def log_message(self, channel: pika.channel.Channel, log_msg: str, log_level: str):
        """Log a message to the log queue."""
        try:
            if channel is None:
                print(f"Log ({log_level}): {log_msg}")
                return
            channel.queue_declare(queue=self.log_queue, durable=True)
            log_entry = {"level": log_level, "message": log_msg}
            channel.basic_publish(
                exchange='',
                routing_key=self.log_queue,
                body=json.dumps(log_entry),
                properties=pika.BasicProperties(delivery_mode=2)
            )
        except Exception as e:
            print(f"Failed to publish log message to {self.log_queue}: {e}")

    async def process_message(self, channel: pika.channel.Channel, method_frame: Optional[pika.spec.Basic.Deliver],
                              body: bytes) -> bool:
        """Process a single message with error handling for Text-to-Speech."""
        try:
            log_msg = "Received TTS request message"
            await self.log_message(channel, log_msg, "INFO")

            # The input message is expected to be the translation JSON.
            try:
                translation_json = json.loads(body)
            except Exception as e:
                log_msg = f"Failed to decode input JSON: {e}"
                await self.log_message(channel, log_msg, "ERROR")
                return False

            # Extract translated text from the translation JSON
            translated_text = self.extract_translated_text(translation_json)
            if not translated_text:
                log_msg = "No translated text extracted from translation response"
                await self.log_message(channel, log_msg, "ERROR")
                return False

            # Call the TTS API with the translated text.
            tts_response = await self.tts_inference(channel,translated_text)
            if not tts_response or tts_response.get("status") != "success":
                log_msg = f"TTS failed: {tts_response.get('message', 'Unknown error') if tts_response else 'No response'}"
                await self.log_message(channel, log_msg, "ERROR")
                return False

            try:
                if isinstance(tts_response, dict):
                    tts_response = tts_response
                else:
                    tts_response = json.loads(tts_response)
                log_msg = f"Received valid TTS JSON message: {tts_response}"
                await self.log_message(channel, log_msg, "INFO")
            except Exception as e:
                malformed_queue = f"{self.input_queue}_malformedjson"
                log_msg = f"Malformed TTS JSON detected: {tts_response}"
                await self.log_message(channel, log_msg, "WARNING")
                try:
                    channel.queue_declare(queue=malformed_queue, durable=True)
                    channel.basic_publish(
                        exchange='',
                        routing_key=malformed_queue,
                        body=tts_response,
                        properties=pika.BasicProperties(delivery_mode=2)
                    )
                    log_msg = f"Malformed TTS JSON message pushed to '{malformed_queue}'"
                    await self.log_message(channel, log_msg, "INFO")
                    return True
                except Exception as e:
                    log_msg = f"Failed to push malformed TTS JSON to '{malformed_queue}': {e}"
                    await self.log_message(channel, log_msg, "ERROR")
                    return False

            # Publish the TTS result to the output queue.
            try:
                try:
                    channel.queue_declare(queue=self.output_queue, durable=True, passive=True)
                except pika.exceptions.ChannelClosedByBroker:
                    if channel.is_closed:
                        channel = channel.connection.channel()
                    channel.queue_declare(queue=self.output_queue, durable=True)
                    log_msg = f"Recreated output queue '{self.output_queue}'"
                    await self.log_message(channel, log_msg, "INFO")

                try:
                    channel.basic_publish(
                        exchange='',
                        routing_key=self.output_queue,
                        body=json.dumps(tts_response),
                        properties=pika.BasicProperties(delivery_mode=2),
                        mandatory=True
                    )
                    log_msg = f"Successfully published TTS result to {self.output_queue}"
                    await self.log_message(channel, log_msg, "INFO")
                    return True
                except pika.exceptions.AMQPConnectionError as e:
                    log_msg = f"RabbitMQ Server Down Error: {e}"
                    await self.log_message(channel, log_msg, "ERROR")
                    return False
                except ConnectionResetError:
                    log_msg = "Network disconnected! Reconnecting..."
                    await self.log_message(channel, log_msg, "ERROR")
                    return False
            except Exception as e:
                log_msg = f"Failed to publish TTS message: {e}"
                await self.log_message(channel, log_msg, "ERROR")
                return False

        except Exception as e:
            log_msg = f"Processing TTS Error: {e}"
            await self.log_message(channel, log_msg, "ERROR")
            return False

    async def consume_messages(self):
        retry_delay = 1
        connection = None
        channel = None
        queue_empty_logged = False 
        
        while True:
            try:
                if not connection or connection.is_closed:
                    params = pika.URLParameters(self.cloudamqp_url)
                    params.socket_timeout = 5
                    connection = pika.BlockingConnection(params)
                    channel = connection.channel()
                    channel.queue_declare(queue=self.input_queue, durable=True)
                    channel.queue_declare(queue=self.output_queue, durable=True)
                    channel.queue_declare(queue=self.log_queue, durable=True)


                method_frame, _, body = channel.basic_get(queue=self.input_queue, auto_ack=False)

                if method_frame:
                    if await self.process_message(channel, method_frame, body):
                        channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    else:
                        channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                    queue_empty_logged = False    
                else:
                    if not queue_empty_logged:
                        log_msg = f"Input queue '{self.input_queue}' is currently empty."
                        await self.log_message(channel, log_msg, "INFO")
                        queue_empty_logged = True

                retry_delay = 1

            except pika.exceptions.ChannelClosedByBroker as e:
                error_message = str(e)
                if connection.is_closed:
                    params = pika.URLParameters(self.cloudamqp_url)
                    params.socket_timeout = 5
                    connection = pika.BlockingConnection(params)
                if channel is None or channel.is_closed:
                    channel = connection.channel()

                if "NOT_FOUND - no queue" in error_message:
                    if self.input_queue in error_message:
                        log_msg = f"Input queue '{self.input_queue}' not found. Recreating queue."
                        await self.log_message(channel, log_msg, "ERROR")
                        channel.queue_declare(queue=self.input_queue, durable=True)
                    else:
                        log_msg = f"Queue not found: {error_message}"
                        await self.log_message(channel, log_msg, "ERROR")
                else:
                    log_msg = f"Channel closed by broker: {e}"
                    await self.log_message(channel, log_msg, "ERROR")

            except pika.exceptions.AMQPConnectionError as e:
                log_msg = f"RabbitMQ Server Down Error: {e}"
                await self.log_message(channel, log_msg, "ERROR")
                if connection and not connection.is_closed:
                    connection.close()
                await self.log_message(channel, f"Retrying in {retry_delay} seconds...", "ERROR")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

            except ConnectionResetError:
                log_msg = "Network disconnected! Reconnecting..."
                if connection and not connection.is_closed:
                    connection.close()
                await self.log_message(channel, f"Retrying in {retry_delay} seconds...", "ERROR")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

            except Exception as e:
                log_msg = f"Unexpected error: {e}"
                await self.log_message(channel, log_msg, "ERROR")
                if connection and not connection.is_closed:
                    connection.close()
                await asyncio.sleep(1)

            await asyncio.sleep(0.1)
