import subprocess
import time
import sys

# A list of all the services that need to run in the background.
# These are your "workers" who will run continuously.
pipeline_services = [
    ("ASR Service", [sys.executable, "ASR_service.py"]),
    ("ASR_MT Bridge", [sys.executable, "ASR_MT_bridge.py"]),
    ("MT Service", [sys.executable, "MT_service.py"]),
    ("MT_TTS Bridge", [sys.executable, "MT_TTS_bridge.py"]),
    ("TTS Service", [sys.executable, "TTS_service.py"])
]

# A list to keep track of all the running processes
processes = []

print("🚀 Starting all pipeline services in the background...")

try:
    # Loop through and start each service
    for name, command in pipeline_services:
        print(f"-> Starting {name}...")
        
        # Use Popen to start the script as a non-blocking background process
        proc = subprocess.Popen(command)
        processes.append((name, proc))
        
        # Give a short delay for each service to initialize
        time.sleep(2)

    print("\n✅ All services are running in the background.")
    print("The pipeline is now active and waiting for messages.")
    print("Press Ctrl+C in this terminal to stop all services.")
    
    # Keep the main script alive while the background services run
    while True:
        time.sleep(10)

except KeyboardInterrupt:
    # This block runs when you press Ctrl+C
    print("\n🛑 Shutting down all services...")
    
    # Terminate all the background processes in reverse order
    for name, proc in reversed(processes):
        print(f"-> Terminating {name} (PID: {proc.pid})...")
        proc.terminate()
    
    # Wait for all processes to confirm termination
    for name, proc in processes:
        proc.wait()

    print("✅ All services stopped.")