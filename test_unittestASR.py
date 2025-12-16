import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import json
import pika
import asyncio
import requests
from io import BytesIO
from unittest.mock import ANY

from ASR_API_Manager import ASRMessageProcessor
from Config import ASR_DICTIONARY, INPUT_LANG

class FakeStringWithGet(str):
    def get(self, key, default=None):
        if key == "status":
            return "success"
        if key == "message":
            return "Unknown error"
        return default

class TestASRMessageProcessor(unittest.IsolatedAsyncioTestCase):
    """Test cases for the ASR API Manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.input_queue = "test_asr_input"
        self.output_queue = "test_asr_output"
        self.log_queue = "test_log"
        self.cloudamqp_url = "amqps://keqzgbzz:ooZR8GlQRTtXg6V__RBZd0leDtVYZhrj@puffin.rmq2.cloudamqp.com/keqzgbzz"
        
        self.processor = ASRMessageProcessor(
            input_queue=self.input_queue,
            output_queue=self.output_queue,
            cloudamqp_url=self.cloudamqp_url,
            log_queue=self.log_queue
        )
        
        # Sample audio data for testing
        self.sample_audio_data = b"test_audio_data"
        
        # Sample successful API response
        self.sample_api_response = {
            "status": "success",
            "data": {
                "recognized_text": "This is a test audio message"
            }
        }

    @patch('ASR_API_Manager.requests.post')
    async def test_asr_inference_success(self, mock_post):
        """Test ASR inference with a successful API response."""
        # Mock the requests.post response
        mock_response = MagicMock()
        mock_response.json.return_value = self.sample_api_response
        mock_post.return_value = mock_response
        
        # Use an AsyncMock for the channel so that awaited methods are properly mocked.
        mock_channel = AsyncMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)

        
        result = await self.processor.asr_inference(mock_channel, self.sample_audio_data)
        self.assertEqual(result, self.sample_api_response)
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["access-token"], 
                         ASR_DICTIONARY[INPUT_LANG]["access_token"])
        self.assertIn("files", kwargs)
        self.assertIn("audio_file", kwargs["files"])

    @patch('ASR_API_Manager.requests.post')
    async def test_asr_inference_timeout(self, mock_post):
        """Test ASR inference with a timeout error."""
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")
        
        mock_channel = AsyncMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)

        result = await self.processor.asr_inference(mock_channel, self.sample_audio_data)
        self.assertIsNone(result)

    @patch('ASR_API_Manager.requests.post')
    async def test_asr_inference_http_error(self, mock_post):
        """Test ASR inference with an HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        http_error = requests.exceptions.HTTPError("Too Many Requests")
        http_error.response = mock_response
        mock_post.side_effect = http_error
        
        mock_channel = AsyncMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)

        result = await self.processor.asr_inference(mock_channel, self.sample_audio_data)
        self.assertIsNone(result)

    @patch('ASR_API_Manager.ASRMessageProcessor.asr_inference')
    async def test_process_message_success(self, mock_asr_inference):
        """Test processing a message with successful ASR inference."""
        mock_asr_inference.return_value = self.sample_api_response
        
        mock_channel = AsyncMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)

        
        mock_method_frame = MagicMock()
        result = await self.processor.process_message(
            mock_channel, mock_method_frame, self.sample_audio_data
        )
        self.assertTrue(result)
        
        mock_channel.basic_publish.assert_any_call(
            exchange='',
            routing_key=self.output_queue,
            body=json.dumps(self.sample_api_response),
            properties=unittest.mock.ANY,
            mandatory=True
        )

    @patch('ASR_API_Manager.ASRMessageProcessor.asr_inference')
    async def test_process_message_asr_failure(self, mock_asr_inference):
        """Test processing a message with a failed ASR inference."""
        mock_asr_inference.return_value = None
        
        mock_channel = AsyncMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)

        
        mock_method_frame = MagicMock()
        result = await self.processor.process_message(
            mock_channel, mock_method_frame, self.sample_audio_data
        )
        self.assertFalse(result)

    @patch("ASR_API_Manager.pika.BasicProperties", new=lambda **kwargs: MagicMock())
    @patch("ASR_API_Manager.ASRMessageProcessor.log_message", new_callable=AsyncMock)
    @patch("ASR_API_Manager.ASRMessageProcessor.asr_inference", new_callable=AsyncMock)
    async def test_process_message_json_decode_error(self, mock_inference, mock_log_message):
        """Test processing a message where ASR inference returns malformed (non-JSON) response."""
        processor = ASRMessageProcessor(
            input_queue="test_asr_input",
            output_queue="test_asr_output",
            cloudamqp_url="amqp://test",
            log_queue="test_log"
        )

        # Helper class to simulate a string with a .get() method.
        class FakeStringWithGet(str):
            def get(self, key, default=None):
                if key == "status":
                    return "success"
                if key == "message":
                    return "Unknown error"
                return default

        # Return a malformed JSON string that supports .get()
        malformed_response = FakeStringWithGet("INVALID_JSON_RESPONSE")
        mock_inference.return_value = malformed_response

        # Set up a channel mock, but override queue_declare and basic_publish as synchronous mocks.
        mock_channel = AsyncMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)

        # Run process_message.
        result = await processor.process_message(mock_channel, None, b"dummy audio")
        self.assertTrue(result)

        # Instead of checking await behavior, we check that the methods were called with the expected arguments.
        mock_log_message.assert_any_call(
            mock_channel, 
            "Malformed JSON detected: INVALID_JSON_RESPONSE", 
            "WARNING"
        )
        mock_channel.queue_declare.assert_called_with(
            queue="test_asr_input_malformedjson", 
            durable=True
        )
        mock_channel.basic_publish.assert_called_with(
            exchange='',
            routing_key="test_asr_input_malformedjson",
            body="INVALID_JSON_RESPONSE",
            properties=ANY
        )


if __name__ == '__main__':
    unittest.main() 