# KaamNearby — Hyperlocal Blue-Collar Services Marketplace

> **Tagline:** "Trusted Local Services, Just Around the Corner."

**KaamNearby** is a complete, production-style, full-stack web application connecting households needing everyday home repairs with background-verified local tradespeople (electricians, plumbers, carpenters, painters, and technicians).

It solves the core problems of opaque pricing, unreliable discovery, and middleman exploitation through **direct, multi-round price negotiation**, **government identity verification**, and **transparent booking management**.

---

## 🌟 Key Features

1. **Role-Based Portals & Dashboards**:
   - **Customer Portal**: Search and filter local verified workers, review trade credentials, create service bookings with initial price offers, negotiate multi-round counter-offers, complete jobs, and submit 1–5 star reviews.
   - **Worker Hub**: Manage trade profile, starting rates, and service areas; toggle availability (Online/Offline); respond to booking requests; propose counter-offers; accept agreed rates; track earnings; and upload identity documents for verification.
   - **Operations & Admin Panel**: Real-time platform metrics (customers, workers, GMV, verifications queue, open support inquiries), inspect and approve/reject worker verification credentials, manage categories, supervise user directory, audit negotiations, manage incoming support tickets, and review security logs.

2. **Customer & User Support Ticketing**:
   - Inquiries sent via the Contact & Help page (`/contact`) are automatically stored in the database.
   - Immediate in-app notifications are generated and delivered to **all active administrators** with a direct link to the support ticket.
   - Admins can manage ticket statuses (`open`, `in_progress`, `resolved`, `closed`), write resolution notes, and track which admin resolved each inquiry.
   - Registered users receive an automatic in-app notification when their inquiry status is updated by an admin.

3. **Multi-Round Price Negotiation Engine**:
   - Both customers and workers participate in an iterative negotiation timeline.
   - Chronological offer history tracking with individual states (`pending`, `countered`, `superseded`, `accepted`, `rejected`).
   - Locking mechanism: Once an offer is accepted by either party, the price is locked (`agreed_price`), the booking is confirmed, and further tampering is prevented.

3. **Worker Identity & Credential Verification**:
   - Workers submit identity proofs (Aadhaar, PAN, Voter ID, Driving License, or ITI Trade Certificates) with secure document uploads.
   - Administrative review queue with approve/reject decisions and feedback notes.
   - Only approved workers receive the public **Verified** badge and appear in public discovery.

4. **Real Worker Search, Filtering & Reviews**:
   - Multi-parameter filtering by keyword, trade category, city/locality, price range, and availability.
   - Genuine rating calculations derived exclusively from completed customer bookings.

5. **Security & Production Best Practices**:
   - Secure Flask session management with `SameSite=Lax` and `HttpOnly`.
   - Passwords hashed using Werkzeug cryptographic hashing (`scrypt` / `pbkdf2`).
   - CSRF token validation on all state-changing `POST` requests.
   - Parameterized SQL queries preventing SQL injection.
   - Safe file uploads with extension whitelisting and access-controlled endpoints for identity proofs.

---

## 🛠️ Technology Stack

- **Backend**: Python 3 (3.10+) & Flask 3.x
- **Database**: SQLite3 (`instance/kaamnearby.db`) with foreign key constraints and transactional integrity
- **Frontend**: HTML5 Semantic markup, Modern CSS3 with Custom Design System, Vanilla JavaScript
- **Templates**: Jinja2 with custom filters (`currency`, `format_date`)
- **Security**: Werkzeug password hashing, Token-based CSRF protection
- **Icons**: Lucide Icons
- **Testing**: Python `unittest` test suite covering authentication, permissions, booking creation, price negotiation, and verifications

---

## 📁 Project Directory Structure

```text
kaamnearby/
├── app.py                      # Application entry point, routes, handlers
├── auth.py                     # Authentication helpers, session & CSRF protection
├── config.py                   # Configuration classes (Dev, Testing, Prod)
├── database.py                 # SQLite database schema, connections, and seeder
├── helpers.py                  # Audit logging, notifications, worker rating stats
├── requirements.txt            # Python dependencies
├── .env.example                # Example environment variable file
├── .gitignore                  # Git ignore rules
├── README.md                   # Complete documentation & startup guide
├── instance/
│   └── kaamnearby.db           # SQLite database
├── uploads/
│   └── verifications/          # Securely stored verification documents
├── static/
│   ├── css/
│   │   ├── style.css           # Global design system & landing page styles
│   │   ├── dashboard.css       # Dashboards & price negotiation UI styles
│   │   └── responsive.css      # Mobile, tablet, & drawer responsiveness
│   └── js/
│       ├── main.js             # Navigation, alerts, modals, dropdowns
│       └── dashboard.js        # Counter-offer toggle & star rating widget
├── templates/
│   ├── base.html               # Master layout template
│   ├── index.html              # Landing page
│   ├── services.html           # Worker search & directory
│   ├── worker_detail.html      # Worker profile & booking form
│   ├── login.html              # Login page with demo credentials
│   ├── register.html           # Customer & worker registration
│   ├── about.html              # About mission & story
│   ├── how_it_works.html       # Step-by-step workflow guide
│   ├── contact.html            # Help & support center
│   ├── terms.html              # Terms of service
│   ├── privacy.html            # Privacy policy
│   ├── notifications.html      # In-app notifications
│   ├── customer/               # Customer portal templates
│   ├── worker/                 # Worker hub templates
│   ├── admin/                  # Super admin templates
│   ├── partials/               # Reusable components (navbar, footer, sidebar, alerts)
│   └── errors/                 # 400, 403, 404, 500 error pages
└── tests/                      # Automated test suite
    ├── test_base.py
    ├── test_auth.py
    ├── test_permissions.py
    ├── test_bookings.py
    ├── test_offers.py
    ├── test_verifications.py
    └── test_support.py
```

---

## 🚀 Local Setup & Installation

### 1. Prerequisites
- Python 3.10 or higher installed on your computer.

### 2. Open Project in Terminal / PowerShell
Navigate to the project root folder:
```powershell
cd "c:\Users\hp\Desktop\gl bajaj"
```

### 3. (Optional) Create and Activate a Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 4. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 5. Initialize & Seed Database
The application automatically creates and seeds the database on first run. You can also trigger it manually via:
```powershell
python -c "import database, config, app; a = app.create_app(); database.init_db(a); database.seed_db(a); print('Ready!')"
```

---

## 🔑 Pre-Configured Test Accounts

The seeded database comes with accounts across all three roles for local testing:

| Role | Email | Password | Details |
|---|---|---|---|
| **Administrator** | `admin@kaamnearby.com` | `Admin@12345` | Full platform supervision & verification approval |
| **Household Customer** | `rahul.customer@example.com` | `Customer@12345` | Customer in Greater Noida with seeded booking |
| **Approved Worker** | `suresh.electrician@example.com` | `Worker@12345` | Verified Electrician in Greater Noida |
| **Pending Worker** | `dinesh.repair@example.com` | `Worker@12345` | Appliance Repair tech awaiting admin approval |

---

## ▶️ Running the Application

Start the Flask local development server:
```powershell
python app.py
```

Open your web browser and visit:
👉 **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 🧪 Testing the Multi-Round Price Negotiation Workflow

1. Open **[http://127.0.0.1:5000/login](http://127.0.0.1:5000/login)** and sign in as **Customer**:
   - `rahul.customer@example.com` / `Customer@12345`
2. Go to **Explore Services** -> Click **Suresh Kumar Sharma** (Electrician).
3. Fill out the booking form:
   - Date: Pick an upcoming date.
   - Problem: "Ceiling fan regulator wiring loose."
   - Initial Offer: `₹400`
   - Click **Send Booking Request**.
4. Log out and sign in as **Worker**:
   - `suresh.electrician@example.com` / `Worker@12345`
5. Go to **Bookings & Requests** -> Open the new booking inquiry:
   - Click **Make Counter-Offer**.
   - Amount: `₹500`
   - Note: "Requires replacement heavy-duty capacitor and safety check."
   - Click **Send Counter-Offer to Customer**.
6. Log out and sign back in as **Customer**:
   - Open **My Bookings** -> Open the booking.
   - You will see the chronological timeline with the worker's ₹500 counter-offer.
   - Click **Make Counter-Offer** -> Enter `₹460` -> Submit.
7. Log out and sign back in as **Worker**:
   - Open the booking.
   - Click the green **Accept ₹460** button.
   - The booking status updates to **Confirmed** and the price locks at **₹460**!
8. Click **Start Work (Mark In Progress)** -> and subsequently **Mark Service as Completed**.
9. Sign back in as Customer and leave a **5-star review** with feedback!

---

## 🧪 Running the Automated Test Suite

To run all automated tests verifying authentication, permissions, bookings, negotiations, and admin verifications:

```powershell
python -m unittest discover tests
```

---

## 🛡️ Limitations & Production Roadmap

- **Payments**: The application uses direct cash/UPI settlement upon completion. For automated online payments, integrations with payment gateways like Razorpay or Cashfree can be connected via webhooks.
- **SMS & WhatsApp Alerts**: Notifications are currently handled via the in-app notification center. A production deployment can link an SMS provider like Twilio or Fast2SMS.
- **Maps & GPS Distance**: Proximity uses locality and city matching. Google Maps Places API can be attached for real-time kilometer-radius calculations.

#   g l - b a j a j  
 