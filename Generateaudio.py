import os
from gtts import gTTS
from pydub import AudioSegment

class AudioGenerator:
    @staticmethod
    def generate_audio(output_path="input_audio.wav"):
        text = (
            "Hello, this is a sample audio file created for demonstration purposes. "
            "The purpose of this recording is to provide clear and articulate English speech. "
            "It is intended to serve as a test of audio generation capabilities and to ensure that the resulting file lasts exactly thirty seconds. "
            "Please listen to this recording and note the quality of the synthesized voice as it conveys the intended message. "
            "Thank you for using this service. Enjoy this demonstration."
        )

        # Generate speech with gTTS
        tts = gTTS(text, lang='en')
        temp_mp3 = "temp_output.mp3"
        tts.save(temp_mp3)

        # Convert the MP3 to WAV, adjust properties, and ensure the duration is exactly 30 seconds (30,000ms)
        audio = AudioSegment.from_mp3(temp_mp3)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)  # 16kHz, Mono, 16-bit
        target_duration_ms = 30000
        current_duration_ms = len(audio)

        # Adjust the audio duration to exactly 30 seconds.
        if current_duration_ms < target_duration_ms:
            silence_duration = target_duration_ms - current_duration_ms
            silence = AudioSegment.silent(duration=silence_duration)
            audio = audio + silence
        elif current_duration_ms > target_duration_ms:
            audio = audio[:target_duration_ms]

        # Export the audio file as a WAV file.
        audio.export(output_path, format="wav", bitrate="64k")
        print(f"Generated {output_path} with duration {len(audio)/1000:.2f} seconds.")

        # Clean up temporary MP3 file.
        os.remove(temp_mp3)
        return output_path

if __name__ == "__main__":
    AudioGenerator.generate_audio()
