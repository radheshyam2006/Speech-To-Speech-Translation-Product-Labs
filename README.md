# Real-time Speech-to-Speech Translation Pipeline

**Product Labs, IIIT Hyderabad**  
*January 2025 – March 2025*

## Overview

A high-performance, real-time speech-to-speech translation system that enables seamless cross-language audio communication. The pipeline processes audio in 300 ms chunks, providing near-instantaneous translation with smooth playback through intelligent buffering.

## Key Features

- **Real-time Processing**: Audio chunks processed in 300 ms intervals for minimal latency
- **Robust Message Queue**: RabbitMQ-based architecture with durable queues for reliable message delivery
- **Intelligent Buffering**: Sophisticated buffer management ensures smooth, uninterrupted audio playback
- **Error Resilience**: Comprehensive error handling and persistent messaging system that significantly reduced failure rates
- **Modular Architecture**: Decoupled components (ASR, MT, TTS) connected via message bridges for scalability

## Architecture

The system consists of three main components connected via message bridges:

```
Audio Input → ASR Service → MT Service → TTS Service → Audio Output
                 ↓             ↓            ↓
              RabbitMQ     RabbitMQ    RabbitMQ
                 ↓             ↓            ↓
           (Durable Queues with Error Handling)
```

### Components

1. **ASR (Automatic Speech Recognition)**
   - Converts incoming audio chunks to text
   - Managed by `ASR_service.py` and `ASR_API_Manager.py`

2. **MT (Machine Translation)**
   - Translates text from source to target language
   - Managed by `MT_service.py` and `MT_API_Manager.py`

3. **TTS (Text-to-Speech)**
   - Synthesizes translated text back to audio
   - Managed by `TTS_service.py` and `TTS_API_Manager.py`

4. **Buffer Management**
   - Ensures smooth audio playback despite network/processing variations
   - Implements intelligent queuing and synchronization

5. **Message Bridges**
   - `ASR_MT_bridge.py`: Connects ASR output to MT input
   - `MT_TTS_bridge.py`: Connects MT output to TTS input
   - `TTS_Buffer_bridge.py`: Manages TTS output buffering

## Installation

### Prerequisites

- Python 3.8+
- RabbitMQ server
- Audio input/output devices

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd "varun dass"
   ```

2. **Install dependencies**
   ```bash
   pip install -r req.txt
   ```

3. **Configure RabbitMQ**
   - Ensure RabbitMQ is running on your system
   - Update connection settings in `Config.py`

4. **Configure Services**
   - Edit `Config.py` to set API keys and service endpoints
   - Adjust audio chunk size and buffer parameters as needed

## Usage

### Starting the Pipeline

1. **Start RabbitMQ services**
   ```bash
   # Ensure RabbitMQ server is running
   rabbitmq-server
   ```

2. **Launch services in separate terminals**

   Terminal 1 - ASR Service:
   ```bash
   python ASR_service.py
   ```

   Terminal 2 - MT Service:
   ```bash
   python MT_service.py
   ```

   Terminal 3 - TTS Service:
   ```bash
   python TTS_service.py
   ```

3. **Start message bridges**

   Terminal 4:
   ```bash
   python ASR_MT_bridge.py
   ```

   Terminal 5:
   ```bash
   python MT_TTS_bridge.py
   ```

   Terminal 6:
   ```bash
   python TTS_Buffer_bridge.py
   ```

4. **Begin audio processing**
   ```bash
   # Send audio chunks
   python send.py

   # Receive and play translated audio
   python receive.py
   ```

### Testing

Run the test suite to verify system functionality:

```bash
# Unit tests
python test_unittestASR.py
python test_unittestMT.py
python test_unittestTTS.py
python test_unittestBuffer.py

# Integration tests
python test_integration.py

# End-to-end tests
python test_endtoend.py
```

## Project Structure

```
.
├── ASR_service.py           # ASR microservice
├── ASR_API_Manager.py       # ASR API interface
├── MT_service.py            # Machine translation microservice
├── MT_API_Manager.py        # MT API interface
├── TTS_service.py           # Text-to-speech microservice
├── TTS_API_Manager.py       # TTS API interface
├── ASR_MT_bridge.py         # ASR to MT message bridge
├── MT_TTS_bridge.py         # MT to TTS message bridge
├── TTS_Buffer_bridge.py     # TTS to buffer message bridge
├── Buffer_Manager.py        # Audio buffer management
├── Message_Processor.py     # Message processing utilities
├── ChunksPush.py            # Audio chunk handling
├── send.py                  # Audio sender
├── receive.py               # Audio receiver
├── playbufferaudio.py       # Audio playback utilities
├── Generateaudio.py         # Audio generation utilities
├── Config.py                # Configuration settings
├── Utils.py                 # Utility functions
├── arch.py                  # Architecture definitions
├── test_*.py                # Test suites
└── req.txt                  # Python dependencies
```

## Technologies Used

- **Python**: Core programming language
- **RabbitMQ**: Message queue for reliable inter-service communication
- **Speech Recognition APIs**: ASR implementation
- **Translation APIs**: Machine translation services
- **Speech Synthesis APIs**: TTS implementation
- **Audio Processing Libraries**: For chunk management and playback

## Key Technical Achievements

- **300 ms Latency**: Optimized chunk processing for real-time performance
- **Durable Queues**: Persistent messaging that reduced failure rates significantly
- **Smart Buffering**: Eliminated audio stuttering and gaps during playback
- **Error Recovery**: Comprehensive error handling ensures system resilience
- **Scalable Design**: Modular architecture allows independent scaling of components

## Configuration

Edit `Config.py` to customize:

- Audio chunk size (default: 300 ms)
- RabbitMQ connection parameters
- API endpoints and credentials
- Buffer size and playback parameters
- Queue durability settings
- Error retry policies


### Common Issues

1. **Audio stuttering**: Increase buffer size in `Config.py`
2. **Connection errors**: Verify RabbitMQ is running and accessible
3. **High latency**: Reduce audio chunk size or optimize API response times
4. **Message loss**: Ensure durable queues are enabled in configuration

## Future Enhancements

- [ ] Support for multiple concurrent translation sessions
- [ ] Web-based UI for easy configuration
- [ ] Additional language pairs
- [ ] Real-time quality metrics dashboard
- [ ] Docker containerization for easier deployment

## Contributors

**Product Labs, IIIT Hyderabad**

## Acknowledgments

Special thanks to IIIT Hyderabad Product Labs for supporting this research and development project.

---

For questions or support, please contact radheshyam.modampuri@students.iiit.ac.in
