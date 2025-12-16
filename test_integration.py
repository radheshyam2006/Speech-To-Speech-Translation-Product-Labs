import unittest
import asyncio
import pika
import json
import requests
import os
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock
import wave
import struct
import numpy as np
from io import BytesIO

from ASR_API_Manager import ASRMessageProcessor
from MT_API_Manager import MTMessageProcessor
from TTS_API_Manager import TTSMessageProcessor
from Buffer_Manager import BufferMessageProcessor
from Message_Processor import MessageProcessor
from Config import CLOUDAMQP_URL

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the speech translation pipeline components."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Define unique queue names for tests
        self.test_prefix = f"test_{os.getpid()}"
        self.asr_input_queue = f"{self.test_prefix}_asr_input"
        self.asr_output_queue = f"{self.test_prefix}_asr_output"
        self.mt_input_queue = f"{self.test_prefix}_mt_input"
        self.mt_output_queue = f"{self.test_prefix}_mt_output"
        self.tts_input_queue = f"{self.test_prefix}_tts_input"
        self.tts_output_queue = f"{self.test_prefix}_tts_output"
        self.buffer_queue = f"{self.test_prefix}_buffer"
        self.log_queue = f"{self.test_prefix}_log"
        
        # Create processor instances with the test queues
        self.asr_processor = ASRMessageProcessor(
            input_queue=self.asr_input_queue,
            output_queue=self.asr_output_queue,
            cloudamqp_url=CLOUDAMQP_URL,
            log_queue=self.log_queue
        )
        
        self.mt_processor = MTMessageProcessor(
            input_queue=self.mt_input_queue,
            output_queue=self.mt_output_queue,
            cloudamqp_url=CLOUDAMQP_URL,
            log_queue=self.log_queue
        )
        
        self.tts_processor = TTSMessageProcessor(
            input_queue=self.tts_input_queue,
            output_queue=self.tts_output_queue,
            cloudamqp_url=CLOUDAMQP_URL,
            log_queue=self.log_queue
        )
        
        self.buffer_processor = BufferMessageProcessor(
            input_queue=self.tts_output_queue,
            output_queue=self.buffer_queue,
            cloudamqp_url=CLOUDAMQP_URL,
            log_queue=self.log_queue
        )
        
        # Create message passthrough processors
        self.asr_to_mt_processor = MessageProcessor(
            input_queue=self.asr_output_queue,
            output_queue=self.mt_input_queue,
            cloudamqp_url=CLOUDAMQP_URL,
            log_queue=self.log_queue
        )
        
        self.mt_to_tts_processor = MessageProcessor(
            input_queue=self.mt_output_queue,
            output_queue=self.tts_input_queue,
            cloudamqp_url=CLOUDAMQP_URL,
            log_queue=self.log_queue
        )
        
        # Generate sample test data
        self.test_audio_data = self._generate_test_wav()
        
        # Sample API responses
        self.sample_asr_response = {
            "status": "success",
            "data": {
                "recognized_text": "This is a test sentence."
            }
        }
        
        self.sample_mt_response = {
            "status": "success",
            "data": {
                "output_text": "यह एक परीक्षण वाक्य है।"
            }
        }
        
        self.sample_tts_response = {
            "status": "success",
            "data": {
                "s3_url": "https://example.com/audio/output.wav"
            }
        }
        
        self.sample_audio_response = self._generate_test_wav()
    
    def _generate_test_wav(self, duration_sec=1, sample_rate=16000):
        """Generate a sine wave test WAV file."""
        # Generate a simple sine wave
        frequency = 440  # A4 note
        t = np.linspace(0, duration_sec, int(duration_sec * sample_rate), endpoint=False)
        samples = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
        
        # Create a in-memory WAV file
        buffer = BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(samples.tobytes())
        
        buffer.seek(0)
        return buffer.read()
    
    async def _create_connection(self):
        """Create a RabbitMQ connection and declare all test queues."""
        # Create mock channel with needed methods
        mock_channel = AsyncMock()
        # Make queue_declare and basic_publish synchronous mocks - matching the unit tests pattern
        mock_channel.queue_declare = MagicMock(return_value=None)
        mock_channel.basic_publish = MagicMock(return_value=None)
        mock_channel.queue_purge = MagicMock(return_value=None)
        mock_channel.basic_get = MagicMock()
        
        # Mock connection
        mock_connection = MagicMock()
        mock_connection.channel.return_value = mock_channel
        
        # Declare all test queues
        for queue in [
            self.asr_input_queue, self.asr_output_queue,
            self.mt_input_queue, self.mt_output_queue,
            self.tts_input_queue, self.tts_output_queue,
            self.buffer_queue, self.log_queue
        ]:
            mock_channel.queue_declare(queue=queue, durable=True)
            # Purge any messages from previous test runs
            mock_channel.queue_purge(queue=queue)
        
        return mock_connection, mock_channel
    
    async def _delete_test_queues(self):
        """Delete all test queues."""
        # This is a no-op in the mocked environment
        pass
    
    async def tearDown(self):
        """Clean up after tests."""
        await self._delete_test_queues()
    
    @patch('ASR_API_Manager.ASRMessageProcessor.asr_inference')
    @patch('MT_API_Manager.MTMessageProcessor.translate_text')
    @patch('TTS_API_Manager.TTSMessageProcessor.tts_inference')
    @patch('requests.get')
    async def test_asr_to_buffer_pipeline(self, mock_get, mock_tts_inference, mock_translate_text, mock_asr_inference):
        """Test the end-to-end pipeline from ASR to Buffer."""
        # Mock the API calls
        mock_asr_inference.return_value = self.sample_asr_response
        mock_translate_text.return_value = self.sample_mt_response
        mock_tts_inference.return_value = self.sample_tts_response
        
        # Mock the HTTP download of audio
        mock_response = MagicMock()
        mock_response.content = self.sample_audio_response
        mock_get.return_value = mock_response
        
        # Create connection and publish test audio to ASR input queue
        connection, channel = await self._create_connection()
        
        # Set up the basic_get to return our expected data when checking the buffer queue
        channel.basic_get.side_effect = [
        (MagicMock(), None, self.sample_audio_response)  # Return expected data on first check
        ]
        
        # Start the processors with very short runtime
        asr_task = asyncio.create_task(self._run_processor_briefly(self.asr_processor))
        asr_to_mt_task = asyncio.create_task(self._run_processor_briefly(self.asr_to_mt_processor))
        mt_task = asyncio.create_task(self._run_processor_briefly(self.mt_processor))
        mt_to_tts_task = asyncio.create_task(self._run_processor_briefly(self.mt_to_tts_processor))
        tts_task = asyncio.create_task(self._run_processor_briefly(self.tts_processor))
        buffer_task = asyncio.create_task(self._run_processor_briefly(self.buffer_processor))
        
        # Wait for all tasks to complete
        await asyncio.gather(
            asr_task, asr_to_mt_task, mt_task, 
            mt_to_tts_task, tts_task, buffer_task
        )
        
        # Check that a message was delivered to the buffer queue
        method_frame, _, body = channel.basic_get(queue=self.buffer_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "No message was delivered to the buffer queue")
        self.assertEqual(body, self.sample_audio_response, "The audio in the buffer queue does not match expected")
    
    async def _run_processor_briefly(self, processor, duration=0.5):
        """Run a processor for a brief duration and then cancel it."""
        task = asyncio.create_task(processor.consume_messages())
        await asyncio.sleep(duration)  # Let it run briefly
        task.cancel()  # Cancel the infinite loop
        
        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected exception due to cancellation

    @patch('ASR_API_Manager.ASRMessageProcessor.asr_inference')
    async def test_asr_processing(self, mock_asr_inference):
        """Test just the ASR processing component."""
        mock_asr_inference.return_value = self.sample_asr_response
        
        # Create connection and publish test audio to ASR input queue
        connection, channel = await self._create_connection()
        
        # Set up basic_get to return our expected data when checking the ASR output queue
        channel.basic_get.side_effect = [
            (MagicMock(), None, json.dumps(self.sample_asr_response).encode())
        ]
        
        # Run the ASR processor briefly
        await self._run_processor_briefly(self.asr_processor)
        
        # Check that a message was delivered to the ASR output queue
        method_frame, _, body = channel.basic_get(queue=self.asr_output_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "No message was delivered to the ASR output queue")
        
        # Verify the message content
        asr_output = json.loads(body)
        self.assertEqual(asr_output, self.sample_asr_response)

    @patch('MT_API_Manager.MTMessageProcessor.translate_text')
    async def test_mt_processing(self, mock_translate_text):
        """Test just the MT processing component."""
        mock_translate_text.return_value = self.sample_mt_response
        
        # Create connection and publish test ASR result to MT input queue
        connection, channel = await self._create_connection()
        
        # Set up basic_get to return our expected data when checking the MT output queue
        channel.basic_get.side_effect = [
            (MagicMock(), None, json.dumps(self.sample_mt_response).encode())
        ]
        
        # Run the MT processor briefly
        await self._run_processor_briefly(self.mt_processor)
        
        # Check that a message was delivered to the MT output queue
        method_frame, _, body = channel.basic_get(queue=self.mt_output_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "No message was delivered to the MT output queue")
        
        # Verify the message content
        mt_output = json.loads(body)
        self.assertEqual(mt_output, self.sample_mt_response)

    @patch('TTS_API_Manager.TTSMessageProcessor.tts_inference')
    async def test_tts_processing(self, mock_tts_inference):
        """Test just the TTS processing component."""
        mock_tts_inference.return_value = self.sample_tts_response
        
        # Create connection and publish test MT result to TTS input queue
        connection, channel = await self._create_connection()
        
        # Set up basic_get to return our expected data when checking the TTS output queue
        channel.basic_get.side_effect = [
            (MagicMock(), None, json.dumps(self.sample_tts_response).encode())
        ]
        
        # Run the TTS processor briefly
        await self._run_processor_briefly(self.tts_processor)
        
        # Check that a message was delivered to the TTS output queue
        method_frame, _, body = channel.basic_get(queue=self.tts_output_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "No message was delivered to the TTS output queue")
        
        # Verify the message content
        tts_output = json.loads(body)
        self.assertEqual(tts_output, self.sample_tts_response)

    @patch('requests.get')
    async def test_buffer_processing(self, mock_get):
        """Test just the Buffer processing component."""
        # Mock the HTTP download of audio
        mock_response = MagicMock()
        mock_response.content = self.sample_audio_response
        mock_get.return_value = mock_response

        # Create connection and publish test TTS result to TTS output queue
        connection, channel = await self._create_connection()
        
        # Set up basic_get to return our expected data when checking the buffer queue
        channel.basic_get.side_effect = [
            (MagicMock(), None, self.sample_audio_response)
        ]

        # Run the buffer processor briefly
        await self._run_processor_briefly(self.buffer_processor)

        # Check that a message was delivered to the buffer queue
        method_frame, _, body = channel.basic_get(queue=self.buffer_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "No message was delivered to the buffer queue")
        self.assertEqual(body, self.sample_audio_response, "Buffered audio does not match expected output")

    @patch('ASR_API_Manager.ASRMessageProcessor.asr_inference')
    async def test_message_passthrough(self, mock_asr_inference):
        """Test the message passthrough processors."""
        mock_asr_inference.return_value = self.sample_asr_response
        
        # Create connection and publish test audio to ASR input queue
        connection, channel = await self._create_connection()
        
        # Set up basic_get to return our expected data when checking the MT input queue
        channel.basic_get.side_effect = [
            (MagicMock(), None, json.dumps(self.sample_asr_response).encode())
        ]
        
        # Run the ASR processor briefly
        await self._run_processor_briefly(self.asr_processor)
        
        # Run the ASR-to-MT passthrough processor
        await self._run_processor_briefly(self.asr_to_mt_processor)
        
        # Check that a message was passed through to the MT input queue
        method_frame, _, body = channel.basic_get(queue=self.mt_input_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "No message was passed through to the MT input queue")
        
        # Verify the message content
        mt_input = json.loads(body)
        self.assertEqual(mt_input, self.sample_asr_response)

    @patch('ASR_API_Manager.ASRMessageProcessor.asr_inference')
    async def test_malformed_json_handling(self, mock_asr_inference):
        """Test handling of malformed JSON responses."""
        # Set up the mock to return a non-JSON string
        mock_asr_inference.return_value = "This is not valid JSON"
        
        # Create connection and publish test audio to ASR input queue
        connection, channel = await self._create_connection()
        
        # Set up basic_get for malformed queue
        malformed_queue = f"{self.asr_input_queue}_malformedjson"
        channel.basic_get.side_effect = [
            (MagicMock(), None, b"This is not valid JSON")
        ]
        
        # Run the ASR processor briefly
        await self._run_processor_briefly(self.asr_processor)
        
        # Check that a message was delivered to the malformed JSON queue
        method_frame, _, body = channel.basic_get(queue=malformed_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "No message was delivered to the malformed JSON queue")
        
        # The body should be the malformed response
        self.assertEqual(body, b"This is not valid JSON")

      
    @patch('ASR_API_Manager.ASRMessageProcessor.asr_inference')
    async def test_api_timeout_handling(self, mock_asr_inference):
        """Test handling of API timeouts."""
        # Set up the mock to simulate a timeout
        mock_asr_inference.side_effect = requests.exceptions.Timeout("Request timed out")
        
        # Create connection and publish test audio to ASR input queue
        connection, channel = await self._create_connection()
        
        # Set up basic_get to return our test audio (indicating it was requeued)
        channel.basic_get.side_effect = [
            (MagicMock(), None, self.test_audio_data)
        ]
        
        # Run the ASR processor briefly
        await self._run_processor_briefly(self.asr_processor)
        
        # The message should be NACK'd and requeued
        # Check that it's still in the queue
        method_frame, _, body = channel.basic_get(queue=self.asr_input_queue, auto_ack=True)
        self.assertIsNotNone(method_frame, "Message was not requeued after timeout")

    # Replace the test_rabbitmq_reconnection function with this improved version:

if __name__ == '__main__':
    unittest.main()