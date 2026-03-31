#!/bin/bash
# K4GSR Virtual Beamline -- stop all processes
echo "Stopping beamline processes..."
pkill -f "soft_ioc.py" 2>/dev/null && echo "  Soft IOC stopped" || echo "  Soft IOC not running"
pkill -f "server/server.py" 2>/dev/null && echo "  Server stopped" || echo "  Server not running"
echo "Done."
