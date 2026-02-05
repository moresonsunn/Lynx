#!/bin/bash

# Quality of Life Features Setup Script
# This script sets up the new QoL features for Lynx

set -e

echo "========================================"
echo "  Lynx Quality of Life Features Setup  "
echo "========================================"
echo ""

# Check if we're in the right directory
if [ ! -f "backend/app.py" ]; then
    echo "❌ Error: Please run this script from the Lynx root directory"
    exit 1
fi

echo "✅ Directory check passed"
echo ""

# Install new Python dependencies
echo "📦 Installing new Python dependencies..."
cd backend

# Check if venv exists
if [ -d "venv" ]; then
    echo "   Using existing virtual environment"
    source venv/bin/activate
elif [ -d "../venv" ]; then
    echo "   Using existing virtual environment"
    source ../venv/bin/activate
fi

# Install pyotp for 2FA support
echo "   Installing pyotp for 2FA/TOTP..."
pip install "pyotp>=2.8.0" --quiet

echo "✅ Dependencies installed"
echo ""

# Create UserTwoFactor table
echo "🗄️  Creating database tables..."
python3 << 'EOF'
import sys
sys.path.insert(0, '.')

from database import engine, Base
from models import UserTwoFactor

# Create tables
Base.metadata.create_all(bind=engine)
print("   ✅ UserTwoFactor table created")
EOF

echo "✅ Database setup complete"
echo ""

# Verify imports
echo "🔍 Verifying module imports..."
python3 << 'EOF'
import sys
sys.path.insert(0, '.')

try:
    import ui_enhancements_routes
    print("   ✅ ui_enhancements_routes imported successfully")
except ImportError as e:
    print(f"   ❌ Failed to import ui_enhancements_routes: {e}")
    sys.exit(1)

try:
    import config_management_routes
    print("   ✅ config_management_routes imported successfully")
except ImportError as e:
    print(f"   ❌ Failed to import config_management_routes: {e}")
    sys.exit(1)

try:
    import security_enhanced_routes
    print("   ✅ security_enhanced_routes imported successfully")
except ImportError as e:
    print(f"   ❌ Failed to import security_enhanced_routes: {e}")
    sys.exit(1)
EOF

echo "✅ All modules verified"
echo ""

# Test basic functionality
echo "🧪 Running basic functionality tests..."
python3 << 'EOF'
import sys
sys.path.insert(0, '.')

from ui_enhancements_routes import router as ui_router
from config_management_routes import router as config_router
from security_enhanced_routes import router as security_router

# Check router configurations
assert ui_router.prefix == "/ui-enhancements", "UI router prefix incorrect"
print("   ✅ UI enhancements router configured")

assert config_router.prefix == "/config-management", "Config router prefix incorrect"
print("   ✅ Config management router configured")

assert security_router.prefix == "/security", "Security router prefix incorrect"
print("   ✅ Security router configured")

# Check for key functions
from security_enhanced_routes import _verify_totp, _is_valid_ip

# Test IP validation
assert _is_valid_ip("192.168.1.1") == True, "IPv4 validation failed"
assert _is_valid_ip("invalid") == False, "Invalid IP should fail"
print("   ✅ IP validation working")

print("\n   All tests passed!")
EOF

echo "✅ Functionality tests passed"
echo ""

cd ..

# Display feature summary
echo "=========================================="
echo "  ✅ Setup Complete!"
echo "=========================================="
echo ""
echo "Quality of Life Features Installed:"
echo ""
echo "1. 🎨 UI/UX Enhancements"
echo "   • Advanced search & filtering"
echo "   • Drag & drop file uploads"
echo "   • Terminal command history"
echo "   • Customizable dashboard widgets"
echo "   • User preferences management"
echo "   • Mobile-optimized endpoints"
echo ""
echo "2. ⚙️  Configuration Management"
echo "   • Visual server.properties editor"
echo "   • 6 built-in config templates"
echo "   • Config comparison & diff"
echo "   • Property validation"
echo "   • World seed generator"
echo ""
echo "3. 🔒 Enhanced Security"
echo "   • 2FA/TOTP authentication"
echo "   • IP whitelisting"
echo "   • Enhanced audit logging"
echo "   • Per-server permissions"
echo "   • Security dashboard"
echo ""
echo "📚 Documentation:"
echo "   See QUALITY_OF_LIFE_FEATURES.md for full details"
echo ""
echo "🚀 Next Steps:"
echo "   1. Restart your Lynx server"
echo "   2. Navigate to /docs to see new API endpoints"
echo "   3. Set up 2FA for admin accounts (recommended)"
echo "   4. Configure dashboard widgets in UI"
echo ""
echo "Example API endpoints:"
echo "   POST /security/2fa/setup"
echo "   GET  /config-management/templates"
echo "   POST /ui-enhancements/search/servers"
echo ""
echo "Happy configuring! 🎉"
