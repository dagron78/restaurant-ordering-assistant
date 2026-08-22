"""Tile-matching cases shared by the two F-04 repros.

Every item name below is real in scripts/init_db.py::add_sample_data.
"""

# (item searched for, text of a tile that is NOT that product)
WRONG_PRODUCT = [
    ("Whole Milk",             "Whole Wheat Flour 50lb Bag"),
    ("Ground Beef 80/20",      "Ground Turkey 93/7 Lean"),
    ("Ground Beef 80/20",      "Ground Beef 73/27 Bulk"),
    ("Chicken Breast",         "Chicken Thighs Boneless"),
    ("Heavy Cream 40%",        "Heavy Duty Foil Wrap"),
    ("Atlantic Salmon",        "Atlantic Cod Fillet"),
    ("Olive Oil Extra Virgin", "Canola Oil 35lb"),
]

# (item searched for, text of a tile that IS that product and must keep matching)
RIGHT_PRODUCT = [
    ("Whole Milk",             "Whole Milk Gallon Grade A"),
    ("Ground Beef 80/20",      "Ground Beef 80/20 10lb Case"),
    ("Chicken Breast",         "Chicken Breast Boneless Skinless 40lb"),
    ("Heavy Cream 40%",        "Heavy Cream 40% Qt 12ct"),
    ("Atlantic Salmon",        "Atlantic Salmon Fillet Fresh"),
    ("Olive Oil Extra Virgin", "Extra Virgin Olive Oil 1 Gal"),
    ("Fry Oil 35lb",           "Fry Oil 35lb Jib Clear"),
]
