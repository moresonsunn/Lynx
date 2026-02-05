#!/bin/bash
# Quick start script for High-Impact Features

echo "🚀 Lynx High-Impact Features - Quick Start"
echo "=========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "backend/migrate_high_impact.py" ]; then
    echo "❌ Error: Please run this script from the Lynx root directory"
    exit 1
fi

echo "📦 Step 1: Installing dependencies..."
cd backend
pip install -r requirements.txt

echo ""
echo "🗄️ Step 2: Running database migration..."
python migrate_high_impact.py

if [ $? -ne 0 ]; then
    echo "❌ Migration failed. Please check the error messages above."
    exit 1
fi

echo ""
echo "🔄 Step 3: Restarting Docker containers..."
cd ..
docker compose down
docker compose up -d --build

echo ""
echo "⏳ Waiting for services to start..."
sleep 5

echo ""
echo "✅ Setup complete!"
echo ""
echo "📚 Next Steps:"
echo "  1. Visit http://localhost:8000/docs to see new API endpoints"
echo "  2. Read HIGH_IMPACT_FEATURES.md for detailed documentation"
echo "  3. Start using the new features:"
echo ""
echo "     Performance Monitoring:"
echo "     curl -X POST http://localhost:8000/analytics/metrics/collect/YOUR_SERVER"
echo ""
echo "     Create Server Group:"
echo "     curl -X POST http://localhost:8000/multi-server/groups -d '{\"name\":\"My Group\"}'"
echo ""
echo "     Scan Mods:"
echo "     curl -X POST http://localhost:8000/mods-enhanced/scan/YOUR_SERVER"
echo ""
echo "🎉 Enjoy your enhanced Lynx server management platform!"
