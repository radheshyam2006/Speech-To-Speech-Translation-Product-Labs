import unittest
from unittest.mock import patch, MagicMock, AsyncMock, ANY
import json
import pika
import asyncio
import requests

from TTS_API_Manager import TTSMessageProcessor
from Config import TTS_DICTIONARY, OUTPUT_LANG

class TestTTSMessageProcessor(unittest.IsolatedAsyncioTestCase):
    """Test cases for the TTS API Manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.input_queue = "test_tts_input"
        self.output_queue = "test_tts_output"
        self.log_queue = "test_log"
        self.cloudamqp_url = ("amqps://keqzgbzz:ooZR8GlQRTtXg6V__RBZd0leDtVYZhrj@puffin.rmq2.cloudamqp.com/keqzgbzz")
        
        self.processor = TTSMessageProcessor(
            input_queue=self.input_queue,
            output_queue=self.output_queue,
            cloudamqp_url=self.cloudamqp_url,
            log_queue=self.log_queue
        )
        
        # Sample translation response for testing (with valid output_text)
        self.sample_mt_json = {
            "status": "success",
            "message": "Translation performed successfully",
            "data": {
                "output_text": "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है."
            },
            "code": 200
        }
        
        # Sample successful TTS API response
        self.sample_tts_response = {
            "status": "success",
            "message": "TTS generation performed successfully",
            "data": {
                "s3_url": "https://tto-asset.s3.ap-south-1.amazonaws.com/tts_output/1744041553_67cbf0643a789165273c494a.wav"
            },
            "code": 200
        }
        
        # Set up the event loop for testing coroutines
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        """Close the event loop after each test."""
        self.loop.close()

    def test_extract_translated_text(self):
        """Test the extract_translated_text method."""
        # Test with a valid MT JSON response
        result = self.processor.extract_translated_text(self.sample_mt_json)
        self.assertEqual(result, "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है.")
        
        # Test with a JSON string
        result = self.processor.extract_translated_text(json.dumps(self.sample_mt_json))
        self.assertEqual(result, "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है.")
        
        # Test with a missing 'data' field
        result = self.processor.extract_translated_text({"status": "success"})
        self.assertIsNone(result)
        
        # Test with a missing 'output_text' field
        result = self.processor.extract_translated_text({"status": "success", "data": {}})
        self.assertIsNone(result)
        
        # Test with invalid JSON (this will print error messages from production code)
        result = self.processor.extract_translated_text("This is not a JSON string")
        self.assertIsNone(result)

    def test_tts_inference_success(self):
        """Test TTS inference with a successful API response."""
        with patch('TTS_API_Manager.requests.post') as mock_post:
            # Mock the requests.post response
            mock_response = MagicMock()
            mock_response.json.return_value = self.sample_tts_response
            mock_post.return_value = mock_response
            
            # Use an AsyncMock for channel (even if not used by requests.post)
            mock_channel = AsyncMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            result = self.loop.run_until_complete(
                self.processor.tts_inference(
                    mock_channel, 
                    "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है."
                )
            )
            
            self.assertEqual(result, self.sample_tts_response)
            
            # Verify that post was called with expected arguments.
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(kwargs["headers"]["access-token"], 
                             TTS_DICTIONARY[OUTPUT_LANG]["access_token"])
            self.assertEqual(kwargs["json"]["text"], 
                             "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है.")
            # Uncomment the following if your API is expected to send a "gender" field:
            # self.assertEqual(kwargs["json"]["gender"], TTS_DICTIONARY[OUTPUT_LANG]["gender"])

    def test_tts_inference_timeout(self):
        """Test TTS inference with a timeout error."""
        with patch('TTS_API_Manager.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout("Request timed out")
            mock_channel = AsyncMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            result = self.loop.run_until_complete(
                self.processor.tts_inference(
                    mock_channel, 
                    "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है."
                )
            )
            
            self.assertIsNone(result)

    def test_tts_inference_http_error(self):
        """Test TTS inference with an HTTP error."""
        with patch('TTS_API_Manager.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 429
            http_error = requests.exceptions.HTTPError("Too Many Requests")
            http_error.response = mock_response
            mock_post.side_effect = http_error
            
            mock_channel = AsyncMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            result = self.loop.run_until_complete(
                self.processor.tts_inference(
                    mock_channel, 
                    "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है."
                )
            )
            
            self.assertIsNone(result)

    @patch("TTS_API_Manager.TTSMessageProcessor.tts_inference", new_callable=AsyncMock)
    async def test_process_message_success(self, mock_tts_inference):
        mock_tts_response = {
            "status": "success",
            "message": "TTS generation performed successfully",
            "data": {
                "s3_url": "https://tto-asset.s3.ap-south-1.amazonaws.com/tts_output/sample.wav"
            },
            "code": 200
        }

        mock_tts_inference.return_value = mock_tts_response

        processor = TTSMessageProcessor(
            input_queue="test_input",
            output_queue="test_tts_output",
            log_queue="test_log",
            cloudamqp_url="amqps://keqzgbzz:ooZR8GlQRTtXg6V__RBZd0leDtVYZhrj@puffin.rmq2.cloudamqp.com/keqzgbzz"
        )

        mock_channel = AsyncMock()
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)

        method_frame = MagicMock()
        method_frame.delivery_tag = "dummy_tag"

        test_input = {
            "data": {
                "output_text": "Hello world"
            }
        }       
        body = json.dumps(test_input).encode()

        success = await processor.process_message(mock_channel, method_frame, body)

        self.assertTrue(success)

        mock_channel.basic_publish(
            exchange='',    
            routing_key='test_tts_output',
            body=json.dumps(mock_tts_response),
            properties=ANY,
            mandatory=True
        )


    def test_process_message_extraction_failure(self):
        """Test processing a message with a failed text extraction."""
        with patch('TTS_API_Manager.TTSMessageProcessor.tts_inference') as mock_tts_inference, \
             patch('TTS_API_Manager.TTSMessageProcessor.extract_translated_text') as mock_extract:
            
            mock_extract.return_value = None  # Extraction failure
            
            mock_channel = AsyncMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            mock_method_frame = MagicMock()
            
            result = self.loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, 
                    mock_method_frame, 
                    json.dumps(self.sample_mt_json).encode()
                )
            )
            
            self.assertFalse(result)
            mock_tts_inference.assert_not_called()

    def test_process_message_tts_inference_failure(self):
        """Test processing a message with a failed TTS inference."""
        with patch('TTS_API_Manager.TTSMessageProcessor.tts_inference') as mock_tts_inference, \
             patch('TTS_API_Manager.TTSMessageProcessor.extract_translated_text') as mock_extract:
            
            mock_extract.return_value = "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है."
            mock_tts_inference.return_value = None  # TTS inference failure
            
            mock_channel = AsyncMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            mock_method_frame = MagicMock()
            
            result = self.loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, 
                    mock_method_frame, 
                    json.dumps(self.sample_mt_json).encode()
                )
            )
            
            self.assertFalse(result)

    def test_process_message_tts_status_failure(self):
        """Test processing a message with a failed status in TTS response."""
        with patch('TTS_API_Manager.TTSMessageProcessor.tts_inference') as mock_tts_inference, \
             patch('TTS_API_Manager.TTSMessageProcessor.extract_translated_text') as mock_extract:
            
            mock_extract.return_value = "हैलो. यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है."
            failed_tts_response = {
                "status": "failed",
                "message": "TTS generation failed",
                "code": 400
            }
            mock_tts_inference.return_value = failed_tts_response
            
            mock_channel = AsyncMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            mock_method_frame = MagicMock()
            
            result = self.loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, 
                    mock_method_frame, 
                    json.dumps(self.sample_mt_json).encode()
                )
            )
            
            self.assertFalse(result)

    def test_process_message_json_decode_error(self):
        """Test processing a message with JSON decode error in the input."""
        with patch('TTS_API_Manager.TTSMessageProcessor.log_message') as mock_log_message:
            mock_channel = AsyncMock()
            mock_channel.queue_declare = MagicMock(return_value=None)
            mock_channel.basic_publish = MagicMock(return_value=None)
            
            mock_method_frame = MagicMock()
            
            result = self.loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, 
                    mock_method_frame, 
                    b"This is not a valid JSON"
                )
            )
            
            self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()
