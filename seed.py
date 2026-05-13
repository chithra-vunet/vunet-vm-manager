#!/usr/bin/env python3
"""
Seed the database with an admin user and sample VMs.
Run once: python seed.py
Safe to re-run — skips existing records.
"""
from datetime import datetime, timedelta
import sys
import os

# ── Bootstrap Flask app so models can reach MongoDB ───────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from app import create_app
app = create_app()

with app.app_context():
    import app as _app
    db = _app.db

    # ── Admin user ─────────────────────────────────────────────────────────────
    if db.users.find_one({"username": "admin"}):
        print("Admin user already exists — skipping.")
    else:
        import bcrypt
        pw_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt())
        db.users.insert_one({
            "username":      "admin",
            "password_hash": pw_hash,
            "role":          "admin",
            "created_at":    datetime.utcnow(),
        })
        print("Created admin user  →  username: admin | password: admin123")

    # ── Sample VMs ─────────────────────────────────────────────────────────────
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    sample_vms = [
        # Normal active VMs
        {
            "cloud_provider": "Azure-Billed",
            "vm_name": "prod-api-01",
            "ip_address": "10.0.1.10",
            "requested_by": "Ravi Kumar",
            "team_name": "Platform Engineering",
            "start_date": today - timedelta(days=180),
            "planned_end_date": today + timedelta(days=90),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 12.50,
            "tags": ["prod"],
        },
        {
            "cloud_provider": "Azure-Billed",
            "vm_name": "prod-api-02",
            "ip_address": "10.0.1.11",
            "requested_by": "Ravi Kumar",
            "team_name": "Platform Engineering",
            "start_date": today - timedelta(days=150),
            "planned_end_date": today + timedelta(days=75),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 12.50,
            "tags": ["prod"],
        },
        {
            "cloud_provider": "AWS",
            "vm_name": "data-pipeline-01",
            "ip_address": "172.16.0.5",
            "requested_by": "Priya Sharma",
            "team_name": "Data Engineering",
            "start_date": today - timedelta(days=60),
            "planned_end_date": today + timedelta(days=120),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 8.75,
            "tags": ["prod", "dev"],
        },
        {
            "cloud_provider": "GCP",
            "vm_name": "ml-training-01",
            "ip_address": "192.168.10.20",
            "requested_by": "Anil Mehta",
            "team_name": "AI/ML",
            "start_date": today - timedelta(days=30),
            "planned_end_date": today + timedelta(days=60),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 25.00,
            "tags": ["dev"],
        },
        {
            "cloud_provider": "Azure-FreeCredits",
            "vm_name": "dev-sandbox-01",
            "ip_address": "10.1.0.50",
            "requested_by": "Sneha Nair",
            "team_name": "Platform Engineering",
            "start_date": today - timedelta(days=20),
            "planned_end_date": today + timedelta(days=40),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 0.00,
            "tags": ["dev"],
        },
        # Expiring soon (within 7 days)
        {
            "cloud_provider": "E2E",
            "vm_name": "staging-web-01",
            "ip_address": "10.2.0.10",
            "requested_by": "Kiran Rao",
            "team_name": "QA",
            "start_date": today - timedelta(days=90),
            "planned_end_date": today + timedelta(days=5),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 3.20,
            "tags": ["staging"],
        },
        {
            "cloud_provider": "AWS",
            "vm_name": "test-db-replica",
            "ip_address": "172.16.0.20",
            "requested_by": "Deepak Singh",
            "team_name": "QA",
            "start_date": today - timedelta(days=45),
            "planned_end_date": today + timedelta(days=3),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 5.50,
            "tags": ["test"],
        },
        # Overdue
        {
            "cloud_provider": "C4I",
            "vm_name": "legacy-app-server",
            "ip_address": "10.5.0.99",
            "requested_by": "Mohan Das",
            "team_name": "Backend",
            "start_date": today - timedelta(days=200),
            "planned_end_date": today - timedelta(days=15),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 6.00,
            "tags": ["prod"],
        },
        {
            "cloud_provider": "Tower",
            "vm_name": "reporting-old-01",
            "ip_address": "10.9.0.5",
            "requested_by": "Lakshmi Iyer",
            "team_name": "Data Engineering",
            "start_date": today - timedelta(days=300),
            "planned_end_date": today - timedelta(days=30),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 4.00,
            "tags": ["prod"],
        },
        # Inactive
        {
            "cloud_provider": "GCP",
            "vm_name": "poc-nlp-server",
            "ip_address": "192.168.20.1",
            "requested_by": "Anil Mehta",
            "team_name": "AI/ML",
            "start_date": today - timedelta(days=120),
            "planned_end_date": today - timedelta(days=60),
            "status": "Inactive",
            "deleted_date": today - timedelta(days=60),
            "daily_cost": 18.00,
            "tags": ["dev"],
        },
        {
            "cloud_provider": "Azure-Billed",
            "vm_name": "old-ci-runner",
            "ip_address": "10.0.2.30",
            "requested_by": "Ravi Kumar",
            "team_name": "Platform Engineering",
            "start_date": today - timedelta(days=365),
            "planned_end_date": today - timedelta(days=90),
            "status": "Inactive",
            "deleted_date": today - timedelta(days=90),
            "daily_cost": 7.25,
            "tags": ["dev", "staging"],
        },
        # More active VMs for different teams
        {
            "cloud_provider": "AWS",
            "vm_name": "backend-api-prod",
            "ip_address": "172.16.1.5",
            "requested_by": "Mohan Das",
            "team_name": "Backend",
            "start_date": today - timedelta(days=100),
            "planned_end_date": today + timedelta(days=200),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 15.00,
            "tags": ["prod"],
        },
        {
            "cloud_provider": "E2E",
            "vm_name": "frontend-staging",
            "ip_address": "10.2.0.25",
            "requested_by": "Sneha Nair",
            "team_name": "Frontend",
            "start_date": today - timedelta(days=15),
            "planned_end_date": today + timedelta(days=30),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 2.00,
            "tags": ["staging"],
        },
        {
            "cloud_provider": "Azure-FreeCredits",
            "vm_name": "dev-test-env-01",
            "ip_address": "10.1.0.60",
            "requested_by": "Deepak Singh",
            "team_name": "QA",
            "start_date": today - timedelta(days=10),
            "planned_end_date": today + timedelta(days=20),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 0.00,
            "tags": ["test", "dev"],
        },
        {
            "cloud_provider": "C4I",
            "vm_name": "infra-monitor-01",
            "ip_address": "10.5.0.10",
            "requested_by": "Lakshmi Iyer",
            "team_name": "DevOps",
            "start_date": today - timedelta(days=250),
            "planned_end_date": today + timedelta(days=115),
            "status": "Active",
            "deleted_date": None,
            "daily_cost": 4.50,
            "tags": ["prod"],
        },
    ]

    inserted = 0
    skipped  = 0
    now = datetime.utcnow()

    for vm in sample_vms:
        if db.vms.find_one({"vm_name": vm["vm_name"]}):
            skipped += 1
            continue
        vm["created_at"] = now
        vm["updated_at"] = now
        db.vms.insert_one(vm)
        inserted += 1

    print(f"VMs: {inserted} inserted, {skipped} skipped (already existed).")
    print("\nDone! Run the app with:  python run.py")
    print("Login at http://localhost:5000/login  →  admin / admin123")
