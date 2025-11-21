#!/bin/bash
# Start ADK API server for the robot agent system
# Run from adk-backend directory

cd "$(dirname "$0")"

# Check if .env exists
if [ ! -f .env ]; then
    echo "Error: .env file not found"
    echo "Please create .env with:"
    echo "  OPENROUTER_API_KEY=your_key_here"
    echo "  GOOGLE_API_KEY=your_key_here"
    exit 1
fi

echo "Starting ADK API Server..."
echo "API will be available at: http://localhost:8003"
echo "Docs available at: http://localhost:8003/docs"
echo ""

adk api_server . --host 0.0.0.0 --port 8003 --reload --allow_origins "*"

