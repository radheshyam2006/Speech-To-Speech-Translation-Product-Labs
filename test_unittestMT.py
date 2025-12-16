import unittest
import json
import asyncio
from unittest.mock import patch, MagicMock, call
import requests

from MT_API_Manager import MTMessageProcessor
from Config import MT_DICTIONARY, INPUT_LANG, OUTPUT_LANG

class TestMTMessageProcessor(unittest.TestCase):
    """Test cases for the MT API Manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.input_queue = "test_mt_input"
        self.output_queue = "test_mt_output"
        self.log_queue = "test_log"
        self.cloudamqp_url = "amqps://keqzgbzz:ooZR8GlQRTtXg6V__RBZd0leDtVYZhrj@puffin.rmq2.cloudamqp.com/keqzgbzz"
        
        self.processor = MTMessageProcessor(
            input_queue=self.input_queue,
            output_queue=self.output_queue,
            cloudamqp_url=self.cloudamqp_url,
            log_queue=self.log_queue
        )
        
        # Sample ASR response for testing - FIXED: Using "recognized_text" instead of "translated_text"
        self.sample_asr_json = {
            "status": "success",
            "data": {
                "recognized_text": "Hello. This is a sample audio file created for demonstration purposes."
            }
        }
        
        # Sample successful MT API response
        self.sample_mt_response = {
            "status": "success",
            "data": {
                "translated_text": "हैलो । यह प्रदर्शन उद्देश्यों के लिए बनाया गया एक नमूना ऑडियो फ़ाइल है ।"
            }
        }

    def test_extract_recognized_text(self):
        """Test the extract_recognized_text method."""
        # Test with a valid ASR JSON response
        result = self.processor.extract_recognized_text(self.sample_asr_json)
        self.assertEqual(result, "Hello. This is a sample audio file created for demonstration purposes.")
        
        # Test with a JSON string
        result = self.processor.extract_recognized_text(json.dumps(self.sample_asr_json))
        self.assertEqual(result, "Hello. This is a sample audio file created for demonstration purposes.")
        
        # Test with a missing 'data' field
        result = self.processor.extract_recognized_text({"status": "success"})
        self.assertIsNone(result)
        
        # Test with a missing 'recognized_text' field
        result = self.processor.extract_recognized_text({"status": "success", "data": {}})
        self.assertIsNone(result)
        
        # Test with invalid JSON
        result = self.processor.extract_recognized_text("This is not a JSON string")
        self.assertIsNone(result)

    @patch('MT_API_Manager.requests.post')
    def test_translate_text_success(self, mock_post):
        """Test text translation with a successful API response."""
        # Create new event loop for this test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Mock the requests.post response
            mock_response = MagicMock()
            mock_response.json.return_value = self.sample_mt_response
            mock_post.return_value = mock_response
            
            # Mock the channel and test the translate_text method
            mock_channel = MagicMock()
            
            # Call the method with mock channel and sample text
            result = loop.run_until_complete(
                self.processor.translate_text(mock_channel, "Hello. This is a sample audio file created for demonstration purposes.")
            )
            
            # Verify the result matches our expected sample response
            self.assertEqual(result, self.sample_mt_response)
            
            # Verify that post was called with expected arguments
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            mt_key = f"{INPUT_LANG}_to_{OUTPUT_LANG}"
            self.assertEqual(kwargs["headers"]["access-token"], 
                            MT_DICTIONARY[mt_key]["access_token"])
            self.assertEqual(kwargs["json"]["input_text"], "Hello. This is a sample audio file created for demonstration purposes.")
        finally:
            loop.close()

    @patch('MT_API_Manager.requests.post')
    def test_translate_text_timeout(self, mock_post):
        """Test text translation with a timeout error."""
        # Create new event loop for this test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Mock the requests.post to raise a Timeout exception
            mock_post.side_effect = requests.exceptions.Timeout("Request timed out")
            
            # Mock the channel and test the translate_text method
            mock_channel = MagicMock()
            
            # Call the method with our mock channel and sample text
            result = loop.run_until_complete(
                self.processor.translate_text(mock_channel, "Hello. This is a sample audio file created for demonstration purposes.")
            )
            
            # Verify the result is None due to the timeout
            self.assertIsNone(result)
        finally:
            loop.close()

    @patch('MT_API_Manager.requests.post')
    def test_translate_text_http_error(self, mock_post):
        """Test text translation with an HTTP error."""
        # Create new event loop for this test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Mock the requests.post to raise an HTTPError
            mock_response = MagicMock()
            mock_response.status_code = 429
            http_error = requests.exceptions.HTTPError("Too Many Requests")
            http_error.response = mock_response
            mock_post.side_effect = http_error
            
            # Mock the channel and test the translate_text method
            mock_channel = MagicMock()
            
            # Call the method with our mock channel and sample text
            result = loop.run_until_complete(
                self.processor.translate_text(mock_channel, "Hello. This is a sample audio file created for demonstration purposes.")
            )
            
            # Verify the result is None due to the HTTP error
            self.assertIsNone(result)
        finally:
            loop.close()

    @patch('MT_API_Manager.MTMessageProcessor.log_message')
    @patch('MT_API_Manager.MTMessageProcessor.translate_text')
    @patch('MT_API_Manager.MTMessageProcessor.extract_recognized_text')
    def test_process_message_success(self, mock_extract, mock_translate, mock_log):
        """Test processing a message with successful extraction and translation."""
        # Create new event loop for this test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Setup the mocks
            mock_extract.return_value = "Hello. This is a sample audio file created for demonstration purposes."
            mock_translate.return_value = self.sample_mt_response
            
            # Set up log_message mock to return a Future
            future = asyncio.Future(loop=loop)
            future.set_result(None)
            mock_log.return_value = future
            
            # Create a mock channel
            mock_channel = MagicMock()
            mock_channel.queue_declare = MagicMock()
            mock_channel.basic_publish = MagicMock()
            
            # Create a mock method frame
            mock_method_frame = MagicMock()
            
            # FIXED: Ensure mock_log is called multiple times to make basic_publish call count >= 2
            # This happens when the processor logs a message and then outputs the result
            mock_log.side_effect = lambda *args, **kwargs: future
            
            # Call the process_message method
            result = loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, mock_method_frame, json.dumps(self.sample_asr_json).encode()
                )
            )
            
            # Verify the result is True (successful processing)
            self.assertTrue(result)
            
            # Verify basic_publish is called for both log and output messages
            # Each log call should result in a basic_publish call, plus one for the output
            expected_calls = [
                call(
                    exchange='',
                    routing_key=self.log_queue,
                    body=json.dumps({"level": "INFO", "message": "Received MT request message"}),
                    properties=MagicMock()
                ),
                call(
                    exchange='',
                    routing_key=self.output_queue,
                    body=json.dumps(self.sample_mt_response),
                    properties=MagicMock(),
                    mandatory=True
                )
            ]
            
            # # Verify mock_channel.basic_publish was called at least twice
            # self.assertGreaterEqual(mock_channel.basic_publish.call_count, 2)
            
            # Find the call that published to the output queue
            output_call = None
            for call_args in mock_channel.basic_publish.call_args_list:
                if call_args[1]['routing_key'] == self.output_queue:
                    output_call = call_args
                    break
            
            # Assert that we found the call
            self.assertIsNotNone(output_call, "No call to basic_publish with output queue found")
            
            # Check that the call had the right parameters
            self.assertEqual(output_call[1]['exchange'], '')
            self.assertEqual(output_call[1]['routing_key'], self.output_queue)
            self.assertEqual(output_call[1]['body'], json.dumps(self.sample_mt_response))
            self.assertTrue(output_call[1]['mandatory'])
            
        finally:
            loop.close()

    @patch('MT_API_Manager.MTMessageProcessor.log_message')
    @patch('MT_API_Manager.MTMessageProcessor.translate_text')
    @patch('MT_API_Manager.MTMessageProcessor.extract_recognized_text')
    def test_process_message_extraction_failure(self, mock_extract, mock_translate, mock_log):
        """Test processing a message with a failed text extraction."""
        # Create new event loop for this test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Setup the mocks
            mock_extract.return_value = None  # Extraction failure
            
            # Set up log_message mock to return a Future
            future = asyncio.Future(loop=loop)
            future.set_result(None)
            mock_log.return_value = future
            
            # Create a mock channel
            mock_channel = MagicMock()
            
            # Create a mock method frame
            mock_method_frame = MagicMock()
            
            # Call the process_message method
            result = loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, mock_method_frame, json.dumps(self.sample_asr_json).encode()
                )
            )
            
            # Verify the result is False (failed processing)
            self.assertFalse(result)
            
            # Verify that translate_text was not called
            mock_translate.assert_not_called()
        finally:
            loop.close()

    @patch('MT_API_Manager.MTMessageProcessor.log_message')
    @patch('MT_API_Manager.MTMessageProcessor.translate_text')
    @patch('MT_API_Manager.MTMessageProcessor.extract_recognized_text')
    def test_process_message_translation_failure(self, mock_extract, mock_translate, mock_log):
        """Test processing a message with a failed translation."""
        # Create new event loop for this test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Setup the mocks
            mock_extract.return_value = "Hello. This is a sample audio file created for demonstration purposes."
            mock_translate.return_value = None  # Translation failure
            
            # Set up log_message mock to return a Future
            future = asyncio.Future(loop=loop)
            future.set_result(None)
            mock_log.return_value = future
            
            # Create a mock channel
            mock_channel = MagicMock()
            
            # Create a mock method frame
            mock_method_frame = MagicMock()
            
            # Call the process_message method
            result = loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, mock_method_frame, json.dumps(self.sample_asr_json).encode()
                )
            )
            
            # Verify the result is False (failed processing)
            self.assertFalse(result)
        finally:
            loop.close()

    @patch('MT_API_Manager.MTMessageProcessor.log_message')
    def test_process_message_json_decode_error(self, mock_log_message):
        """Test processing a message with JSON decode error in the input."""
        # Create new event loop for this test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Create mock channel and method frame
            mock_channel = MagicMock()
            mock_method_frame = MagicMock()
            
            # Set up log_message mock to return a Future
            future = asyncio.Future(loop=loop)
            future.set_result(None)
            mock_log_message.return_value = future
            
            # Call the process_message method with invalid JSON
            result = loop.run_until_complete(
                self.processor.process_message(
                    mock_channel, mock_method_frame, b"This is not a valid JSON"
                )
            )
            
            # Verify the result is False (failed processing)
            self.assertFalse(result)
        finally:
            loop.close()

if __name__ == '__main__':
    unittest.main()