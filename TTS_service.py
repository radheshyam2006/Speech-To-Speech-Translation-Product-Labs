# Main-5
import asyncio
from fastapi import FastAPI
from TTS_API_Manager import TTSMessageProcessor
from Config import CLOUDAMQP_URL

class FastAPIApp:
    """Encapsulates the FastAPI application setup and routes."""
    
    def __init__(self):
        self.app = FastAPI()
        self.input_queue = 'TTS_input'
        self.output_queue = 'TTS_output'
        self.message_processor = TTSMessageProcessor(
            input_queue=self.input_queue,
            output_queue=self.output_queue,
            cloudamqp_url=CLOUDAMQP_URL
        )

        self.configure_startup()
        
    async def log_message(self, log_msg: str, level: str = "INFO"):
        """Logs messages using the TTSMessageProcessor's log_message method."""
        await self.message_processor.log_message(None, log_msg, level)
        
    def configure_startup(self):
        """Configures the application startup event."""
        
        @self.app.on_event("startup")
        async def start_consumer():
            """Starts message consumption when FastAPI launches."""
            
            log_msg = "Starting RabbitMQ consumer..."
            await self.log_message(log_msg, "INFO")
            # Start consuming messages
            asyncio.create_task(self.message_processor.consume_messages())

# Initialize the FastAPI application
fastapi_app = FastAPIApp()
app = fastapi_app.app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)