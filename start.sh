#!/bin/bash
echo "Starting Quant Auto-Memory Daemon..."
python cloud_auto_memory.py &

echo "Starting Flask Quant Dashboard..."
gunicorn -w 1 -b 0.0.0.0:$PORT quant_dashboard:app
