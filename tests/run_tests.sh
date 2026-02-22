#!/bin/bash
# Run mock server and tests

cd /home/ada/save4223/cabinet-pi

echo "🚀 Starting Mock Save4223 API Server..."
python3 tests/mock_server.py &
SERVER_PID=$!

sleep 2

echo ""
echo "🧪 Running API Tests..."
python3 tests/test_api.py

TEST_RESULT=$?

echo ""
echo "🛑 Stopping Mock Server..."
kill $SERVER_PID 2>/dev/null

exit $TEST_RESULT
