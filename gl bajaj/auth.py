import functools
import secrets
import re
from flask import session, redirect, url_for, flash, request, abort, g
from database import get_db

def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def validate_csrf():
    """Verify CSRF token from form or header on state-changing requests."""
    token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
    expected_token = session.get('csrf_token')
    if not expected_token or not token or not secrets.compare_digest(token, expected_token):
        abort(400, description="Invalid or missing CSRF token. Please refresh and try again.")

def get_current_user():
    """Load logged-in user from database if session exists."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
    if not user:
        # User might have been deactivated or deleted
        session.clear()
        return None
    return dict(user)

def get_current_worker():
    """If logged in as a worker, fetch worker profile."""
    user = get_current_user()
    if not user or user.get('role') != 'worker':
        return None
    db = get_db()
    worker = db.execute("SELECT * FROM workers WHERE user_id = ?", (user['id'],)).fetchone()
    return dict(worker) if worker else None

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login', next=request.url))
        return view(**kwargs)
    return wrapped_view

def role_required(*allowed_roles):
    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            if 'user_id' not in session:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('login', next=request.url))
            role = session.get('user_role')
            if role not in allowed_roles:
                flash("You do not have permission to view that resource.", "error")
                abort(403)
            return view(**kwargs)
        return wrapped_view
    return decorator

def customer_required(view):
    return role_required('customer')(view)

def worker_required(view):
    return role_required('worker')(view)

def admin_required(view):
    return role_required('admin')(view)

def validate_email_format(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))

