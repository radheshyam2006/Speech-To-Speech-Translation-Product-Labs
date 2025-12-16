import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
from ASR_API_Manager import ASRMessageProcessor
from Config import CLOUDAMQP_URL

class FastAPIApp:
    """Encapsulates the FastAPI application setup and routes."""

    def __init__(self):
        self.app = FastAPI(lifespan=self.lifespan)
        self.input_queue = 'ASR_input'
        self.output_queue = 'ASR_output'
        self.message_processor = ASRMessageProcessor(
            input_queue=self.input_queue,
            output_queue=self.output_queue,
            cloudamqp_url=CLOUDAMQP_URL
        )

    async def log_message(self, log_msg: str, level: str = "INFO"):
        """Logs messages using the ASRMessageProcessor's log_message method."""
        await self.message_processor.log_message(None, log_msg, level)

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """
        Manages application startup and shutdown events.
        Code before 'yield' runs on startup. Code after 'yield' runs on shutdown.
        """
        log_msg = "Starting RabbitMQ consumer..."
        await self.log_message(log_msg, "INFO")

        consumer_task = asyncio.create_task(self.message_processor.consume_messages())
        print("INFO:     Application startup complete.")

        yield 

        print("INFO:     Application shutting down...")
        consumer_task.cancel()  # Cleanly stop the background task on shutdown

# Initialize the FastAPI application
fastapi_app = FastAPIApp()
app = fastapi_app.app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)