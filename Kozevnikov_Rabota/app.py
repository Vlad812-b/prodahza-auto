# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'cars.db')

app = Flask(__name__)
app.config['DATABASE'] = DATABASE_PATH
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')


def get_db_connection():
    connection = sqlite3.connect(app.config['DATABASE'])
    connection.row_factory = sqlite3.Row
    return connection


def ensure_column_exists(connection, table_name, column_name, column_definition):
    cursor = connection.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
        connection.commit()


def ensure_tables():
    connection = sqlite3.connect(app.config['DATABASE'])
    cursor = connection.cursor()

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

    ensure_column_exists(connection, 'leads', 'user_id', 'INTEGER REFERENCES users(id) ON DELETE SET NULL')
    ensure_column_exists(connection, 'users', 'role', "TEXT NOT NULL DEFAULT 'customer'")

    connection.commit()
    connection.close()


ensure_tables()


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_current_user():
    if hasattr(g, 'current_user'):
        return g.current_user
    user_id = session.get('user_id')
    if not user_id:
        g.current_user = None
        return None
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    connection.close()
    g.current_user = user
    return user


@app.context_processor
def inject_user():
    user = get_current_user()
    return {
        'current_user': user,
        'is_admin': bool(user and user['role'] == 'admin'),
        'is_moderator': bool(user and user['role'] == 'moderator'),
        'is_customer': bool(user and user['role'] == 'customer')
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not get_current_user():
            flash('Войдите в личный кабинет, чтобы оформить заявку.', 'error')
            return redirect(url_for('login', next=request.url))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if not user:
                flash('Войдите в личный кабинет, чтобы продолжить.', 'error')
                return redirect(url_for('login', next=request.url))
            if roles and user['role'] not in roles:
                flash('У вас нет прав для этого действия.', 'error')
                return redirect(url_for('index'))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def latest_tracking(cursor):
    cursor.execute(
        """
        SELECT t.*
        FROM tracking_events t
        INNER JOIN (
            SELECT car_id, MAX(updated_at) AS max_updated
            FROM tracking_events
            GROUP BY car_id
        ) latest ON latest.car_id = t.car_id AND latest.max_updated = t.updated_at
        """
    )
    return {row['car_id']: row for row in cursor.fetchall()}


@app.route('/')
def index():
    country_filter = request.args.get('country')
    normalized_country = None
    if country_filter:
        normalized_country = country_filter.strip().lower().capitalize()
    search_query = request.args.get('q')

    connection = get_db_connection()
    cursor = connection.cursor()

    query = "SELECT * FROM cars"
    params = []
    clauses = []

    if normalized_country and normalized_country.lower() in {'china', 'korea'}:
        clauses.append("LOWER(country) = ?")
        params.append(normalized_country)

    if search_query:
        clauses.append("(LOWER(brand) LIKE ? OR LOWER(model) LIKE ?)")
        like_pattern = f"%{search_query.lower()}%"
        params.extend([like_pattern, like_pattern])

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY year DESC"

    cursor.execute(query, params)
    cars = cursor.fetchall()

    tracking_map = latest_tracking(cursor)

    cursor.execute("SELECT DISTINCT country FROM cars")
    countries = sorted({row['country'] for row in cursor.fetchall() if row['country']})

    connection.close()

    return render_template(
        'index.html',
        cars=cars,
        countries=countries,
        selected_country=normalized_country,
        search_query=search_query,
        tracking_map=tracking_map
    )


@app.route('/add', methods=['GET'])
@role_required('admin', 'moderator')
def add_car_form():
    return render_template('add_car.html')


@app.route('/add', methods=['POST'])
@role_required('admin', 'moderator')
def add_car():
    required_fields = ['brand', 'model', 'year', 'price', 'country']
    missing = [field for field in required_fields if not request.form.get(field)]
    if missing:
        flash('Пожалуйста, заполните все обязательные поля.', 'error')
        return redirect(url_for('add_car_form'))

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO cars (brand, model, year, price, mileage, fuel_type, country, image_url, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request.form.get('brand').strip(),
            request.form.get('model').strip(),
            safe_int(request.form.get('year')) or 0,
            safe_int(request.form.get('price')) or 0,
            safe_int(request.form.get('mileage')) or 0,
            request.form.get('fuel_type'),
            request.form.get('country'),
            request.form.get('image_url') or '',
            request.form.get('description') or ''
        )
    )

    connection.commit()
    connection.close()

    flash('Автомобиль добавлен в каталог.', 'success')
    return redirect(url_for('index'))


@app.route('/lead', methods=['POST'])
@login_required
def create_lead():
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip()
    preferred_brand = request.form.get('preferred_brand', '').strip()
    preferred_model = request.form.get('preferred_model', '').strip()
    budget = request.form.get('budget')
    country = request.form.get('preferred_country')
    comment = request.form.get('comment', '').strip()
    car_id = request.form.get('car_id')

    if not name or not phone:
        flash('Имя и телефон обязательны для заявки.', 'error')
        return redirect(url_for('index') + '#request')

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO leads (name, phone, email, car_id, preferred_brand, preferred_model, country, budget, comment, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            phone,
            email,
            safe_int(car_id),
            preferred_brand,
            preferred_model,
            country,
            safe_int(budget),
            comment,
            get_current_user()['id']
        )
    )

    connection.commit()
    connection.close()

    flash('Заявка успешно отправлена! Мы свяжемся с вами в ближайшее время.', 'success')
    return redirect(url_for('index'))


@app.route('/leads')
@role_required('admin')
def leads_list():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT leads.*, cars.brand AS car_brand, cars.model AS car_model,
               users.name AS user_name, users.email AS user_email, users.role AS user_role
        FROM leads
        LEFT JOIN cars ON cars.id = leads.car_id
        LEFT JOIN users ON users.id = leads.user_id
        ORDER BY leads.created_at DESC
        """
    )
    leads = cursor.fetchall()

    connection.close()

    return render_template('leads.html', leads=leads)


@app.route('/tracking')
def tracking_overview():
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT tracking_events.*, cars.brand, cars.model, cars.country
        FROM tracking_events
        JOIN cars ON cars.id = tracking_events.car_id
        ORDER BY tracking_events.updated_at DESC
        """
    )
    events = cursor.fetchall()
    connection.close()
    return render_template('tracking.html', events=events)


@app.route('/tracking/manage', methods=['GET', 'POST'])
@role_required('admin', 'moderator')
def manage_tracking():
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        car_id = safe_int(request.form.get('car_id'))
        status = request.form.get('status', '').strip()
        location = request.form.get('location', '').strip()
        eta = request.form.get('eta', '').strip()
        comment = request.form.get('comment', '').strip()

        if not car_id or not status or not location:
            flash('Выберите автомобиль, статус и местоположение.', 'error')
        else:
            cursor.execute(
                """
                INSERT INTO tracking_events (car_id, status, location, eta, comment)
                VALUES (?, ?, ?, ?, ?)
                """,
                (car_id, status, location, eta, comment)
            )
            connection.commit()
            flash('Статус автомобиля обновлён.', 'success')

        return redirect(url_for('manage_tracking'))

    cursor.execute("SELECT id, brand, model, year FROM cars ORDER BY brand")
    cars = cursor.fetchall()

    cursor.execute(
        """
        SELECT tracking_events.*, cars.brand, cars.model
        FROM tracking_events
        JOIN cars ON cars.id = tracking_events.car_id
        ORDER BY tracking_events.updated_at DESC
        LIMIT 20
        """
    )
    events = cursor.fetchall()

    connection.close()
    return render_template('tracking_manage.html', cars=cars, events=events)


@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    if get_current_user():
        return redirect(url_for('index'))

    next_url = request.args.get('next') or request.form.get('next') or url_for('index')

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()
        password_confirm = request.form.get('password_confirm', '').strip()

        if not all([name, email, password, password_confirm]):
            flash('Заполните все обязательные поля.', 'error')
            return redirect(url_for('register', next=next_url))

        if password != password_confirm:
            flash('Пароли не совпадают.', 'error')
            return redirect(url_for('register', next=next_url))

        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            connection.close()
            flash('Этот email уже зарегистрирован.', 'error')
            return redirect(url_for('register', next=next_url))

        cursor.execute(
            "INSERT INTO users (name, email, phone, password_hash) VALUES (?, ?, ?, ?)",
            (name, email, phone, generate_password_hash(password))
        )
        connection.commit()
        user_id = cursor.lastrowid
        connection.close()

        session['user_id'] = user_id
        flash('Регистрация прошла успешно!', 'success')
        return redirect(next_url)

    return render_template('auth_register.html', next_url=next_url)


@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if get_current_user():
        return redirect(url_for('index'))

    next_url = request.args.get('next') or request.form.get('next') or url_for('index')

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        connection.close()

        if not user or not check_password_hash(user['password_hash'], password):
            flash('Неверный email или пароль.', 'error')
            return redirect(url_for('login', next=next_url))

        session['user_id'] = user['id']
        flash('С возвращением!', 'success')
        return redirect(next_url)

    return render_template('auth_login.html', next_url=next_url)


@app.route('/auth/logout')
def logout():
    session.pop('user_id', None)
    flash('Вы вышли из личного кабинета.', 'success')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001)