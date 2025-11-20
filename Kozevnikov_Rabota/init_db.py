# init_db.py
import sqlite3
from werkzeug.security import generate_password_hash

connection = sqlite3.connect('cars.db')
cursor = connection.cursor()


def ensure_column(table, column, definition):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cursor.fetchall()}
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'customer',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER NOT NULL,
    price INTEGER NOT NULL,
    mileage INTEGER,
    fuel_type TEXT,
    country TEXT NOT NULL,
    image_url TEXT,
    description TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT,
    car_id INTEGER,
    preferred_brand TEXT,
    preferred_model TEXT,
    country TEXT,
    budget INTEGER,
    comment TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    FOREIGN KEY (car_id) REFERENCES cars (id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    car_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    location TEXT NOT NULL,
    eta TEXT,
    comment TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (car_id) REFERENCES cars (id) ON DELETE CASCADE
)
''')

ensure_column('leads', 'user_id', 'INTEGER REFERENCES users(id) ON DELETE SET NULL')
ensure_column('users', 'role', "TEXT NOT NULL DEFAULT 'customer'")

cursor.execute("SELECT COUNT(*) FROM cars")
has_records = cursor.fetchone()[0]

if not has_records:
    cursor.executemany(
        "INSERT INTO cars (brand, model, year, price, mileage, fuel_type, country, image_url, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ('Hyundai', 'Sonata', 2021, 25000, 15000, 'Petrol', 'Korea', 'https://images.pexels.com/photos/102399/pexels-photo-102399.jpeg', 'Современный бизнес-седан для долгих поездок.'),
            ('Kia', 'Sorento', 2022, 42000, 5000, 'Hybrid', 'Korea', 'https://images.pexels.com/photos/97075/pexels-photo-97075.jpeg', 'Полный привод, 7 мест, топовая комплектация.'),
            ('BYD', 'Han', 2023, 45000, 0, 'Electric', 'China', 'https://images.pexels.com/photos/210019/pexels-photo-210019.jpeg', 'Премиальный электромобиль с запасом хода 600 км.'),
            ('Geely', 'Monjaro', 2022, 36000, 8000, 'Petrol', 'China', 'https://images.pexels.com/photos/358070/pexels-photo-358070.jpeg', 'Большой кроссовер «под ключ» за 30 дней.'),
        ]
    )

cursor.execute("SELECT id FROM users WHERE email = ?", ('demo@asiadrive.com',))
user = cursor.fetchone()
if not user:
    cursor.execute(
        "INSERT INTO users (name, email, phone, password_hash, role) VALUES (?, ?, ?, ?, ?)",
        ('Demo Manager', 'demo@asiadrive.com', '+82 10 1234 5678', generate_password_hash('demo1234'), 'admin')
    )
    user_id = cursor.lastrowid
else:
    user_id = user[0]
    cursor.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))

cursor.execute("SELECT id FROM users WHERE email = ?", ('moderator@asiadrive.com',))
moder = cursor.fetchone()
if not moder:
    cursor.execute(
        "INSERT INTO users (name, email, phone, password_hash, role) VALUES (?, ?, ?, ?, ?)",
        ('Moderator Kim', 'moderator@asiadrive.com', '+82 10 3434 5656', generate_password_hash('mod1234'), 'moderator')
    )

cursor.execute("SELECT COUNT(*) FROM tracking_events")
tracking_count = cursor.fetchone()[0]

if tracking_count == 0:
    cursor.executemany(
        "INSERT INTO tracking_events (car_id, status, location, eta, comment) VALUES (?, ?, ?, ?, ?)",
        [
            (1, 'На складе Пусан', 'Пусан, Южная Корея', '7 дней', 'Ждём место на пароме.'),
            (2, 'В пути по морю', 'Жёлтое море', '12 дней', 'Контейнер закреплён на судне AsiaStar.'),
            (3, 'Таможня РФ', 'Владивосток', '5 дней', 'Оформление ПТС.'),
            (4, 'Доставка по РФ', 'Новосибирск', '3 дня', 'Отправлено автотранспортом.'),
        ]
    )

connection.commit()
connection.close()

print("База данных обновлена. Добавлены пользователи, заявки и статусы доставки.")