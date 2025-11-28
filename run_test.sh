#!/bin/bash

# URL of the SMS service endpoint
URL="http://localhost:8003/notifications/send-sms/"

# JSON payload
DATA='{
  "phone": "+251930376854",
  "message": "Hello! This is a test SMS from the SMS Service."
}'

echo "Sending SMS request to $URL..."
echo "Payload: $DATA"

# Send POST request
curl -X POST "$URL" \
     -H "Content-Type: application/json" \
     -d "$DATA"

echo -e "\nDone."
