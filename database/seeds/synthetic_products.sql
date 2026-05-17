-- Synthetic product seed data for development and testing.
-- Run after migrations: psql $DATABASE_URL -f database/seeds/synthetic_products.sql
-- Or via Supabase CLI dashboard SQL editor.
-- ON CONFLICT DO NOTHING makes this idempotent — safe to run multiple times.

INSERT INTO products (name, brand, category, base_price, current_price, specs, stock_count, avg_rating, is_active)
VALUES
    (
        'Dell XPS 15 9530',
        'Dell',
        'laptops',
        125000.00,
        125000.00,
        '{"cpu": "Intel Core i7-13700H", "ram_gb": 16, "storage_gb": 512, "display_inches": 15.6, "battery_wh": 86, "weight_kg": 1.86, "gpu": "NVIDIA RTX 4060"}',
        50,
        4.5,
        true
    ),
    (
        'Apple MacBook Pro 14 M3',
        'Apple',
        'laptops',
        199000.00,
        199000.00,
        '{"cpu": "Apple M3", "ram_gb": 18, "storage_gb": 512, "display_inches": 14.2, "battery_wh": 70, "weight_kg": 1.55, "gpu": "Apple M3 10-core"}',
        30,
        4.8,
        true
    ),
    (
        'Lenovo ThinkPad X1 Carbon Gen 11',
        'Lenovo',
        'laptops',
        145000.00,
        145000.00,
        '{"cpu": "Intel Core i7-1365U", "ram_gb": 16, "storage_gb": 512, "display_inches": 14.0, "battery_wh": 57, "weight_kg": 1.12, "gpu": "Intel Iris Xe"}',
        25,
        4.4,
        true
    ),
    (
        'Sony WH-1000XM5',
        'Sony',
        'headphones',
        29990.00,
        29990.00,
        '{"type": "over-ear", "noise_cancellation": true, "battery_hours": 30, "weight_kg": 0.25, "wireless": true}',
        100,
        4.7,
        true
    ),
    (
        'Samsung Galaxy Tab S9 Ultra',
        'Samsung',
        'tablets',
        109999.00,
        109999.00,
        '{"display_inches": 14.6, "ram_gb": 12, "storage_gb": 256, "battery_wh": 44.5, "weight_kg": 0.732, "stylus": true}',
        40,
        4.3,
        true
    )
ON CONFLICT DO NOTHING;
