import sqlite3
import os
from flask import g, current_app
from werkzeug.security import generate_password_hash

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('customer', 'worker', 'admin')),
    phone TEXT,
    city TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    bio TEXT,
    experience_years INTEGER DEFAULT 2,
    starting_price REAL DEFAULT 300.0,
    service_area TEXT,
    available INTEGER DEFAULT 1 CHECK(available IN (0, 1)),
    verification_status TEXT DEFAULT 'pending' CHECK(verification_status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    icon TEXT NOT NULL,
    description TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_ref TEXT UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES users(id),
    worker_id INTEGER NOT NULL REFERENCES workers(id),
    service TEXT NOT NULL,
    service_date TEXT NOT NULL,
    service_time TEXT NOT NULL,
    address TEXT NOT NULL,
    description TEXT NOT NULL,
    initial_offer REAL NOT NULL,
    current_offer REAL NOT NULL,
    agreed_price REAL DEFAULT NULL,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'countered', 'confirmed', 'in_progress', 'completed', 'cancelled', 'rejected')),
    cancelled_by INTEGER REFERENCES users(id),
    cancel_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    amount REAL NOT NULL,
    note TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected', 'superseded')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    doc_number TEXT NOT NULL,
    file_path TEXT,
    note TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
    admin_note TEXT,
    reviewed_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER UNIQUE NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES users(id),
    worker_id INTEGER NOT NULL REFERENCES workers(id),
    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    comment TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link TEXT,
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS support_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    status TEXT DEFAULT 'open' CHECK(status IN ('open', 'in_progress', 'resolved', 'closed')),
    admin_notes TEXT,
    resolved_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workers_user_id ON workers(user_id);
CREATE INDEX IF NOT EXISTS idx_workers_category ON workers(category);
CREATE INDEX IF NOT EXISTS idx_workers_status ON workers(verification_status, available);
CREATE INDEX IF NOT EXISTS idx_bookings_customer ON bookings(customer_id);
CREATE INDEX IF NOT EXISTS idx_bookings_worker ON bookings(worker_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_offers_booking ON offers(booking_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_support_status ON support_messages(status);
"""

def get_db():
    if 'db' not in g:
        db_path = current_app.config['DATABASE']
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db(app=None):
    if app:
        with app.app_context():
            db = get_db()
            db.executescript(SCHEMA_SQL)
            db.commit()
    else:
        db = get_db()
        db.executescript(SCHEMA_SQL)
        db.commit()

def seed_db(app=None):
    """Seed default categories, administrator, and sample workers/customers if not present."""
    context_manager = app.app_context() if app else None
    if context_manager:
        context_manager.__enter__()

    try:
        db = get_db()
        
        # 1. Seed Categories
        categories_data = [
            ("Electrical Services", "electrical", "zap", "Wiring, switchboard repair, appliance installation, and safety checks"),
            ("Plumbing", "plumbing", "droplet", "Pipe leakages, bathroom fittings, tap repairs, water tank installation"),
            ("Carpentry", "carpentry", "hammer", "Furniture repair, custom woodwork, door fixing, and cabinet assembly"),
            ("Painting", "painting", "paint-brush", "Interior and exterior wall painting, touch-ups, waterproof coating"),
            ("AC Repair", "ac-repair", "wind", "AC servicing, gas charging, filter cleanup, compressor maintenance"),
            ("Appliance Repair", "appliance-repair", "wrench", "Washing machines, refrigerators, microwaves, and geysers"),
            ("Cleaning", "cleaning", "sparkles", "Deep home cleaning, kitchen scrubbing, bathroom sanitization"),
            ("Other Services", "other-services", "wrench", "General handywork, masonry, welding, and local assistance")
        ]
        
        for name, slug, icon, desc in categories_data:
            db.execute("""
                INSERT OR IGNORE INTO categories (name, slug, icon, description, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (name, slug, icon, desc))

        # 2. Seed Admin User
        admin_email = "admin@kaamnearby.com"
        admin = db.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
        if not admin:
            db.execute("""
                INSERT INTO users (name, email, password_hash, role, phone, city, is_active)
                VALUES (?, ?, ?, 'admin', '9876543210', 'Noida', 1)
            """, ("System Administrator", admin_email, generate_password_hash("Admin@12345")))
            admin_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            admin_id = admin['id']

        # 3. Seed Sample Customer
        customer_email = "rahul.customer@example.com"
        customer = db.execute("SELECT id FROM users WHERE email = ?", (customer_email,)).fetchone()
        if not customer:
            db.execute("""
                INSERT INTO users (name, email, password_hash, role, phone, city, is_active)
                VALUES (?, ?, ?, 'customer', '9811122233', 'Greater Noida', 1)
            """, ("Rahul Verma", customer_email, generate_password_hash("Customer@12345")))
            customer_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            customer_id = customer['id']

        # 4. Seed Sample Workers
        sample_workers = [
            {
                "name": "Suresh Kumar Sharma",
                "email": "suresh.electrician@example.com",
                "phone": "9812345671",
                "city": "Greater Noida",
                "category": "Electrical Services",
                "bio": "Certified electrician with 8+ years of residential and commercial wiring, MCB troubleshooting, and inverter setup experience.",
                "experience": 8,
                "price": 350.0,
                "area": "Alpha 1, Pari Chowk, Knowledge Park, Beta 2",
                "available": 1,
                "status": "approved",
                "doc_type": "Aadhaar Card",
                "doc_number": "XXXX-XXXX-4891"
            },
            {
                "name": "Manoj Mistri",
                "email": "manoj.plumber@example.com",
                "phone": "9812345672",
                "city": "Noida",
                "category": "Plumbing",
                "bio": "Specialist in concealed pipe repairs, sanitary installations, water tank cleanouts, and high-pressure pumps with 6 years experience.",
                "experience": 6,
                "price": 400.0,
                "area": "Sector 62, Sector 18, Sector 50, Sector 137",
                "available": 1,
                "status": "approved",
                "doc_type": "Aadhaar Card",
                "doc_number": "XXXX-XXXX-1029"
            },
            {
                "name": "Ramesh Carpenter",
                "email": "ramesh.carpenter@example.com",
                "phone": "9812345673",
                "city": "Greater Noida",
                "category": "Carpentry",
                "bio": "Skilled woodwork master for modular kitchen fittings, door alignment, wardrobe locks, and custom furniture restoration.",
                "experience": 10,
                "price": 450.0,
                "area": "Delta 1, Gamma 2, Surajpur, Greater Noida West",
                "available": 1,
                "status": "approved",
                "doc_type": "PAN Card",
                "doc_number": "ABCDE1234F"
            },
            {
                "name": "Amit Technicals (AC)",
                "email": "amit.ac@example.com",
                "phone": "9812345674",
                "city": "Delhi NCR",
                "category": "AC Repair",
                "bio": "HVAC certified AC technician. Split and window AC jet cleaning, R32/R410 gas refill, and PCB board circuit repairs.",
                "experience": 5,
                "price": 499.0,
                "area": "Noida, Greater Noida, Ghaziabad",
                "available": 1,
                "status": "approved",
                "doc_type": "Trade Certificate",
                "doc_number": "ITI-HVAC-2019-88"
            },
            {
                "name": "Vikram Singh Painter",
                "email": "vikram.painter@example.com",
                "phone": "9812345675",
                "city": "Greater Noida",
                "category": "Painting",
                "bio": "Expert in Asian Paints royal finish, wall putty priming, damp-proof waterproofing, and texture designs.",
                "experience": 7,
                "price": 600.0,
                "area": "Pari Chowk, Knowledge Park III, Chi 1",
                "available": 1,
                "status": "approved",
                "doc_type": "Voter ID",
                "doc_number": "UP/09/2049182"
            },
            {
                "name": "Dinesh Appliance Care",
                "email": "dinesh.repair@example.com",
                "phone": "9812345676",
                "city": "Noida",
                "category": "Appliance Repair",
                "bio": "Repair specialist for fully automatic washing machines, microwave ovens, double-door refrigerators and RO water purifiers.",
                "experience": 4,
                "price": 350.0,
                "area": "Sector 15, Sector 16, Sector 27",
                "available": 1,
                "status": "pending",  # Pending worker to test verification approval workflow!
                "doc_type": "Aadhaar Card",
                "doc_number": "XXXX-XXXX-9921"
            }
        ]

        for w in sample_workers:
            existing = db.execute("SELECT id FROM users WHERE email = ?", (w['email'],)).fetchone()
            if not existing:
                db.execute("""
                    INSERT INTO users (name, email, password_hash, role, phone, city, is_active)
                    VALUES (?, ?, ?, 'worker', ?, ?, 1)
                """, (w['name'], w['email'], generate_password_hash("Worker@12345"), w['phone'], w['city']))
                user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                db.execute("""
                    INSERT INTO workers (user_id, category, bio, experience_years, starting_price, service_area, available, verification_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, w['category'], w['bio'], w['experience'], w['price'], w['area'], w['available'], w['status']))
                worker_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                # Add verification record
                db.execute("""
                    INSERT INTO verifications (worker_id, doc_type, doc_number, note, status, admin_note)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    worker_id, 
                    w['doc_type'], 
                    w['doc_number'], 
                    "Official government identity card verification uploaded.",
                    w['status'],
                    "Identity proof and trade background reviewed." if w['status'] == 'approved' else None
                ))

        # 5. Seed a sample completed booking + review to show real ratings
        suresh_worker = db.execute("""
            SELECT w.id FROM workers w 
            JOIN users u ON w.user_id = u.id 
            WHERE u.email = 'suresh.electrician@example.com'
        """).fetchone()

        if suresh_worker and customer_id:
            suresh_id = suresh_worker['id']
            existing_booking = db.execute("SELECT id FROM bookings WHERE booking_ref = 'KB-202610-001'").fetchone()
            if not existing_booking:
                db.execute("""
                    INSERT INTO bookings (
                        booking_ref, customer_id, worker_id, service, service_date, service_time,
                        address, description, initial_offer, current_offer, agreed_price, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    'KB-202610-001', customer_id, suresh_id, 'Electrical Services',
                    '2026-10-25', '11:00 AM', 'Flat 402, Tower B, Knowledge Park, Greater Noida',
                    'Main circuit breaker tripped and bedroom light fitting needs replacement.',
                    400.0, 450.0, 450.0, 'completed'
                ))
                b_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                # Add sample offers history
                suresh_user = db.execute("SELECT user_id FROM workers WHERE id = ?", (suresh_id,)).fetchone()
                db.execute("""
                    INSERT INTO offers (booking_id, sender_id, amount, note, status)
                    VALUES (?, ?, 400.0, 'Initial offer for breaker check and switch replacement.', 'superseded')
                """, (b_id, customer_id))
                
                db.execute("""
                    INSERT INTO offers (booking_id, sender_id, amount, note, status)
                    VALUES (?, ?, 450.0, 'Will replace breaker and install heavy-duty switches with safety insulation.', 'accepted')
                """, (b_id, suresh_user['user_id']))

                # Add review
                db.execute("""
                    INSERT INTO reviews (booking_id, customer_id, worker_id, rating, comment)
                    VALUES (?, ?, ?, 5, 'Suresh arrived right on time with all tools. Fixed the MCB tripping issue quickly and tested every switch safely. Highly recommended!')
                """, (b_id, customer_id, suresh_id))

        db.commit()
    finally:
        if context_manager:
            context_manager.__exit__(None, None, None)
