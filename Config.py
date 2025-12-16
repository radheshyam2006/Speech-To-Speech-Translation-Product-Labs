"""Configuration settings for the RabbitMQ service, ASR API, and Machine Translation API."""

CLOUDAMQP_URL = "amqps://keqzgbzz:ooZR8GlQRTtXg6V__RBZd0leDtVYZhrj@puffin.rmq2.cloudamqp.com/keqzgbzz"

INPUT_LANG = "english"
OUTPUT_LANG = "hindi"
GENDER = "male"

ASR_API_TIMEOUT = 60
MT_API_TIMEOUT = 60 
TTS_API_TIMEOUT = 60

ASR_DICTIONARY = {
    "english": {
        "api_endpoint": "https://canvas.iiit.ac.in/sandboxbeprod/infer_asr/67127dcbb1a6984f0c5e7d35",
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiNjhlYTYyNWZiOTNlM2JlYzkwMWZkOGRiIiwicm9sZSI6Im1lZ2F0aG9uX3N0dWRlbnQifQ.SM6UU6Tf02jtHFzfQVXHGxyVyjrBnMGcf91opPK1ukE"
    },
}

MT_DICTIONARY = {
    "english_to_hindi": {
        "api_endpoint": "https://canvas.iiit.ac.in/sandboxbeprod/check_model_status_and_infer/689184d2abd5a58fafefd50f",
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiNjhlYTY1Y2FiOTNlM2JlYzkwMWZkOTI0Iiwicm9sZSI6Im1lZ2F0aG9uX3N0dWRlbnQifQ.VUihfHbOiRSwiT5bqrfwNhPOh5NVOofAtEF_LYA51uw"
    },
}

TTS_DICTIONARY = {
    "hindi": {
        "api_endpoint": "https://canvas.iiit.ac.in/sandboxbeprod/generate_tts/67bca89ae0b95a6a1ea34a92",
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiNjhlYTY1Y2FiOTNlM2JlYzkwMWZkOTI0Iiwicm9sZSI6Im1lZ2F0aG9uX3N0dWRlbnQifQ.VUihfHbOiRSwiT5bqrfwNhPOh5NVOofAtEF_LYA51uw"
    },
}
