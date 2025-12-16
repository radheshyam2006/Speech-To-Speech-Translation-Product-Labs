import json
import pika
import asyncio
from typing import Optional
from Utils import JSONFixer

class MessageProcessor:

    """Handles processing and management of RabbitMQ messages."""

    def __init__(self, input_queue: str, output_queue: str, cloudamqp_url: str, log_queue: str = "log_queue"):

        """
        Initialize MessageProcessor with queue configuration.

        Args:
            input_queue: Name of the input queue
            output_queue: Name of the output queue
            cloudamqp_url: URL for CloudAMQP connection
            log_queue: Name of the log queue
        """
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.cloudamqp_url = cloudamqp_url
        self.log_queue = log_queue

    async def log_message(self, channel: pika.channel.Channel, log_msg: str, log_level: str):
        """Log a message to the log queue."""
        if channel is None:
            # Fallback: Log to console if channel is not available.
            print(f"[{log_level}] {log_msg}")
            return

        try:
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
        """Process a single message with error handling."""

        try:
            data = json.loads(body)
            log_msg = f"Received valid JSON message: {data}"
            await self.log_message(channel, log_msg, "INFO")
        except json.JSONDecodeError:
            malformed_queue = f"{self.input_queue}_malformedjson"
            log_msg = f"Malformed JSON detected: {body}"
            await self.log_message(channel, log_msg, "WARNING")

            try:
                channel.queue_declare(queue=malformed_queue, durable=True)
                channel.basic_publish(
                    exchange='',
                    routing_key=malformed_queue,
                    body=body,
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                log_msg = f"Malformed JSON message pushed to '{malformed_queue}'"
                await self.log_message(channel, log_msg, "INFO")
                return True
            except Exception as e:
                log_msg = f"Failed to push malformed JSON to '{malformed_queue}': {e}"
                await self.log_message(channel, log_msg, "ERROR")
                return False

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
                    body=json.dumps(data),
                    properties=pika.BasicProperties(delivery_mode=2),
                    mandatory=True
                )

                log_msg = f"Successfully published to {self.output_queue}"
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
            log_msg = f"Failed to publish message: {e}"
            await self.log_message(channel, log_msg, "ERROR")
            return False

    async def consume_messages(self):
        """Main message consumption loop."""

        retry_delay = 1
        connection = None
        channel = None
        queue_empty_logged = False # Flag to log empty queue once
        
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
                    params.socket_timeout = 5  # Set timeout for connection
                    connection = pika.BlockingConnection(params)
                if channel.is_closed:
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
