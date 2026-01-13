#!/bin/bash
# Script to intelligently start or restart the Ashoka API service

# Function to check if API is running
is_api_running() {
    PID=$(ps aux | grep "python3 api.py" | grep -v grep | awk '{print $2}')
    if [ ! -z "$PID" ]; then
        return 0  # API is running
    else
        return 1  # API is not running
    fi
}

# Function to stop existing API process
stop_api() {
    echo "Stopping existing API process..."
    PID=$(ps aux | grep "python3 api.py" | grep -v grep | awk '{print $2}')
    if [ ! -z "$PID" ]; then
        echo "Killing process $PID"
        kill $PID
        sleep 2
        
        # Check if process is still running and force kill if needed
        if ps -p $PID > /dev/null 2>&1; then
            echo "Process still running, force killing..."
            kill -9 $PID
            sleep 1
        fi
        echo "Process stopped"
        return 0
    else
        echo "No existing API process found"
        return 1
    fi
}

# Function to start API
start_api() {
    echo "Starting API process..."
    
    # Create logs directory if it doesn't exist
    mkdir -p logs
    
    # Activate virtual environment if it exists
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
    
    # Start the API in background (stderr to log file, stdout silent)
    python3 api.py >> logs/api.log 2>&1 &
    NEW_PID=$!
    echo "Started API process with PID: $NEW_PID"
    
    # Wait a moment and check if it's running
    sleep 2
    if ps -p $NEW_PID > /dev/null 2>&1; then
        echo "API service started successfully"
        return 0
    else
        echo "Warning: API service may have failed to start"
        return 1
    fi
}

# Main logic
echo "=== Ashoka API Start/Restart Script ==="

if is_api_running; then
    echo "API is currently running - performing restart..."
    if stop_api; then
        echo "Successfully stopped existing API"
    fi
    start_api
else
    echo "API is not running - performing fresh start..."
    start_api
fi

echo "=== Script completed ==="
