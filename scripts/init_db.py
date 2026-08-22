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
    print("\n✓ Directories created/verified")
    print(f"  Database path: {Config.DATABASE_PATH}")
    print(f"  Sessions path: {Config.SESSIONS_PATH}")
    print(f"  Temp path: {Config.TEMP_PATH}")
    
    # Initialize database
    db = Database()
    
    if reset and Config.DATABASE_PATH.exists():
        print("\n⚠️  Resetting database (deleting existing data)...")
        Config.DATABASE_PATH.unlink()
        print("✓ Old database deleted")
    
    print("\n📦 Initializing database schema...")
    db.init_database()
    print("✓ Schema created successfully")
    
    # Verify vendors were created
    vendors = db.get_all_vendors()
    print("\n📋 Default vendors:")
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
    print("\n🔍 Configuration validation:")
    validation = Config.validate()
    
    status_icons = {True: '✓', False: '✗'}
    print(f"   {status_icons[validation['gemini_api']]} Gemini API key configured")
    print(f"   {status_icons[validation['email']]} Email credentials configured")
    
    if not validation['gemini_api']:
        print("\n⚠️  Warning: Gemini API key not configured.")
        print("   Copy .env.example to .env and add your API key.")
    
    print(f"\n{'=' * 50}")
    print("Database initialization complete!")
    print(f"{'=' * 50}")
    
    if validation['all_valid']:
        print("\n🚀 Ready to run! Start the app with:")
        print("   streamlit run app/main.py")
    else:
        print("\n⚠️  Please configure missing credentials in .env file")
        print("   See .env.example for required variables")


def add_sample_data(db: Database = None, days: int = 30) -> None:
    """
    Add sample data with simulated price history.
    
    Prices are spread across the past `days` days with a gentle drift so
    the trend chart and deal/spike indicators have something real to show
    on first run (every row stamped today would read "stable" forever).
    
    Args:
        db: Database instance (creates new if not provided)
        days: Number of days of history to simulate
    """
    import random
    from datetime import date, timedelta
    
    # Deterministic so demos and screenshots are reproducible
    random.seed(42)
    
    db = db or Database()
    
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
    
    vendors = ['Sysco', 'US Foods']
    today = date.today()
    
    # Build all rows first, then insert as ONE batch - add_price() opens
    # three connections per row, which is ~1800 for this loop otherwise.
    rows = []
    for item_name, base_price in base_prices.items():
        item = db.get_item(name=item_name)
        unit = item.get('default_unit', 'Each') if item else 'Each'
        
        for vendor in vendors:
            # Per-vendor level and drift direction across the window
            vendor_modifier = random.uniform(0.95, 1.05)
            total_drift = random.uniform(-0.15, 0.15)
            
            # Oldest first: date_recorded defines which row is "latest"
            for day_offset in range(days - 1, -1, -1):
                progress = (days - 1 - day_offset) / max(days - 1, 1)
                daily_noise = random.uniform(0.98, 1.02)
                price = round(
                    base_price * vendor_modifier
                    * (1 + total_drift * progress)
                    * daily_noise,
                    2
                )
                
                rows.append({
                    'item_name': item_name,
                    'vendor_name': vendor,
                    'price': price,
                    'unit': unit,
                    'confidence': 1.0,
                    'date_recorded': (today - timedelta(days=day_offset)).isoformat(),
                })
    
    price_count = db.add_prices_batch(rows, source='manual')
    
    print(f"   ✓ Added {price_count} sample prices across {days} days")
    print("\n✅ Sample data added successfully!")


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
