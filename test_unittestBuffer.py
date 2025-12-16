import unittest
from unittest.mock import patch, MagicMock, AsyncMock, call, ANY
import json
import pika
import asyncio
import requests
import io
from pydub import AudioSegment

from Buffer_Manager import BufferMessageProcessor

class TestBufferMessageProcessor(unittest.IsolatedAsyncioTestCase):
    """Test cases for the Buffer Manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.input_queue = "test_buffer_input"
        self.output_queue = "test_buffer_output"
        self.log_queue = "test_log"
        self.cloudamqp_url = "amqps://test:test@test.rmq.cloudamqp.com/test"
        
        self.processor = BufferMessageProcessor(
            input_queue=self.input_queue,
            output_queue=self.output_queue,
            cloudamqp_url=self.cloudamqp_url,
            log_queue=self.log_queue
        )
        
        # Sample TTS response for testing
        self.sample_tts_json = {
            "status": "success",
            "data": {
                "s3_url": "https://example.com/audio/test.wav"
            }
        }
        
        # Sample audio data
        self.sample_audio_data = b"fake_audio_data"

    async def test_log_message_with_channel(self):
        """Test the log_message method with a valid channel."""
        # Use MagicMock for synchronous methods.
        mock_channel = MagicMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        
        # Call the log_message method
        await self.processor.log_message(mock_channel, "Test log message", "INFO")
        
        # Verify queue_declare was called
        mock_channel.queue_declare.assert_called_with(queue=self.log_queue, durable=True)
        
        # Verify basic_publish was called with expected args (for the log message)
        mock_channel.basic_publish.assert_called_with(
            exchange='',
            routing_key=self.log_queue,
            body=json.dumps({"level": "INFO", "message": "Test log message"}),
            properties=ANY
        )

    async def test_log_message_without_channel(self):
        """Test the log_message method without a channel (fallback to console)."""
        with patch('builtins.print') as mock_print:
            await self.processor.log_message(None, "Test console log", "WARNING")
            mock_print.assert_called_once()

    async def test_log_message_with_exception(self):
        """Test the log_message method with an exception."""
        mock_channel = MagicMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        # Use side_effect to force an exception.
        mock_channel.basic_publish.side_effect = Exception("Test exception")
        
        with patch('builtins.print') as mock_print:
            await self.processor.log_message(mock_channel, "Test failed log", "ERROR")
            mock_print.assert_called_once()

    @patch('requests.get')
    async def test_process_message_success(self, mock_get):
        """Test processing a message successfully."""
        # Mock the requests.get response for downloading audio.
        mock_response = MagicMock()
        mock_response.content = self.sample_audio_data
        mock_get.return_value = mock_response
        
        # Use MagicMock for channel methods.
        mock_channel = MagicMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        
        # Create a mock method frame and set a delivery_tag for ack.
        mock_method_frame = MagicMock()
        mock_method_frame.delivery_tag = "dummy_tag"
        
        result = await self.processor.process_message(
            mock_channel, mock_method_frame, json.dumps(self.sample_tts_json).encode()
        )
        
        self.assertTrue(result)
        mock_get.assert_called_with("https://example.com/audio/test.wav")
        
        # Verify that one of the basic_publish calls sends the output audio.
        calls = mock_channel.basic_publish.call_args_list
        found = any(
            kwargs.get("routing_key") == self.output_queue and kwargs.get("body") == self.sample_audio_data
            for args, kwargs in calls
        )
        self.assertTrue(found, "Expected basic_publish call for output audio not found")

    @patch('requests.get')
    async def test_process_message_with_large_audio(self, mock_get):
        """Test processing a message with large audio that gets resampled."""
        with patch('Buffer_Manager.AudioSegment') as mock_audio_segment:
            mock_segment = MagicMock()
            mock_segment.set_frame_rate.return_value = mock_segment
            mock_segment.set_channels.return_value = mock_segment
            mock_segment.set_sample_width.return_value = mock_segment
            mock_segment.export.return_value = b"resampled_audio"
            mock_audio_segment.from_file.return_value = mock_segment
            
            large_audio_data = b'0' * 1048577  # Just over 1MB
            
            mock_response = MagicMock()
            mock_response.content = large_audio_data
            mock_get.return_value = mock_response
            
            mock_channel = MagicMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            mock_method_frame = MagicMock()
            mock_method_frame.delivery_tag = "dummy_tag"
            
            result = await self.processor.process_message(
                mock_channel, mock_method_frame, json.dumps(self.sample_tts_json).encode()
            )
            
            self.assertTrue(result)
            mock_audio_segment.from_file.assert_called_once()
            mock_segment.set_frame_rate.assert_called_with(16000)
            mock_segment.set_channels.assert_called_with(1)
            mock_segment.set_sample_width.assert_called_with(2)
            mock_segment.export.assert_called_once()

    async def test_process_message_malformed_json(self):
        """Test processing a message with malformed JSON."""
        mock_channel = MagicMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        
        mock_method_frame = MagicMock()
        mock_method_frame.delivery_tag = "dummy_tag"
        
        malformed_json = b"This is not valid JSON"
        
        result = await self.processor.process_message(
            mock_channel, mock_method_frame, malformed_json
        )
        
        self.assertTrue(result)
        mock_channel.queue_declare.assert_any_call(
            queue=f"{self.input_queue}_malformedjson", 
            durable=True
        )
        calls = mock_channel.basic_publish.call_args_list
        found = any(
            kwargs.get("routing_key") == f"{self.input_queue}_malformedjson" and kwargs.get("body") == malformed_json
            for args, kwargs in calls
        )
        self.assertTrue(found, "Expected basic_publish call with malformed JSON not found")

    @patch('requests.get')
    async def test_process_message_missing_s3_url(self, mock_get):
        """Test processing a message with missing s3_url."""
        mock_channel = MagicMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        
        mock_method_frame = MagicMock()
        mock_method_frame.delivery_tag = "dummy_tag"
        
        json_missing_url = {"status": "success", "data": {}}
        
        result = await self.processor.process_message(
            mock_channel, mock_method_frame, json.dumps(json_missing_url).encode()
        )
        
        self.assertFalse(result)
        mock_get.assert_not_called()

    @patch('requests.get')
    async def test_process_message_download_error(self, mock_get):
        """Test processing a message with an error during download."""
        mock_get.side_effect = Exception("Download failed")
        
        mock_channel = MagicMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        
        mock_method_frame = MagicMock()
        mock_method_frame.delivery_tag = "dummy_tag"
        
        result = await self.processor.process_message(
            mock_channel, mock_method_frame, json.dumps(self.sample_tts_json).encode()
        )
        
        self.assertFalse(result)

    @patch('pika.BlockingConnection')
    @patch('pika.URLParameters')
    async def test_consume_messages_successful_message(self, mock_url_params, mock_connection):
        """Test consume_messages with a successful message processing."""
        # For consume_messages, basic_get and basic_ack are synchronous.
        mock_channel = MagicMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        
        mock_method_frame = MagicMock()
        mock_method_frame.delivery_tag = "dummy_tag"
        mock_body = json.dumps(self.sample_tts_json).encode()
        mock_channel.basic_get = MagicMock(side_effect=[(mock_method_frame, None, mock_body), (None, None, None)])
        mock_channel.basic_ack = MagicMock()
        
        # Configure connection to return our channel.
        mock_connection.return_value.channel.return_value = mock_channel
        
        with patch.object(self.processor, 'process_message', new=MagicMock()) as mock_process:
            fut = asyncio.Future()
            fut.set_result(True)
            mock_process.return_value = fut
            
            task = asyncio.create_task(self.processor.consume_messages())
            await asyncio.sleep(0.1)  # Let it run briefly
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            mock_process.assert_called_once_with(mock_channel, mock_method_frame, mock_body)
            mock_channel.basic_ack.assert_called_once_with(delivery_tag=mock_method_frame.delivery_tag)

if __name__ == '__main__':
    unittest.main()
