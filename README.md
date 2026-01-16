🚗 Distributed Parking Management System

A distributed, real-time, fault-tolerant parking management system designed for multi-gate environments.
The system continues operating even when the cloud is unavailable, and automatically syncs when connectivity is restored.

✨ Key Features

✅ Distributed architecture (Gate Nodes + Cloud)

✅ Real-time updates via WebSocket

✅ Offline-first Gate Nodes with local database

✅ OCR License Plate Recognition (YOLO + EasyOCR)

✅ Slot coordination using Redis TTL (no DB locking)

✅ Idempotent APIs with event deduplication

✅ Admin Dashboard & Security Control UI

✅ Payment support (VietQR / Cash / Manual)

✅ Reporting & PDF export

✅ Scalable for multiple gates

🧠 System Architecture
+-------------------+        WebSocket        +----------------------+
|   Gate Node UI    | <--------------------> |      Cloud API       |
| (Tkinter + YOLO)  |                        | (FastAPI + WS)       |
+---------+---------+                        +----------+-----------+
          |                                                  |
          | REST (Local API)                                 | PostgreSQL
          |                                                  |
+---------v---------+                        +----------v-----------+
| Local Gate API    |                        |        Redis         |
| (FastAPI)         |                        | (TTL / PubSub)       |
+-------------------+                        +----------------------+
          |
          | SQLite (offline cache + queue)
          v
   Local Gate DB

🧩 Components Overview
1️⃣ Gate Node

Tkinter GUI (Gate UI & Security UI)

Camera input (OpenCV)

License plate recognition (YOLO + EasyOCR)

Local FastAPI server

SQLite database for offline mode

WebSocket client to Cloud

Responsibilities

Vehicle IN / OUT

Slot suggestion (distance-based)

Offline queue when Cloud is down

Best-effort image upload

Local-first operations

2️⃣ Cloud Server

FastAPI REST API

WebSocket server (real-time broadcast)

PostgreSQL (main database)

Redis (coordination + Pub/Sub)

Responsibilities

Central state management

Slot coordination (TTL-based reserve)

Conflict detection

Transaction processing

Fee calculation

Reporting & admin management

🔄 Distributed Design Highlights
🔹 Offline-first

Gate continues working when Cloud is offline

Uses SQLite for local slot state & event queue

Syncs automatically when Cloud reconnects

🔹 Redis TTL instead of DB Lock

Slot reservation via SETEX reserve:{slot}

Prevents race conditions between gates

No blocking database locks

🔹 WebSocket instead of Polling

Real-time slot updates

Heartbeat & RTT measurement

Instant UI refresh across all gates

🔹 Idempotency & Deduplication

Every event supports event_id

processed_events table prevents double processing

Safe retries after network failures

💾 Databases
Cloud

PostgreSQL

slots

vehicles

transactions

payments

processed_events

gates

users

Gate Node

SQLite

local_slots

local_event_queue

local_vehicles

🔐 Security

Bearer Token authentication

Admin-only APIs protected

Gate authentication via Cloud login

WebSocket gate identity verification

💳 Payment Methods

VietQR (QR code generation)

Cash payment

Manual online transfer

Payment status tracking

📊 Admin Dashboard

Real-time slot status

Gate online/offline monitoring

Transaction history

Revenue statistics

PDF report export

Slot CRUD management

🖥️ User Interfaces

Gate Main UI

Slot map (real-time)

Vehicle IN / OUT

Cloud status & RTT

Security Control Room

Live camera view

Dual IN / OUT panels

OCR-assisted operations

Admin Dashboard

Analytics & reports

Slot & gate management

🛠️ Tech Stack
Layer	Technology
UI	Tkinter
Backend	FastAPI
Realtime	WebSocket
OCR	YOLO + EasyOCR
Database	PostgreSQL, SQLite
Cache / Lock	Redis
Image	OpenCV, Pillow
Payment	VietQR
Reporting	ReportLab
Charts	Matplotlib
🚀 How to Run (Simplified)
Cloud
docker-compose up

Gate Node
python init_local_db.py
python gui_gate.py

🧪 Testing Scope

Unit tests (fee calculation, validation)

Integration tests (Gate ↔ Cloud)

Offline simulation

Realtime sync & conflict tests

Deduplication & retry tests

📈 Future Improvements

License plate accuracy optimization

Mobile app for admin

Auto payment confirmation

Horizontal scaling for Cloud

Multi-tenant parking support

📜 License

This project is for educational & demonstration purposes.
Feel free to fork, study, and extend.
