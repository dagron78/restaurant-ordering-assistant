#!/usr/bin/env python3
"""
Database initialization script for Restaurant Ordering Assistant.

Run this script to:
1. Create the database file
2. Initialize the schema
3. Add default data

Usage:
    python scripts/init_db.py [--reset]

Options:
    --reset    Drop all tables and recreate (WARNING: deletes all data)
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import Database


def init_database(reset: bool = False) -> None:
    """
    Initialize the database.
    
    Args:
        reset: If True, drop all existing data first
    """
    print("=" * 50)
    print("Restaurant Ordering Assistant - Database Setup")
    print("=" * 50)
    
    # Ensure directories exist
    Config.ensure_directories()
    print(f"\n✓ Directories created/verified")
    print(f"  Database path: {Config.DATABASE_PATH}")
    print(f"  Sessions path: {Config.SESSIONS_PATH}")
    print(f"  Temp path: {Config.TEMP_PATH}")
    
    # Initialize database
    db = Database()
    
    if reset and Config.DATABASE_PATH.exists():
        print(f"\n⚠️  Resetting database (deleting existing data)...")
        Config.DATABASE_PATH.unlink()
        print(f"✓ Old database deleted")
    
    print(f"\n📦 Initializing database schema...")
    db.init_database()
    print(f"✓ Schema created successfully")
    
    # Verify vendors were created
    vendors = db.get_all_vendors()
    print(f"\n📋 Default vendors:")
    for v in vendors:
        print(f"   - {v['name']} ({v.get('email_domain', 'no domain')})")
    
    # Create sample preferences file if it doesn't exist
    if not Config.PREFERENCES_PATH.exists():
        sample_prefs = """# Restaurant Ordering Preferences
# Write your ordering rules in natural language below.
# The AI will interpret these when making recommendations.

# Example rules (uncomment and modify as needed):
# - Always prefer Sysco for produce items
# - Alert me if Avocados exceed $50 per case
# - Never buy frozen fish from US Foods
# - Quality over price for beef products
# - If Heavy Cream price increases more than 10%, show warning
"""
        Config.PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(Config.PREFERENCES_PATH, 'w') as f:
            f.write(sample_prefs)
        print(f"\n📝 Created sample preferences file: {Config.PREFERENCES_PATH}")
    
    # Validate configuration
    print(f"\n🔍 Configuration validation:")
    validation = Config.validate()
    
    status_icons = {True: '✓', False: '✗'}
    print(f"   {status_icons[validation['gemini_api']]} Gemini API key configured")
    print(f"   {status_icons[validation['email']]} Email credentials configured")
    print(f"   {status_icons[validation['sysco']]} Sysco credentials configured")
    print(f"   {status_icons[validation['usfoods']]} US Foods credentials configured")
    
    if not validation['gemini_api']:
        print(f"\n⚠️  Warning: Gemini API key not configured.")
        print(f"   Copy .env.example to .env and add your API key.")
    
    print(f"\n{'=' * 50}")
    print(f"Database initialization complete!")
    print(f"{'=' * 50}")
    
    if validation['all_valid']:
        print(f"\n🚀 Ready to run! Start the app with:")
        print(f"   streamlit run app/main.py")
    else:
        print(f"\n⚠️  Please configure missing credentials in .env file")
        print(f"   See .env.example for required variables")


def add_sample_data() -> None:
    """Add sample data for testing."""
    db = Database()
    
    print("\n📊 Adding sample data for testing...")
    
    # Sample items
    sample_items = [
        ('Heavy Cream 40%', 'Dairy', 'Case'),
        ('Whole Milk', 'Dairy', 'Gallon'),
        ('Roma Tomatoes', 'Produce', 'Case'),
        ('Avocados Hass', 'Produce', 'Case'),
        ('Chicken Breast', 'Meat', 'Lb'),
        ('Ground Beef 80/20', 'Meat', 'Lb'),
        ('All Purpose Flour', 'Dry Goods', 'Bag'),
        ('Olive Oil Extra Virgin', 'Dry Goods', 'Gallon'),
        ('Fry Oil 35lb', 'Dry Goods', 'Case'),
        ('Atlantic Salmon', 'Seafood', 'Lb'),
    ]
    
    for name, category, unit in sample_items:
        db.add_item(name, category, unit)
    
    print(f"   ✓ Added {len(sample_items)} sample items")
    
    # Sample prices (simulating historical data)
    import random
    from datetime import datetime, timedelta
    
    vendors = ['Sysco', 'US Foods']
    
    base_prices = {
        'Heavy Cream 40%': 24.50,
        'Whole Milk': 3.50,
        'Roma Tomatoes': 22.00,
        'Avocados Hass': 45.00,
        'Chicken Breast': 3.25,
        'Ground Beef 80/20': 4.50,
        'All Purpose Flour': 18.00,
        'Olive Oil Extra Virgin': 28.00,
        'Fry Oil 35lb': 42.00,
        'Atlantic Salmon': 12.50,
    }
    
    price_count = 0
    for item_name, base_price in base_prices.items():
        for vendor in vendors:
            # Add some variation between vendors
            vendor_modifier = random.uniform(0.95, 1.05)
            price = round(base_price * vendor_modifier, 2)
            
            # Get item for unit
            item = db.get_item(name=item_name)
            unit = item.get('default_unit', 'Each') if item else 'Each'
            
            db.add_price(
                item_name=item_name,
                vendor_name=vendor,
                price=price,
                unit=unit,
                source='manual',
                confidence=1.0
            )
            price_count += 1
    
    print(f"   ✓ Added {price_count} sample prices")
    print(f"\n✅ Sample data added successfully!")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Initialize the Restaurant Ordering Assistant database'
    )
    parser.add_argument(
        '--reset', 
        action='store_true',
        help='Drop all tables and recreate (WARNING: deletes all data)'
    )
    parser.add_argument(
        '--sample-data',
        action='store_true',
        help='Add sample data for testing'
    )
    
    args = parser.parse_args()
    
    if args.reset:
        confirm = input("\n⚠️  This will DELETE ALL DATA. Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            sys.exit(0)
    
    init_database(reset=args.reset)
    
    if args.sample_data:
        add_sample_data()
