import os
import math
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, abort, send_from_directory, jsonify, current_app
)
from werkzeug.security import generate_password_hash, check_password_hash

import config
from database import get_db, close_db, init_db, seed_db
from auth import (
    generate_csrf_token, validate_csrf, get_current_user, get_current_worker,
    login_required, customer_required, worker_required, admin_required,
    validate_email_format
)
from helpers import (
    create_notification, log_audit, generate_booking_ref,
    get_worker_rating_stats, get_worker_full_info, save_uploaded_doc,
    notify_all_admins
)

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    if test_config is None:
        app.config.from_object(config.DevelopmentConfig)
    else:
        app.config.from_object(test_config)

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(app.config['DATABASE'])), exist_ok=True)

    app.teardown_appcontext(close_db)

    # -------------------------------------------------------------
    # Template Filters & Context Processors
    # -------------------------------------------------------------
    @app.template_filter('currency')
    def currency_filter(amount):
        if amount is None:
            return "₹0"
        try:
            val = float(amount)
            if val.is_integer():
                return f"₹{int(val):,}"
            return f"₹{val:,.2f}"
        except (ValueError, TypeError):
            return "₹0"

    @app.template_filter('format_date')
    def format_date_filter(val):
        if not val:
            return ""
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.strftime("%d %b %Y, %I:%M %p")
            except Exception:
                return val
        if isinstance(val, datetime):
            return val.strftime("%d %b %Y, %I:%M %p")
        return str(val)

    @app.context_processor
    def inject_global_data():
        user = get_current_user()
        worker = get_current_worker() if user and user['role'] == 'worker' else None
        
        unread_count = 0
        open_support_count = 0
        categories_list = []
        if user:
            db = get_db()
            row = db.execute("SELECT COUNT(id) as count FROM notifications WHERE user_id = ? AND is_read = 0", (user['id'],)).fetchone()
            if row:
                unread_count = row['count']
            
            if user.get('role') == 'admin':
                try:
                    s_row = db.execute("SELECT COUNT(id) as count FROM support_messages WHERE status = 'open'").fetchone()
                    if s_row:
                        open_support_count = s_row['count']
                except Exception:
                    pass
        
        try:
            db = get_db()
            categories_list = db.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY name ASC").fetchall()
        except Exception:
            pass

        return {
            'current_user': user,
            'current_worker': worker,
            'csrf_token': generate_csrf_token(),
            'unread_notifications_count': unread_count,
            'open_support_count': open_support_count,
            'nav_categories': categories_list,
            'now_year': datetime.now().year
        }

    # -------------------------------------------------------------
    # Public Routes
    # -------------------------------------------------------------
    @app.route('/')
    def index():
        db = get_db()
        # Fetch active categories
        categories = db.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY id ASC").fetchall()
        
        # Fetch featured approved and available workers
        featured_workers_raw = db.execute("""
            SELECT w.*, u.name, u.city 
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE w.verification_status = 'approved' AND w.available = 1 AND u.is_active = 1
            ORDER BY w.id DESC LIMIT 6
        """).fetchall()

        featured_workers = []
        for fw in featured_workers_raw:
            data = dict(fw)
            stats = get_worker_rating_stats(fw['id'])
            data['avg_rating'] = stats['avg_rating']
            data['total_reviews'] = stats['total_reviews']
            featured_workers.append(data)

        # Platform count stats
        worker_count = db.execute("SELECT COUNT(id) FROM workers WHERE verification_status = 'approved'").fetchone()[0]
        completed_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE status = 'completed'").fetchone()[0]

        return render_template(
            'index.html',
            categories=categories,
            featured_workers=featured_workers,
            worker_count=worker_count,
            completed_bookings=completed_bookings
        )

    @app.route('/services')
    def services():
        category_slug = request.args.get('category', '').strip()
        search_query = request.args.get('q', '').strip()
        city_query = request.args.get('city', '').strip()
        min_price = request.args.get('min_price', '').strip()
        max_price = request.args.get('max_price', '').strip()
        available_only = request.args.get('available', '')
        sort_by = request.args.get('sort', 'rating_desc')
        page = max(1, int(request.args.get('page', 1)))
        per_page = current_app.config.get('ITEMS_PER_PAGE', 8)

        db = get_db()
        categories = db.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY name ASC").fetchall()
        
        # Resolve category name if slug provided
        selected_cat_name = ""
        if category_slug:
            cat_row = db.execute("SELECT name FROM categories WHERE slug = ? OR name = ?", (category_slug, category_slug)).fetchone()
            if cat_row:
                selected_cat_name = cat_row['name']
            else:
                selected_cat_name = category_slug

        # Build query dynamically
        conditions = ["w.verification_status = 'approved'", "u.is_active = 1"]
        params = []

        if selected_cat_name:
            conditions.append("w.category = ?")
            params.append(selected_cat_name)

        if search_query:
            conditions.append("(u.name LIKE ? OR w.bio LIKE ? OR w.service_area LIKE ? OR w.category LIKE ?)")
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        if city_query:
            conditions.append("(u.city LIKE ? OR w.service_area LIKE ?)")
            wildcard = f"%{city_query}%"
            params.extend([wildcard, wildcard])

        if min_price:
            try:
                min_val = float(min_price)
                conditions.append("w.starting_price >= ?")
                params.append(min_val)
            except ValueError:
                pass

        if max_price:
            try:
                max_val = float(max_price)
                conditions.append("w.starting_price <= ?")
                params.append(max_val)
            except ValueError:
                pass

        if available_only == '1':
            conditions.append("w.available = 1")

        where_clause = " AND ".join(conditions)

        count_query = f"""
            SELECT COUNT(w.id) FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE {where_clause}
        """
        total_workers = db.execute(count_query, params).fetchone()[0]
        total_pages = max(1, math.ceil(total_workers / per_page))

        # Query workers
        query = f"""
            SELECT w.*, u.name, u.email, u.phone, u.city
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE {where_clause}
        """

        # Fetch workers and enrich with real rating stats
        raw_workers = db.execute(query, params).fetchall()
        enriched_workers = []
        for rw in raw_workers:
            data = dict(rw)
            stats = get_worker_rating_stats(rw['id'])
            data['avg_rating'] = stats['avg_rating']
            data['total_reviews'] = stats['total_reviews']
            enriched_workers.append(data)

        # Sort in Python to support rating-based sorting smoothly
        if sort_by == 'price_asc':
            enriched_workers.sort(key=lambda x: x['starting_price'])
        elif sort_by == 'price_desc':
            enriched_workers.sort(key=lambda x: x['starting_price'], reverse=True)
        elif sort_by == 'experience_desc':
            enriched_workers.sort(key=lambda x: x['experience_years'], reverse=True)
        elif sort_by == 'name_asc':
            enriched_workers.sort(key=lambda x: x['name'].lower())
        else: # rating_desc default
            enriched_workers.sort(key=lambda x: (x['avg_rating'], x['total_reviews']), reverse=True)

        # Slice for current page
        offset = (page - 1) * per_page
        paginated_workers = enriched_workers[offset:offset + per_page]

        return render_template(
            'services.html',
            workers=paginated_workers,
            categories=categories,
            selected_category=selected_cat_name,
            category_slug=category_slug,
            search_query=search_query,
            city_query=city_query,
            min_price=min_price,
            max_price=max_price,
            available_only=available_only,
            sort_by=sort_by,
            page=page,
            total_pages=total_pages,
            total_workers=total_workers
        )

    @app.route('/workers/<int:worker_id>')
    def worker_detail(worker_id):
        worker = get_worker_full_info(worker_id)
        if not worker:
            abort(404, description="Worker profile not found.")

        # If not approved and not admin/owner, don't show
        current_user = get_current_user()
        is_owner = current_user and current_user['id'] == worker['user_id']
        is_admin = current_user and current_user['role'] == 'admin'
        if worker['verification_status'] != 'approved' and not (is_owner or is_admin):
            flash("This worker profile is currently undergoing verification.", "info")
            return redirect(url_for('services'))

        db = get_db()
        # Fetch real reviews for this worker
        reviews = db.execute("""
            SELECT r.*, u.name as customer_name, b.service
            FROM reviews r
            JOIN users u ON r.customer_id = u.id
            JOIN bookings b ON r.booking_id = b.id
            WHERE r.worker_id = ?
            ORDER BY r.created_at DESC
        """, (worker_id,)).fetchall()

        return render_template('worker_detail.html', worker=worker, reviews=reviews)

    @app.route('/about')
    def about():
        return render_template('about.html')

    @app.route('/how-it-works')
    def how_it_works():
        return render_template('how_it_works.html')

    @app.route('/contact', methods=['GET', 'POST'])
    def contact():
        if request.method == 'POST':
            validate_csrf()
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            subject = request.form.get('subject', '').strip()
            message = request.form.get('message', '').strip()

            if not name or not email or not message:
                flash("Please complete all required fields.", "error")
                return render_template('contact.html')

            user = get_current_user()
            user_id = user['id'] if user else None

            db = get_db()
            db.execute("""
                INSERT INTO support_messages (user_id, name, email, subject, message, status)
                VALUES (?, ?, ?, ?, ?, 'open')
            """, (user_id, name, email, subject or "General Support Inquiry", message))
            msg_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.commit()

            # Broadcast persistent in-app notification to all administrators
            notify_all_admins(
                title=f"New Support Inquiry: {subject or 'Customer Message'}",
                message=f"From {name} ({email}): {message[:120]}{'...' if len(message) > 120 else ''}",
                link=f"/admin/support/{msg_id}"
            )

            log_audit(user_id, "SUPPORT_MESSAGE_SUBMITTED", f"From: {email}, ID: {msg_id}")

            flash("Thank you for contacting KaamNearby! Your message has been received and routed to our administrative team.", "success")
            return redirect(url_for('contact'))
        return render_template('contact.html')

    @app.route('/terms')
    def terms():
        return render_template('terms.html')

    @app.route('/privacy')
    def privacy():
        return render_template('privacy.html')

    # -------------------------------------------------------------
    # Authentication Routes
    # -------------------------------------------------------------
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if 'user_id' in session:
            return redirect_to_dashboard(session.get('user_role'))

        db = get_db()
        categories = db.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY name ASC").fetchall()

        if request.method == 'POST':
            validate_csrf()
            role = request.form.get('role', 'customer').strip().lower()
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            phone = request.form.get('phone', '').strip()
            city = request.form.get('city', '').strip()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            agree_terms = request.form.get('agree_terms')

            form_data = {
                'name': name, 'email': email, 'phone': phone, 'city': city, 'role': role,
                'category': request.form.get('category', ''),
                'bio': request.form.get('bio', ''),
                'starting_price': request.form.get('starting_price', ''),
                'experience_years': request.form.get('experience_years', '1'),
                'service_area': request.form.get('service_area', '')
            }

            if role not in ('customer', 'worker'):
                flash("Invalid account type selected.", "error")
                return render_template('register.html', categories=categories, form=form_data)

            if not agree_terms:
                flash("You must agree to the Terms of Service to register.", "error")
                return render_template('register.html', categories=categories, form=form_data)

            if not name or not email or not city or not password:
                flash("Please fill in all required fields.", "error")
                return render_template('register.html', categories=categories, form=form_data)

            if not validate_email_format(email):
                flash("Please enter a valid email address.", "error")
                return render_template('register.html', categories=categories, form=form_data)

            if len(password) < 8:
                flash("Password must be at least 8 characters long.", "error")
                return render_template('register.html', categories=categories, form=form_data)

            if password != confirm_password:
                flash("Passwords do not match.", "error")
                return render_template('register.html', categories=categories, form=form_data)

            # Check duplicate email
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                flash("An account with this email already exists. Please log in.", "error")
                return render_template('register.html', categories=categories, form=form_data)

            # Worker specific validation
            if role == 'worker':
                category = form_data['category'].strip()
                bio = form_data['bio'].strip()
                service_area = form_data['service_area'].strip() or city
                try:
                    starting_price = float(form_data['starting_price'] or 300)
                    if starting_price < 50:
                        flash("Starting price must be at least ₹50.", "error")
                        return render_template('register.html', categories=categories, form=form_data)
                except ValueError:
                    flash("Please enter a valid numeric starting price.", "error")
                    return render_template('register.html', categories=categories, form=form_data)

                try:
                    experience = int(form_data['experience_years'] or 1)
                except ValueError:
                    experience = 1

                if not category:
                    flash("Please select your primary service category.", "error")
                    return render_template('register.html', categories=categories, form=form_data)

            # Insert User
            pw_hash = generate_password_hash(password)
            try:
                db.execute("""
                    INSERT INTO users (name, email, password_hash, role, phone, city, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                """, (name, email, pw_hash, role, phone, city))
                user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                if role == 'worker':
                    db.execute("""
                        INSERT INTO workers (user_id, category, bio, experience_years, starting_price, service_area, available, verification_status)
                        VALUES (?, ?, ?, ?, ?, ?, 1, 'pending')
                    """, (user_id, category, bio, experience, starting_price, service_area))
                    worker_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                    # Create initial verification placeholder
                    db.execute("""
                        INSERT INTO verifications (worker_id, doc_type, doc_number, note, status)
                        VALUES (?, 'Pending Submission', 'Awaiting document upload', 'Registration completed. Verification documents required.', 'pending')
                    """, (worker_id,))

                    create_notification(
                        user_id,
                        "Welcome to KaamNearby!",
                        "Your worker account is created. Please submit identity verification documents to begin receiving booking requests.",
                        "/worker/verification"
                    )
                else:
                    create_notification(
                        user_id,
                        "Welcome to KaamNearby!",
                        "Your account has been registered successfully. Explore verified local services and find trusted professionals today.",
                        "/services"
                    )

                db.commit()
                log_audit(user_id, "USER_REGISTERED", f"Role: {role}, Email: {email}")

                # Establish session
                session.clear()
                session['user_id'] = user_id
                session['user_name'] = name
                session['user_email'] = email
                session['user_role'] = role
                generate_csrf_token()

                flash("Welcome to KaamNearby! Your account has been registered.", "success")
                return redirect_to_dashboard(role)

            except Exception as e:
                db.rollback()
                flash("An unexpected error occurred during registration. Please try again.", "error")
                return render_template('register.html', categories=categories, form=form_data)

        return render_template('register.html', categories=categories, form={})

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if 'user_id' in session:
            return redirect_to_dashboard(session.get('user_role'))

        if request.method == 'POST':
            validate_csrf()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            next_url = request.args.get('next') or request.form.get('next')

            if not email or not password:
                flash("Please enter both email and password.", "error")
                return render_template('login.html', email=email)

            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if not user or not check_password_hash(user['password_hash'], password):
                flash("Invalid email or password. Please verify your credentials.", "error")
                return render_template('login.html', email=email)

            if not user['is_active']:
                flash("This account has been deactivated. Please contact support.", "error")
                return render_template('login.html', email=email)

            # Establish session securely
            session.clear()
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['user_role'] = user['role']
            generate_csrf_token()

            log_audit(user['id'], "USER_LOGIN", f"Logged in from {request.remote_addr}")
            flash(f"Welcome back, {user['name']}!", "success")

            # Validate next_url to prevent open redirects
            if next_url and next_url.startswith('/'):
                return redirect(next_url)

            return redirect_to_dashboard(user['role'])

        return render_template('login.html')

    @app.route('/logout', methods=['GET', 'POST'])
    def logout():
        user_id = session.get('user_id')
        if user_id:
            log_audit(user_id, "USER_LOGOUT")
        session.clear()
        flash("You have been signed out safely.", "info")
        return redirect(url_for('index'))

    def redirect_to_dashboard(role):
        if role == 'customer':
            return redirect(url_for('customer_dashboard'))
        elif role == 'worker':
            return redirect(url_for('worker_dashboard'))
        elif role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('index'))

    # -------------------------------------------------------------
    # Notification Routes
    # -------------------------------------------------------------
    @app.route('/notifications')
    @login_required
    def notifications():
        user = get_current_user()
        db = get_db()
        notifs = db.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? 
            ORDER BY created_at DESC LIMIT 50
        """, (user['id'],)).fetchall()
        return render_template('notifications.html', notifications=notifs)

    @app.route('/notifications/<int:notif_id>/read')
    @login_required
    def notification_mark_read(notif_id):
        user = get_current_user()
        db = get_db()
        notif = db.execute("SELECT * FROM notifications WHERE id = ? AND user_id = ?", (notif_id, user['id'])).fetchone()
        if notif:
            db.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notif_id,))
            db.commit()
            if notif['link']:
                return redirect(notif['link'])
        return redirect(url_for('notifications'))

    @app.route('/notifications/mark-all-read', methods=['POST'])
    @login_required
    def notifications_mark_all_read():
        validate_csrf()
        user = get_current_user()
        db = get_db()
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user['id'],))
        db.commit()
        flash("All notifications marked as read.", "success")
        return redirect(url_for('notifications'))

    # -------------------------------------------------------------
    # Customer Routes
    # -------------------------------------------------------------
    @app.route('/customer/dashboard')
    @customer_required
    def customer_dashboard():
        user = get_current_user()
        db = get_db()

        # Customer Statistics
        total_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE customer_id = ?", (user['id'],)).fetchone()[0]
        pending_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE customer_id = ? AND status IN ('pending', 'countered')", (user['id'],)).fetchone()[0]
        confirmed_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE customer_id = ? AND status IN ('confirmed', 'in_progress')", (user['id'],)).fetchone()[0]
        completed_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE customer_id = ? AND status = 'completed'", (user['id'],)).fetchone()[0]

        # Recent Bookings
        recent_bookings = db.execute("""
            SELECT b.*, w.category, u.name as worker_name, u.phone as worker_phone
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            JOIN users u ON w.user_id = u.id
            WHERE b.customer_id = ?
            ORDER BY b.updated_at DESC LIMIT 5
        """, (user['id'],)).fetchall()

        return render_template(
            'customer/dashboard.html',
            total_bookings=total_bookings,
            pending_bookings=pending_bookings,
            confirmed_bookings=confirmed_bookings,
            completed_bookings=completed_bookings,
            recent_bookings=recent_bookings
        )

    @app.route('/customer/bookings')
    @customer_required
    def customer_bookings():
        user = get_current_user()
        status_filter = request.args.get('status', 'all').strip()

        db = get_db()
        conditions = ["b.customer_id = ?"]
        params = [user['id']]

        if status_filter != 'all':
            if status_filter == 'active':
                conditions.append("b.status IN ('pending', 'countered', 'confirmed', 'in_progress')")
            else:
                conditions.append("b.status = ?")
                params.append(status_filter)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT b.*, w.category, u.name as worker_name, u.city as worker_city, u.phone as worker_phone
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            JOIN users u ON w.user_id = u.id
            WHERE {where_clause}
            ORDER BY b.updated_at DESC
        """
        bookings = db.execute(query, params).fetchall()

        return render_template('customer/bookings.html', bookings=bookings, current_status=status_filter)

    @app.route('/customer/book/<int:worker_id>', methods=['POST'])
    @customer_required
    def customer_create_booking(worker_id):
        validate_csrf()
        user = get_current_user()
        db = get_db()

        # Validate worker
        worker = get_worker_full_info(worker_id)
        if not worker:
            abort(404, description="Worker not found.")

        if worker['user_id'] == user['id']:
            flash("You cannot book your own worker profile.", "error")
            return redirect(url_for('worker_detail', worker_id=worker_id))

        if worker['verification_status'] != 'approved':
            flash("This worker has not yet completed official verification.", "error")
            return redirect(url_for('worker_detail', worker_id=worker_id))

        if not worker['available']:
            flash("This worker is currently not accepting new booking requests.", "warning")
            return redirect(url_for('worker_detail', worker_id=worker_id))

        service = request.form.get('service', '').strip() or worker['category']
        service_date = request.form.get('service_date', '').strip()
        service_time = request.form.get('service_time', '').strip()
        address = request.form.get('address', '').strip()
        description = request.form.get('description', '').strip()
        offer_str = request.form.get('initial_offer', '').strip()

        if not service_date or not service_time or not address or not description or not offer_str:
            flash("Please fill in all booking details and your initial price offer.", "error")
            return redirect(url_for('worker_detail', worker_id=worker_id))

        try:
            initial_offer = float(offer_str)
            if initial_offer <= 0:
                flash("Please offer a valid positive amount in Indian Rupees.", "error")
                return redirect(url_for('worker_detail', worker_id=worker_id))
        except ValueError:
            flash("Invalid price offer amount entered.", "error")
            return redirect(url_for('worker_detail', worker_id=worker_id))

        booking_ref = generate_booking_ref()

        try:
            db.execute("""
                INSERT INTO bookings (
                    booking_ref, customer_id, worker_id, service, service_date, service_time,
                    address, description, initial_offer, current_offer, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (
                booking_ref, user['id'], worker_id, service, service_date, service_time,
                address, description, initial_offer, initial_offer
            ))
            booking_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert initial offer record
            db.execute("""
                INSERT INTO offers (booking_id, sender_id, amount, note, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (booking_id, user['id'], initial_offer, f"Initial service request offer for {service}."))

            # Notify worker
            create_notification(
                worker['user_id'],
                "New Booking Request Received!",
                f"{user['name']} requested {service} for ₹{initial_offer:,.0f} on {service_date}.",
                f"/worker/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "BOOKING_CREATED", f"Booking ID: {booking_id}, Worker ID: {worker_id}, Offer: {initial_offer}")
            flash(f"Booking request {booking_ref} submitted successfully! The worker has been notified.", "success")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        except Exception as e:
            db.rollback()
            flash("Failed to submit booking request. Please try again.", "error")
            return redirect(url_for('worker_detail', worker_id=worker_id))

    @app.route('/customer/bookings/<int:booking_id>')
    @customer_required
    def customer_booking_detail(booking_id):
        user = get_current_user()
        db = get_db()

        booking = db.execute("""
            SELECT b.*, w.category, w.starting_price, w.user_id as worker_user_id,
                   u.name as worker_name, u.phone as worker_phone, u.email as worker_email, u.city as worker_city
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            JOIN users u ON w.user_id = u.id
            WHERE b.id = ? AND b.customer_id = ?
        """, (booking_id, user['id'])).fetchone()

        if not booking:
            abort(404, description="Booking not found or access denied.")

        offers = db.execute("""
            SELECT o.*, u.name as sender_name, u.role as sender_role
            FROM offers o
            JOIN users u ON o.sender_id = u.id
            WHERE o.booking_id = ?
            ORDER BY o.created_at ASC, o.id ASC
        """, (booking_id,)).fetchall()

        latest_offer = offers[-1] if offers else None

        # Check if reviewed
        review = db.execute("SELECT * FROM reviews WHERE booking_id = ?", (booking_id,)).fetchone()

        return render_template(
            'customer/booking_detail.html',
            booking=booking,
            offers=offers,
            latest_offer=latest_offer,
            review=review
        )

    @app.route('/customer/bookings/<int:booking_id>/offer', methods=['POST'])
    @customer_required
    def customer_submit_offer(booking_id):
        validate_csrf()
        user = get_current_user()
        db = get_db()

        booking = db.execute("""
            SELECT b.*, w.user_id as worker_user_id
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            WHERE b.id = ? AND b.customer_id = ?
        """, (booking_id, user['id'])).fetchone()

        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] not in ('pending', 'countered'):
            flash("This booking is no longer in negotiation.", "error")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        latest_offer = db.execute("""
            SELECT * FROM offers WHERE booking_id = ? ORDER BY id DESC LIMIT 1
        """, (booking_id,)).fetchone()

        if latest_offer and latest_offer['sender_id'] == user['id']:
            flash("You already submitted the most recent offer. Please wait for the worker to respond.", "warning")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        amount_str = request.form.get('amount', '').strip()
        note = request.form.get('note', '').strip()

        try:
            amount = float(amount_str)
            if amount <= 0:
                flash("Offer must be a valid positive amount.", "error")
                return redirect(url_for('customer_booking_detail', booking_id=booking_id))
        except ValueError:
            flash("Invalid offer amount.", "error")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        try:
            # Supersede previous pending offers
            db.execute("UPDATE offers SET status = 'superseded' WHERE booking_id = ? AND status = 'pending'", (booking_id,))
            
            # Insert new counter offer
            db.execute("""
                INSERT INTO offers (booking_id, sender_id, amount, note, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (booking_id, user['id'], amount, note or "Customer counter-offer."))

            # Update booking state
            db.execute("""
                UPDATE bookings 
                SET current_offer = ?, status = 'countered', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (amount, booking_id))

            create_notification(
                booking['worker_user_id'],
                "New Counter-Offer Received",
                f"{user['name']} submitted a counter-offer of ₹{amount:,.0f} for booking {booking['booking_ref']}.",
                f"/worker/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "OFFER_SUBMITTED", f"Booking {booking_id}, Amount: {amount}")
            flash(f"Counter-offer of ₹{amount:,.0f} sent successfully!", "success")

        except Exception as e:
            db.rollback()
            flash("Failed to submit counter-offer. Please try again.", "error")

        return redirect(url_for('customer_booking_detail', booking_id=booking_id))

    @app.route('/customer/bookings/<int:booking_id>/accept', methods=['POST'])
    @customer_required
    def customer_accept_offer(booking_id):
        validate_csrf()
        user = get_current_user()
        db = get_db()

        booking = db.execute("""
            SELECT b.*, w.user_id as worker_user_id
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            WHERE b.id = ? AND b.customer_id = ?
        """, (booking_id, user['id'])).fetchone()

        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] not in ('pending', 'countered'):
            flash("This booking cannot be accepted at this stage.", "error")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        latest_offer = db.execute("""
            SELECT * FROM offers WHERE booking_id = ? ORDER BY id DESC LIMIT 1
        """, (booking_id,)).fetchone()

        if not latest_offer or latest_offer['sender_id'] == user['id']:
            flash("You cannot accept your own offer. Awaiting worker response.", "error")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        agreed_price = latest_offer['amount']

        try:
            # Supersede all other offers and accept latest
            db.execute("UPDATE offers SET status = 'superseded' WHERE booking_id = ? AND id != ?", (booking_id, latest_offer['id']))
            db.execute("UPDATE offers SET status = 'accepted' WHERE id = ?", (latest_offer['id'],))

            # Update booking to confirmed
            db.execute("""
                UPDATE bookings 
                SET agreed_price = ?, status = 'confirmed', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (agreed_price, booking_id))

            create_notification(
                booking['worker_user_id'],
                "Offer Accepted! Booking Confirmed",
                f"{user['name']} accepted your offer of ₹{agreed_price:,.0f} for booking {booking['booking_ref']}.",
                f"/worker/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "OFFER_ACCEPTED", f"Booking {booking_id}, Final Price: {agreed_price}")
            flash(f"Offer accepted! Booking confirmed at ₹{agreed_price:,.0f}.", "success")

        except Exception as e:
            db.rollback()
            flash("Failed to accept offer. Please try again.", "error")

        return redirect(url_for('customer_booking_detail', booking_id=booking_id))

    @app.route('/customer/bookings/<int:booking_id>/cancel', methods=['POST'])
    @customer_required
    def customer_cancel_booking(booking_id):
        validate_csrf()
        user = get_current_user()
        reason = request.form.get('reason', '').strip() or "Cancelled by customer."

        db = get_db()
        booking = db.execute("""
            SELECT b.*, w.user_id as worker_user_id
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            WHERE b.id = ? AND b.customer_id = ?
        """, (booking_id, user['id'])).fetchone()

        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] in ('completed', 'cancelled', 'rejected'):
            flash("This booking is already closed.", "warning")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        try:
            db.execute("""
                UPDATE bookings 
                SET status = 'cancelled', cancelled_by = ?, cancel_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (user['id'], reason, booking_id))

            db.execute("UPDATE offers SET status = 'rejected' WHERE booking_id = ? AND status = 'pending'", (booking_id,))

            create_notification(
                booking['worker_user_id'],
                "Booking Cancelled",
                f"{user['name']} cancelled booking {booking['booking_ref']}. Reason: {reason}",
                f"/worker/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "BOOKING_CANCELLED", f"Booking {booking_id}, Reason: {reason}")
            flash("Booking has been cancelled.", "info")

        except Exception as e:
            db.rollback()
            flash("Error cancelling booking.", "error")

        return redirect(url_for('customer_booking_detail', booking_id=booking_id))

    @app.route('/customer/bookings/<int:booking_id>/complete', methods=['POST'])
    @customer_required
    def customer_complete_booking(booking_id):
        validate_csrf()
        user = get_current_user()
        db = get_db()

        booking = db.execute("""
            SELECT b.*, w.user_id as worker_user_id
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            WHERE b.id = ? AND b.customer_id = ?
        """, (booking_id, user['id'])).fetchone()

        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] not in ('confirmed', 'in_progress'):
            flash("Only confirmed or in-progress jobs can be completed.", "warning")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        try:
            db.execute("""
                UPDATE bookings SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (booking_id,))

            create_notification(
                booking['worker_user_id'],
                "Service Marked Completed!",
                f"{user['name']} confirmed completion for booking {booking['booking_ref']}.",
                f"/worker/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "BOOKING_COMPLETED", f"Booking {booking_id} completed by customer")
            flash("Service marked as completed! Please share a review to help others in the community.", "success")

        except Exception as e:
            db.rollback()
            flash("Error updating booking status.", "error")

        return redirect(url_for('customer_booking_detail', booking_id=booking_id))

    @app.route('/customer/bookings/<int:booking_id>/review', methods=['POST'])
    @customer_required
    def customer_submit_review(booking_id):
        validate_csrf()
        user = get_current_user()
        db = get_db()

        booking = db.execute("""
            SELECT b.*, w.user_id as worker_user_id
            FROM bookings b
            JOIN workers w ON b.worker_id = w.id
            WHERE b.id = ? AND b.customer_id = ?
        """, (booking_id, user['id'])).fetchone()

        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] != 'completed':
            flash("You can only review services that have been marked completed.", "error")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        existing_review = db.execute("SELECT id FROM reviews WHERE booking_id = ?", (booking_id,)).fetchone()
        if existing_review:
            flash("You have already reviewed this booking.", "warning")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        try:
            rating = int(request.form.get('rating', 5))
            if rating < 1 or rating > 5:
                flash("Rating must be between 1 and 5 stars.", "error")
                return redirect(url_for('customer_booking_detail', booking_id=booking_id))
        except ValueError:
            flash("Invalid rating value.", "error")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        comment = request.form.get('comment', '').strip()
        if not comment or len(comment) < 5:
            flash("Please write at least a few words describing your experience.", "error")
            return redirect(url_for('customer_booking_detail', booking_id=booking_id))

        try:
            db.execute("""
                INSERT INTO reviews (booking_id, customer_id, worker_id, rating, comment)
                VALUES (?, ?, ?, ?, ?)
            """, (booking_id, user['id'], booking['worker_id'], rating, comment))

            create_notification(
                booking['worker_user_id'],
                "New Customer Review Received!",
                f"{user['name']} gave you a {rating}-star review for booking {booking['booking_ref']}.",
                f"/worker/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "REVIEW_SUBMITTED", f"Booking {booking_id}, Rating: {rating}")
            flash("Thank you! Your review has been published.", "success")

        except Exception as e:
            db.rollback()
            flash("Failed to submit review.", "error")

        return redirect(url_for('customer_booking_detail', booking_id=booking_id))

    @app.route('/customer/profile', methods=['GET', 'POST'])
    @customer_required
    def customer_profile():
        user = get_current_user()
        db = get_db()

        if request.method == 'POST':
            validate_csrf()
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            city = request.form.get('city', '').strip()

            if not name or not city:
                flash("Name and city cannot be empty.", "error")
                return render_template('customer/profile.html', user=user)

            db.execute("UPDATE users SET name = ?, phone = ?, city = ? WHERE id = ?", (name, phone, city, user['id']))
            db.commit()
            session['user_name'] = name
            log_audit(user['id'], "PROFILE_UPDATED")
            flash("Profile updated successfully.", "success")
            return redirect(url_for('customer_profile'))

        return render_template('customer/profile.html', user=user)

    # -------------------------------------------------------------
    # Worker Routes
    # -------------------------------------------------------------
    @app.route('/worker/dashboard')
    @worker_required
    def worker_dashboard():
        worker = get_current_worker()
        user = get_current_user()
        if not worker:
            abort(404, description="Worker profile not found.")

        db = get_db()
        stats = get_worker_rating_stats(worker['id'])

        total_requests = db.execute("SELECT COUNT(id) FROM bookings WHERE worker_id = ?", (worker['id'],)).fetchone()[0]
        pending_requests = db.execute("SELECT COUNT(id) FROM bookings WHERE worker_id = ? AND status IN ('pending', 'countered')", (worker['id'],)).fetchone()[0]
        active_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE worker_id = ? AND status IN ('confirmed', 'in_progress')", (worker['id'],)).fetchone()[0]
        completed_jobs = db.execute("SELECT COUNT(id) FROM bookings WHERE worker_id = ? AND status = 'completed'", (worker['id'],)).fetchone()[0]
        
        # Calculate total earnings from agreed prices on completed jobs
        earnings_row = db.execute("SELECT SUM(agreed_price) FROM bookings WHERE worker_id = ? AND status = 'completed'", (worker['id'],)).fetchone()
        total_earnings = earnings_row[0] if earnings_row and earnings_row[0] else 0.0

        # Recent bookings
        recent_bookings = db.execute("""
            SELECT b.*, u.name as customer_name, u.phone as customer_phone, u.city as customer_city
            FROM bookings b
            JOIN users u ON b.customer_id = u.id
            WHERE b.worker_id = ?
            ORDER BY b.updated_at DESC LIMIT 5
        """, (worker['id'],)).fetchall()

        return render_template(
            'worker/dashboard.html',
            worker=worker,
            user=user,
            rating_stats=stats,
            total_requests=total_requests,
            pending_requests=pending_requests,
            active_bookings=active_bookings,
            completed_jobs=completed_jobs,
            total_earnings=total_earnings,
            recent_bookings=recent_bookings
        )

    @app.route('/worker/bookings')
    @worker_required
    def worker_bookings():
        worker = get_current_worker()
        status_filter = request.args.get('status', 'all').strip()

        db = get_db()
        conditions = ["b.worker_id = ?"]
        params = [worker['id']]

        if status_filter != 'all':
            if status_filter == 'requests':
                conditions.append("b.status IN ('pending', 'countered')")
            elif status_filter == 'active':
                conditions.append("b.status IN ('confirmed', 'in_progress')")
            else:
                conditions.append("b.status = ?")
                params.append(status_filter)

        where_clause = " AND ".join(conditions)
        bookings = db.execute(f"""
            SELECT b.*, u.name as customer_name, u.phone as customer_phone, u.city as customer_city
            FROM bookings b
            JOIN users u ON b.customer_id = u.id
            WHERE {where_clause}
            ORDER BY b.updated_at DESC
        """, params).fetchall()

        return render_template('worker/bookings.html', bookings=bookings, current_status=status_filter)

    @app.route('/worker/bookings/<int:booking_id>')
    @worker_required
    def worker_booking_detail(booking_id):
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        booking = db.execute("""
            SELECT b.*, u.name as customer_name, u.phone as customer_phone, u.email as customer_email, u.city as customer_city
            FROM bookings b
            JOIN users u ON b.customer_id = u.id
            WHERE b.id = ? AND b.worker_id = ?
        """, (booking_id, worker['id'])).fetchone()

        if not booking:
            abort(404, description="Booking not found or access denied.")

        offers = db.execute("""
            SELECT o.*, u.name as sender_name, u.role as sender_role
            FROM offers o
            JOIN users u ON o.sender_id = u.id
            WHERE o.booking_id = ?
            ORDER BY o.created_at ASC, o.id ASC
        """, (booking_id,)).fetchall()

        latest_offer = offers[-1] if offers else None
        review = db.execute("SELECT * FROM reviews WHERE booking_id = ?", (booking_id,)).fetchone()

        return render_template(
            'worker/booking_detail.html',
            booking=booking,
            offers=offers,
            latest_offer=latest_offer,
            review=review
        )

    @app.route('/worker/bookings/<int:booking_id>/offer', methods=['POST'])
    @worker_required
    def worker_submit_offer(booking_id):
        validate_csrf()
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        booking = db.execute("SELECT * FROM bookings WHERE id = ? AND worker_id = ?", (booking_id, worker['id'])).fetchone()
        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] not in ('pending', 'countered'):
            flash("This booking is no longer in negotiation.", "error")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        latest_offer = db.execute("SELECT * FROM offers WHERE booking_id = ? ORDER BY id DESC LIMIT 1", (booking_id,)).fetchone()
        if latest_offer and latest_offer['sender_id'] == user['id']:
            flash("You have already submitted the most recent counter-offer. Awaiting customer response.", "warning")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        amount_str = request.form.get('amount', '').strip()
        note = request.form.get('note', '').strip()

        try:
            amount = float(amount_str)
            if amount <= 0:
                flash("Offer must be a valid positive amount.", "error")
                return redirect(url_for('worker_booking_detail', booking_id=booking_id))
        except ValueError:
            flash("Invalid offer amount.", "error")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        try:
            db.execute("UPDATE offers SET status = 'superseded' WHERE booking_id = ? AND status = 'pending'", (booking_id,))
            db.execute("""
                INSERT INTO offers (booking_id, sender_id, amount, note, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (booking_id, user['id'], amount, note or "Worker counter-offer."))

            db.execute("""
                UPDATE bookings 
                SET current_offer = ?, status = 'countered', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (amount, booking_id))

            create_notification(
                booking['customer_id'],
                "Worker Sent a Counter-Offer",
                f"{user['name']} submitted a counter-offer of ₹{amount:,.0f} for your booking {booking['booking_ref']}.",
                f"/customer/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "WORKER_COUNTER_OFFER", f"Booking {booking_id}, Amount: {amount}")
            flash(f"Counter-offer of ₹{amount:,.0f} sent to customer.", "success")

        except Exception as e:
            db.rollback()
            flash("Failed to submit counter-offer.", "error")

        return redirect(url_for('worker_booking_detail', booking_id=booking_id))

    @app.route('/worker/bookings/<int:booking_id>/accept', methods=['POST'])
    @worker_required
    def worker_accept_offer(booking_id):
        validate_csrf()
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        booking = db.execute("SELECT * FROM bookings WHERE id = ? AND worker_id = ?", (booking_id, worker['id'])).fetchone()
        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] not in ('pending', 'countered'):
            flash("This booking cannot be accepted at this stage.", "error")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        latest_offer = db.execute("SELECT * FROM offers WHERE booking_id = ? ORDER BY id DESC LIMIT 1", (booking_id,)).fetchone()
        if not latest_offer or latest_offer['sender_id'] == user['id']:
            flash("You cannot accept your own counter-offer. Awaiting customer response.", "error")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        agreed_price = latest_offer['amount']

        try:
            db.execute("UPDATE offers SET status = 'superseded' WHERE booking_id = ? AND id != ?", (booking_id, latest_offer['id']))
            db.execute("UPDATE offers SET status = 'accepted' WHERE id = ?", (latest_offer['id'],))

            db.execute("""
                UPDATE bookings 
                SET agreed_price = ?, status = 'confirmed', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (agreed_price, booking_id))

            create_notification(
                booking['customer_id'],
                "Worker Accepted Your Offer!",
                f"{user['name']} accepted your offer of ₹{agreed_price:,.0f} for booking {booking['booking_ref']}. The job is now Confirmed!",
                f"/customer/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "WORKER_ACCEPTED_OFFER", f"Booking {booking_id}, Agreed: {agreed_price}")
            flash(f"You accepted the offer! Booking is confirmed at ₹{agreed_price:,.0f}.", "success")

        except Exception as e:
            db.rollback()
            flash("Failed to accept offer.", "error")

        return redirect(url_for('worker_booking_detail', booking_id=booking_id))

    @app.route('/worker/bookings/<int:booking_id>/reject', methods=['POST'])
    @worker_required
    def worker_reject_booking(booking_id):
        validate_csrf()
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        booking = db.execute("SELECT * FROM bookings WHERE id = ? AND worker_id = ?", (booking_id, worker['id'])).fetchone()
        if not booking:
            abort(404, description="Booking not found.")

        if booking['status'] in ('completed', 'cancelled', 'rejected'):
            flash("Booking is already closed.", "warning")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        reason = request.form.get('reason', '').strip() or "Worker declined the request."

        try:
            db.execute("""
                UPDATE bookings 
                SET status = 'rejected', cancelled_by = ?, cancel_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (user['id'], reason, booking_id))

            db.execute("UPDATE offers SET status = 'rejected' WHERE booking_id = ? AND status = 'pending'", (booking_id,))

            create_notification(
                booking['customer_id'],
                "Booking Request Declined",
                f"{user['name']} was unable to accept booking {booking['booking_ref']}. Reason: {reason}",
                f"/customer/bookings/{booking_id}"
            )

            db.commit()
            log_audit(user['id'], "WORKER_REJECTED_BOOKING", f"Booking {booking_id}")
            flash("Booking request declined.", "info")

        except Exception as e:
            db.rollback()
            flash("Error rejecting booking.", "error")

        return redirect(url_for('worker_booking_detail', booking_id=booking_id))

    @app.route('/worker/bookings/<int:booking_id>/start', methods=['POST'])
    @worker_required
    def worker_start_job(booking_id):
        validate_csrf()
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        booking = db.execute("SELECT * FROM bookings WHERE id = ? AND worker_id = ?", (booking_id, worker['id'])).fetchone()
        if not booking or booking['status'] != 'confirmed':
            flash("Only confirmed bookings can be started.", "error")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        db.execute("UPDATE bookings SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (booking_id,))
        create_notification(
            booking['customer_id'],
            "Worker Has Started the Job!",
            f"{user['name']} has marked your booking {booking['booking_ref']} as In Progress.",
            f"/customer/bookings/{booking_id}"
        )
        db.commit()
        log_audit(user['id'], "JOB_STARTED", f"Booking {booking_id}")
        flash("Job status updated to In Progress.", "success")
        return redirect(url_for('worker_booking_detail', booking_id=booking_id))

    @app.route('/worker/bookings/<int:booking_id>/complete', methods=['POST'])
    @worker_required
    def worker_complete_job(booking_id):
        validate_csrf()
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        booking = db.execute("SELECT * FROM bookings WHERE id = ? AND worker_id = ?", (booking_id, worker['id'])).fetchone()
        if not booking or booking['status'] not in ('confirmed', 'in_progress'):
            flash("Only confirmed or in-progress bookings can be marked complete.", "error")
            return redirect(url_for('worker_booking_detail', booking_id=booking_id))

        db.execute("UPDATE bookings SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (booking_id,))
        create_notification(
            booking['customer_id'],
            "Service Completed by Worker",
            f"{user['name']} completed your service for booking {booking['booking_ref']}. Please leave a review!",
            f"/customer/bookings/{booking_id}"
        )
        db.commit()
        log_audit(user['id'], "JOB_COMPLETED_WORKER", f"Booking {booking_id}")
        flash("Job marked as Completed! Great work.", "success")
        return redirect(url_for('worker_booking_detail', booking_id=booking_id))

    @app.route('/worker/availability/toggle', methods=['POST'])
    @worker_required
    def worker_toggle_availability():
        validate_csrf()
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        new_status = 0 if worker['available'] else 1
        db.execute("UPDATE workers SET available = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, worker['id']))
        db.commit()

        status_text = "Available for new bookings" if new_status else "Unavailable / Offline"
        log_audit(user['id'], "AVAILABILITY_TOGGLED", f"Status: {status_text}")
        flash(f"Your availability has been updated to: {status_text}.", "info")
        return redirect(request.referrer or url_for('worker_dashboard'))

    @app.route('/worker/profile', methods=['GET', 'POST'])
    @worker_required
    def worker_profile():
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()
        categories = db.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY name ASC").fetchall()

        if request.method == 'POST':
            validate_csrf()
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            city = request.form.get('city', '').strip()
            category = request.form.get('category', '').strip()
            bio = request.form.get('bio', '').strip()
            service_area = request.form.get('service_area', '').strip()
            
            try:
                starting_price = float(request.form.get('starting_price', 300))
                if starting_price < 50:
                    flash("Starting price must be at least ₹50.", "error")
                    return render_template('worker/profile.html', worker=worker, user=user, categories=categories)
            except ValueError:
                flash("Invalid starting price.", "error")
                return render_template('worker/profile.html', worker=worker, user=user, categories=categories)

            try:
                experience = int(request.form.get('experience_years', 1))
            except ValueError:
                experience = 1

            if not name or not city or not category:
                flash("Name, city, and category are required.", "error")
                return render_template('worker/profile.html', worker=worker, user=user, categories=categories)

            db.execute("UPDATE users SET name = ?, phone = ?, city = ? WHERE id = ?", (name, phone, city, user['id']))
            db.execute("""
                UPDATE workers 
                SET category = ?, bio = ?, experience_years = ?, starting_price = ?, service_area = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (category, bio, experience, starting_price, service_area, worker['id']))
            db.commit()

            session['user_name'] = name
            log_audit(user['id'], "WORKER_PROFILE_UPDATED")
            flash("Worker profile updated successfully.", "success")
            return redirect(url_for('worker_profile'))

        return render_template('worker/profile.html', worker=worker, user=user, categories=categories)

    @app.route('/worker/verification', methods=['GET', 'POST'])
    @worker_required
    def worker_verification():
        worker = get_current_worker()
        user = get_current_user()
        db = get_db()

        if request.method == 'POST':
            validate_csrf()
            doc_type = request.form.get('doc_type', '').strip()
            doc_number = request.form.get('doc_number', '').strip()
            note = request.form.get('note', '').strip()
            file = request.files.get('document_file')

            if not doc_type or not doc_number:
                flash("Please choose document type and enter document number.", "error")
                return redirect(url_for('worker_verification'))

            filename = None
            if file and file.filename != '':
                filename, err = save_uploaded_doc(
                    file, worker['id'], app.config['UPLOAD_FOLDER'], app.config['ALLOWED_EXTENSIONS']
                )
                if err:
                    flash(f"Upload error: {err}", "error")
                    return redirect(url_for('worker_verification'))

            # Insert verification record
            db.execute("""
                INSERT INTO verifications (worker_id, doc_type, doc_number, file_path, note, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (worker['id'], doc_type, doc_number, filename, note))

            # Update worker status to pending
            db.execute("UPDATE workers SET verification_status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (worker['id'],))
            db.commit()

            log_audit(user['id'], "VERIFICATION_SUBMITTED", f"Doc: {doc_type}, Number: {doc_number}")
            flash("Verification documents submitted! Our administrative team will review them promptly.", "success")
            return redirect(url_for('worker_verification'))

        # Fetch history of verifications
        verifications = db.execute("""
            SELECT * FROM verifications WHERE worker_id = ? ORDER BY created_at DESC
        """, (worker['id'],)).fetchall()

        return render_template('worker/verification.html', worker=worker, user=user, verifications=verifications)

    # -------------------------------------------------------------
    # Admin Routes
    # -------------------------------------------------------------
    @app.route('/admin/dashboard')
    @admin_required
    def admin_dashboard():
        db = get_db()

        total_customers = db.execute("SELECT COUNT(id) FROM users WHERE role = 'customer'").fetchone()[0]
        total_workers = db.execute("SELECT COUNT(id) FROM workers").fetchone()[0]
        pending_verifications = db.execute("SELECT COUNT(id) FROM verifications WHERE status = 'pending'").fetchone()[0]
        approved_workers = db.execute("SELECT COUNT(id) FROM workers WHERE verification_status = 'approved'").fetchone()[0]
        
        total_bookings = db.execute("SELECT COUNT(id) FROM bookings").fetchone()[0]
        confirmed_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE status = 'confirmed'").fetchone()[0]
        completed_bookings = db.execute("SELECT COUNT(id) FROM bookings WHERE status = 'completed'").fetchone()[0]

        volume_row = db.execute("SELECT SUM(agreed_price) FROM bookings WHERE status = 'completed'").fetchone()
        platform_gmv = volume_row[0] if volume_row and volume_row[0] else 0.0

        # Support messages metrics
        open_support_messages = db.execute("SELECT COUNT(id) FROM support_messages WHERE status = 'open'").fetchone()[0]
        total_support_messages = db.execute("SELECT COUNT(id) FROM support_messages").fetchone()[0]

        # Category breakdown for charts or stats
        category_stats = db.execute("""
            SELECT category, COUNT(id) as count 
            FROM workers 
            GROUP BY category 
            ORDER BY count DESC
        """).fetchall()

        # Recent activities / audit
        recent_audits = db.execute("""
            SELECT a.*, u.name as user_name, u.role as user_role
            FROM audit_logs a
            LEFT JOIN users u ON a.user_id = u.id
            ORDER BY a.created_at DESC LIMIT 6
        """).fetchall()

        return render_template(
            'admin/dashboard.html',
            total_customers=total_customers,
            total_workers=total_workers,
            pending_verifications=pending_verifications,
            approved_workers=approved_workers,
            total_bookings=total_bookings,
            confirmed_bookings=confirmed_bookings,
            completed_bookings=completed_bookings,
            platform_gmv=platform_gmv,
            open_support_messages=open_support_messages,
            total_support_messages=total_support_messages,
            category_stats=category_stats,
            recent_audits=recent_audits
        )

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        role_filter = request.args.get('role', 'all').strip()
        search_query = request.args.get('q', '').strip()

        db = get_db()
        conditions = ["1=1"]
        params = []

        if role_filter != 'all':
            conditions.append("role = ?")
            params.append(role_filter)

        if search_query:
            conditions.append("(name LIKE ? OR email LIKE ? OR city LIKE ?)")
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard])

        where_clause = " AND ".join(conditions)
        users = db.execute(f"""
            SELECT * FROM users WHERE {where_clause} ORDER BY id DESC
        """, params).fetchall()

        return render_template('admin/users.html', users=users, current_role=role_filter, search_query=search_query)

    @app.route('/admin/users/<int:user_id>/toggle-status', methods=['POST'])
    @admin_required
    def admin_toggle_user_status(user_id):
        validate_csrf()
        current_admin = get_current_user()
        db = get_db()

        target_user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target_user:
            abort(404, description="User not found.")

        # Prevent admin locking themselves out or deactivating the last active admin
        if target_user['id'] == current_admin['id']:
            flash("You cannot deactivate your own administrative account.", "error")
            return redirect(url_for('admin_users'))

        if target_user['role'] == 'admin' and target_user['is_active'] == 1:
            active_admin_count = db.execute("SELECT COUNT(id) FROM users WHERE role = 'admin' AND is_active = 1").fetchone()[0]
            if active_admin_count <= 1:
                flash("Cannot deactivate the only active administrator.", "error")
                return redirect(url_for('admin_users'))

        new_status = 0 if target_user['is_active'] else 1
        db.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, user_id))
        db.commit()

        status_text = "activated" if new_status else "suspended"
        log_audit(current_admin['id'], "ADMIN_TOGGLE_USER_STATUS", f"User {user_id} {status_text}")
        flash(f"User {target_user['name']} has been {status_text}.", "info")
        return redirect(url_for('admin_users'))

    @app.route('/admin/workers')
    @admin_required
    def admin_workers():
        status_filter = request.args.get('status', 'all').strip()
        search_query = request.args.get('q', '').strip()

        db = get_db()
        conditions = ["1=1"]
        params = []

        if status_filter != 'all':
            conditions.append("w.verification_status = ?")
            params.append(status_filter)

        if search_query:
            conditions.append("(u.name LIKE ? OR w.category LIKE ? OR u.city LIKE ?)")
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard])

        where_clause = " AND ".join(conditions)
        raw_workers = db.execute(f"""
            SELECT w.*, u.name, u.email, u.phone, u.city, u.is_active
            FROM workers w
            JOIN users u ON w.user_id = u.id
            WHERE {where_clause}
            ORDER BY w.id DESC
        """, params).fetchall()

        workers = []
        for rw in raw_workers:
            data = dict(rw)
            stats = get_worker_rating_stats(rw['id'])
            data['avg_rating'] = stats['avg_rating']
            data['total_reviews'] = stats['total_reviews']
            workers.append(data)

        return render_template('admin/workers.html', workers=workers, current_status=status_filter, search_query=search_query)

    @app.route('/admin/verifications')
    @admin_required
    def admin_verifications():
        status_filter = request.args.get('status', 'all').strip()
        db = get_db()

        conditions = ["1=1"]
        params = []
        if status_filter != 'all':
            conditions.append("v.status = ?")
            params.append(status_filter)

        where_clause = " AND ".join(conditions)
        verifications = db.execute(f"""
            SELECT v.*, w.category, w.starting_price, u.name as worker_name, u.email as worker_email, u.phone as worker_phone, u.city as worker_city
            FROM verifications v
            JOIN workers w ON v.worker_id = w.id
            JOIN users u ON w.user_id = u.id
            WHERE {where_clause}
            ORDER BY v.created_at DESC
        """, params).fetchall()

        return render_template('admin/verifications.html', verifications=verifications, current_status=status_filter)

    @app.route('/admin/verifications/<int:verification_id>/review', methods=['POST'])
    @admin_required
    def admin_review_verification(verification_id):
        validate_csrf()
        current_admin = get_current_user()
        action = request.form.get('action', '').strip().lower()
        admin_note = request.form.get('admin_note', '').strip()

        if action not in ('approve', 'reject'):
            flash("Invalid verification action.", "error")
            return redirect(url_for('admin_verifications'))

        db = get_db()
        verification = db.execute("""
            SELECT v.*, w.user_id as worker_user_id
            FROM verifications v
            JOIN workers w ON v.worker_id = w.id
            WHERE v.id = ?
        """, (verification_id,)).fetchone()

        if not verification:
            abort(404, description="Verification request not found.")

        new_status = 'approved' if action == 'approve' else 'rejected'

        try:
            # Update verification record
            db.execute("""
                UPDATE verifications 
                SET status = ?, admin_note = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_status, admin_note, current_admin['id'], verification_id))

            # Update worker status
            db.execute("""
                UPDATE workers 
                SET verification_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_status, verification['worker_id']))

            # Notify worker
            if new_status == 'approved':
                create_notification(
                    verification['worker_user_id'],
                    "Verification Approved!",
                    "Congratulations! Your verification documents have been approved by admin. Your profile is now live for bookings.",
                    "/worker/dashboard"
                )
            else:
                create_notification(
                    verification['worker_user_id'],
                    "Verification Update: Action Required",
                    f"Your verification request was rejected. Admin note: {admin_note or 'Please review submitted details.'}",
                    "/worker/verification"
                )

            db.commit()
            log_audit(current_admin['id'], f"VERIFICATION_{new_status.upper()}", f"Verification ID: {verification_id}, Note: {admin_note}")
            flash(f"Verification request {new_status}.", "success")

        except Exception as e:
            db.rollback()
            flash("Failed to process verification.", "error")

        return redirect(url_for('admin_verifications'))

    @app.route('/admin/bookings')
    @admin_required
    def admin_bookings():
        status_filter = request.args.get('status', 'all').strip()
        search_query = request.args.get('q', '').strip()

        db = get_db()
        conditions = ["1=1"]
        params = []

        if status_filter != 'all':
            conditions.append("b.status = ?")
            params.append(status_filter)

        if search_query:
            conditions.append("(b.booking_ref LIKE ? OR cu.name LIKE ? OR wu.name LIKE ? OR b.service LIKE ?)")
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        where_clause = " AND ".join(conditions)
        bookings = db.execute(f"""
            SELECT b.*, cu.name as customer_name, cu.email as customer_email,
                   wu.name as worker_name, wu.email as worker_email, w.category
            FROM bookings b
            JOIN users cu ON b.customer_id = cu.id
            JOIN workers w ON b.worker_id = w.id
            JOIN users wu ON w.user_id = wu.id
            WHERE {where_clause}
            ORDER BY b.updated_at DESC
        """, params).fetchall()

        return render_template('admin/bookings.html', bookings=bookings, current_status=status_filter, search_query=search_query)

    @app.route('/admin/bookings/<int:booking_id>')
    @admin_required
    def admin_booking_detail(booking_id):
        db = get_db()
        booking = db.execute("""
            SELECT b.*, cu.name as customer_name, cu.email as customer_email, cu.phone as customer_phone,
                   wu.name as worker_name, wu.email as worker_email, wu.phone as worker_phone, w.category
            FROM bookings b
            JOIN users cu ON b.customer_id = cu.id
            JOIN workers w ON b.worker_id = w.id
            JOIN users wu ON w.user_id = wu.id
            WHERE b.id = ?
        """, (booking_id,)).fetchone()

        if not booking:
            abort(404, description="Booking not found.")

        offers = db.execute("""
            SELECT o.*, u.name as sender_name, u.role as sender_role
            FROM offers o
            JOIN users u ON o.sender_id = u.id
            WHERE o.booking_id = ?
            ORDER BY o.created_at ASC
        """, (booking_id,)).fetchall()

        review = db.execute("SELECT * FROM reviews WHERE booking_id = ?", (booking_id,)).fetchone()

        return render_template('admin/booking_detail.html', booking=booking, offers=offers, review=review)

    @app.route('/admin/categories', methods=['GET', 'POST'])
    @admin_required
    def admin_categories():
        db = get_db()
        admin_user = get_current_user()

        if request.method == 'POST':
            validate_csrf()
            name = request.form.get('name', '').strip()
            slug = request.form.get('slug', '').strip().lower()
            icon = request.form.get('icon', 'wrench').strip()
            desc = request.form.get('description', '').strip()

            if not name or not slug:
                flash("Category name and slug are required.", "error")
                return redirect(url_for('admin_categories'))

            try:
                db.execute("""
                    INSERT INTO categories (name, slug, icon, description, is_active)
                    VALUES (?, ?, ?, ?, 1)
                """, (name, slug, icon, desc))
                db.commit()
                log_audit(admin_user['id'], "CATEGORY_CREATED", f"Name: {name}")
                flash(f"Category '{name}' added successfully.", "success")
            except Exception as e:
                db.rollback()
                flash("Category name or slug already exists.", "error")

            return redirect(url_for('admin_categories'))

        categories = db.execute("SELECT * FROM categories ORDER BY id ASC").fetchall()
        return render_template('admin/categories.html', categories=categories)

    @app.route('/admin/categories/<int:cat_id>/toggle', methods=['POST'])
    @admin_required
    def admin_toggle_category(cat_id):
        validate_csrf()
        admin_user = get_current_user()
        db = get_db()
        cat = db.execute("SELECT * FROM categories WHERE id = ?", (cat_id,)).fetchone()
        if not cat:
            abort(404, description="Category not found.")

        new_status = 0 if cat['is_active'] else 1
        db.execute("UPDATE categories SET is_active = ? WHERE id = ?", (new_status, cat_id))
        db.commit()
        log_audit(admin_user['id'], "CATEGORY_TOGGLED", f"Cat ID: {cat_id}, New: {new_status}")
        flash(f"Category '{cat['name']}' status updated.", "info")
        return redirect(url_for('admin_categories'))

    @app.route('/admin/audit-logs')
    @admin_required
    def admin_audit_logs():
        db = get_db()
        logs = db.execute("""
            SELECT a.*, u.name as user_name, u.role as user_role
            FROM audit_logs a
            LEFT JOIN users u ON a.user_id = u.id
            ORDER BY a.created_at DESC LIMIT 100
        """).fetchall()
        return render_template('admin/audit_logs.html', logs=logs)

    @app.route('/admin/support')
    @admin_required
    def admin_support():
        status_filter = request.args.get('status', 'all').strip()
        search_query = request.args.get('q', '').strip()

        db = get_db()
        conditions = ["1=1"]
        params = []

        if status_filter != 'all':
            conditions.append("s.status = ?")
            params.append(status_filter)

        if search_query:
            conditions.append("(s.name LIKE ? OR s.email LIKE ? OR s.subject LIKE ? OR s.message LIKE ?)")
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        where_clause = " AND ".join(conditions)
        messages = db.execute(f"""
            SELECT s.*, u.name as registered_user_name, u.role as registered_user_role,
                   ru.name as resolved_by_name
            FROM support_messages s
            LEFT JOIN users u ON s.user_id = u.id
            LEFT JOIN users ru ON s.resolved_by = ru.id
            WHERE {where_clause}
            ORDER BY CASE s.status WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END, s.created_at DESC
        """, params).fetchall()

        open_count = db.execute("SELECT COUNT(id) FROM support_messages WHERE status = 'open'").fetchone()[0]
        in_progress_count = db.execute("SELECT COUNT(id) FROM support_messages WHERE status = 'in_progress'").fetchone()[0]
        resolved_count = db.execute("SELECT COUNT(id) FROM support_messages WHERE status = 'resolved'").fetchone()[0]

        return render_template(
            'admin/support.html',
            messages=messages,
            current_status=status_filter,
            search_query=search_query,
            open_count=open_count,
            in_progress_count=in_progress_count,
            resolved_count=resolved_count
        )

    @app.route('/admin/support/<int:msg_id>')
    @admin_required
    def admin_support_detail(msg_id):
        db = get_db()
        msg = db.execute("""
            SELECT s.*, u.name as registered_user_name, u.role as registered_user_role, u.phone as registered_user_phone,
                   ru.name as resolved_by_name
            FROM support_messages s
            LEFT JOIN users u ON s.user_id = u.id
            LEFT JOIN users ru ON s.resolved_by = ru.id
            WHERE s.id = ?
        """, (msg_id,)).fetchone()

        if not msg:
            abort(404, description="Support message not found.")

        return render_template('admin/support_detail.html', msg=msg)

    @app.route('/admin/support/<int:msg_id>/update', methods=['POST'])
    @admin_required
    def admin_support_update(msg_id):
        validate_csrf()
        current_admin = get_current_user()
        db = get_db()

        msg = db.execute("SELECT * FROM support_messages WHERE id = ?", (msg_id,)).fetchone()
        if not msg:
            abort(404, description="Support message not found.")

        status = request.form.get('status', 'open').strip().lower()
        admin_notes = request.form.get('admin_notes', '').strip()

        if status not in ('open', 'in_progress', 'resolved', 'closed'):
            flash("Invalid support message status.", "error")
            return redirect(url_for('admin_support_detail', msg_id=msg_id))

        db.execute("""
            UPDATE support_messages 
            SET status = ?, admin_notes = ?, resolved_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, admin_notes, current_admin['id'], msg_id))

        # If sender was registered, notify them
        if msg['user_id']:
            create_notification(
                msg['user_id'],
                f"Support Ticket Updated: {status.replace('_', ' ').title()}",
                f"Your support inquiry '{msg['subject']}' status has been updated to {status.replace('_', ' ')}. Note: {admin_notes or 'Issue processed by support team.'}",
                "/contact"
            )

        db.commit()
        log_audit(current_admin['id'], "SUPPORT_STATUS_UPDATED", f"ID: {msg_id}, Status: {status}")
        flash(f"Support message #{msg_id} marked as {status.replace('_', ' ')}.", "success")
        return redirect(url_for('admin_support_detail', msg_id=msg_id))

    # -------------------------------------------------------------
    # Document Access Route (Admin/Owner Protected)
    # -------------------------------------------------------------
    @app.route('/uploads/verifications/<path:filename>')
    @login_required
    def secure_uploaded_file(filename):
        user = get_current_user()
        db = get_db()
        
        # Check authorization: user must be admin, or the worker who uploaded this file
        is_admin = user['role'] == 'admin'
        if not is_admin:
            worker = db.execute("SELECT id FROM workers WHERE user_id = ?", (user['id'],)).fetchone()
            if not worker:
                abort(403)
            # Check if this verification record belongs to worker
            ver = db.execute("SELECT id FROM verifications WHERE worker_id = ? AND file_path = ?", (worker['id'], filename)).fetchone()
            if not ver:
                abort(403)

        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # -------------------------------------------------------------
    # Error Handlers
    # -------------------------------------------------------------
    @app.errorhandler(400)
    def bad_request(e):
        return render_template('errors/400.html', error=e), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html', error=e), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html', error=e), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('errors/500.html', error=e), 500

    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        init_db(app)
        seed_db(app)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
