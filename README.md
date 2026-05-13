# VM Manager — VUNet Systems

Internal web app to track Virtual Machines across cloud providers.
**Tracking only — no provisioning.**

---

## Stack

| Layer      | Technology                          |
|-----------|-------------------------------------|
| Backend    | Python 3.10 + Flask 3               |
| Database   | MongoDB Atlas (free tier)           |
| Frontend   | Jinja2 + Bootstrap 5                |
| Charts     | Chart.js (CDN)                      |
| Deployment | Render.com free tier                |

---

## Local Setup

### 1. Clone and enter the project

```bash
cd vm-manager
```

### 2. Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Or install globally (user scope):

```bash
python3 -m pip install --user -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
- **`MONGO_URI`** — paste your Atlas connection string  
  *(Atlas → Cluster → Connect → Drivers → Python)*
- **`SECRET_KEY`** — run `python3 -c "import secrets; print(secrets.token_hex(32))"` and paste the output
- **`DB_NAME`** — keep `vmmanager` unless you changed it in Atlas

### 4. Seed the database

```bash
python seed.py
```

Creates:
- Admin user: `admin` / `admin123`  
- 15 sample VMs (active, expiring, overdue, inactive)

### 5. Run the app

```bash
python run.py
```

Visit: **http://localhost:5000**  
Login: `admin` / `admin123`

---

## Project Structure

```
vm-manager/
├── app/
│   ├── __init__.py          # Flask app factory + MongoDB setup
│   ├── models/
│   │   ├── vm.py            # VM CRUD helpers
│   │   └── user.py          # User model (Flask-Login)
│   ├── routes/
│   │   ├── auth.py          # Login / logout
│   │   ├── dashboard.py     # VM CRUD + CSV export
│   │   └── reports.py       # Reports + chart data endpoints + CSV export
│   ├── templates/
│   │   ├── base.html        # Navbar, flash messages
│   │   ├── login.html
│   │   ├── dashboard.html   # VM table, modals, filters
│   │   └── reports.html     # 4-tab reports with Chart.js
│   └── static/
│       ├── css/custom.css
│       └── js/charts.js
├── config.py                # Config (reads from .env)
├── run.py                   # Entry point
├── seed.py                  # Sample data + admin user
├── requirements.txt
├── Procfile                 # Gunicorn for Render
└── .env.example
```

---

## API Endpoints

| Method | Endpoint                          | Description                  |
|--------|-----------------------------------|------------------------------|
| GET    | `/`                               | Dashboard (VM table + CRUD)  |
| POST   | `/vms/add`                        | Create VM                    |
| POST   | `/vms/<id>/edit`                  | Update VM                    |
| POST   | `/vms/<id>/deactivate`            | Mark VM inactive             |
| POST   | `/vms/<id>/delete`                | Hard delete VM               |
| GET    | `/vms/<id>/json`                  | Get VM as JSON (for modals)  |
| GET    | `/export/vms`                     | Export VM list as CSV        |
| GET    | `/reports/`                       | Reports page                 |
| GET    | `/reports/expiring?days=N`        | VMs expiring in N days       |
| GET    | `/reports/cost-by-provider`       | Cost by cloud provider       |
| GET    | `/reports/usage-by-team`          | VM count + cost per team     |
| GET    | `/reports/trends`                 | 12-month trend data          |
| GET    | `/reports/export/expiring`        | CSV: expiring VMs            |
| GET    | `/reports/export/cost-by-provider`| CSV: cost by provider        |
| GET    | `/reports/export/usage-by-team`   | CSV: team usage              |
| POST   | `/login`                          | Login                        |
| GET    | `/logout`                         | Logout                       |

---

## Deploy to Render (free tier)

1. Push repo to GitHub
2. Go to https://render.com → **New Web Service**
3. Connect your repo
4. Settings:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn run:app`
5. Add Environment Variables:
   - `MONGO_URI` = your Atlas URI
   - `SECRET_KEY` = your secret key
   - `DB_NAME` = `vmmanager`
6. Deploy — Render gives you a free `*.onrender.com` URL
7. Run `python seed.py` once locally (it connects to Atlas directly) to seed data

---

## Default Login

| Field    | Value     |
|----------|-----------|
| Username | `admin`   |
| Password | `admin123`|

**Change the password after first login** (via MongoDB Atlas or add a change-password route in v2).
