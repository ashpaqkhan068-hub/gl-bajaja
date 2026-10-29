import os
import random
import time
from werkzeug.utils import secure_filename
from flask import request
from database import get_db

def create_notification(user_id, title, message, link=None):
    """Insert persistent in-app notification."""
    try:
        db = get_db()
        db.execute("""
            INSERT INTO notifications (user_id, title, message, link, is_read)
            VALUES (?, ?, ?, ?, 0)
        """, (user_id, title, message, link))
        db.commit()
    except Exception as e:
        print(f"Error creating notification: {e}")

def notify_all_admins(title, message, link=None):
    """Deliver a persistent in-app notification to all active administrators."""
    try:
        db = get_db()
        admins = db.execute("SELECT id FROM users WHERE role = 'admin' AND is_active = 1").fetchall()
        for a in admins:
            db.execute("""
                INSERT INTO notifications (user_id, title, message, link, is_read)
                VALUES (?, ?, ?, ?, 0)
            """, (a['id'], title, message, link))
        db.commit()
    except Exception as e:
        print(f"Error notifying admins: {e}")

def log_audit(user_id, action, details=None):
    """Record an audit trail event."""
    try:
        db = get_db()
        ip_addr = request.remote_addr if request else '127.0.0.1'
        db.execute("""
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (?, ?, ?, ?)
        """, (user_id, action, details, ip_addr))
        db.commit()
    except Exception as e:
        print(f"Error creating audit log: {e}")

def generate_booking_ref():
    """Generate unique readable booking reference, e.g. KB-20261029-4821."""
    date_part = time.strftime("%Y%m%d")
    random_part = f"{random.randint(1000, 9999)}"
    return f"KB-{date_part}-{random_part}"

def get_worker_rating_stats(worker_id):
    """Calculate real average rating and count of reviews for a worker."""
    db = get_db()
    row = db.execute("""
        SELECT COUNT(id) as total_reviews, COALESCE(AVG(rating), 0) as avg_rating
        FROM reviews
        WHERE worker_id = ?
    """, (worker_id,)).fetchone()
    
    total = row['total_reviews'] if row else 0
    avg = round(row['avg_rating'], 1) if row and row['avg_rating'] else 0.0
    return {
        'total_reviews': total,
        'avg_rating': avg,
        'has_reviews': total > 0
    }

def get_worker_full_info(worker_id):
    """Retrieve combined worker and user data with computed ratings."""
    db = get_db()
    worker = db.execute("""
        SELECT w.*, u.name, u.email, u.phone, u.city, u.is_active
        FROM workers w
        JOIN users u ON w.user_id = u.id
        WHERE w.id = ?
    """, (worker_id,)).fetchone()
    
    if not worker:
        return None
        
    worker_data = dict(worker)
    stats = get_worker_rating_stats(worker_id)
    worker_data['total_reviews'] = stats['total_reviews']
    worker_data['avg_rating'] = stats['avg_rating']
    worker_data['has_reviews'] = stats['has_reviews']
    return worker_data

def save_uploaded_doc(file, worker_id, upload_folder, allowed_extensions):
    """Securely save uploaded verification document."""
    if not file or file.filename == '':
        return None, "No file selected."
    
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return None, "File must have an extension."
    
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in allowed_extensions:
        return None, f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
    
    os.makedirs(upload_folder, exist_ok=True)
    new_filename = f"worker_{worker_id}_{int(time.time())}_{random.randint(100, 999)}.{ext}"
    destination = os.path.join(upload_folder, new_filename)
    file.save(destination)
    return new_filename, None

