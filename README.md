Distributed Parking Management System

A distributed, real-time parking management system designed for multi-gate parking facilities, following an offline-first architecture to ensure continuous operation at gate nodes even when the central cloud service is unavailable.

1. Overview

This project implements a fault-tolerant parking system with multiple gate nodes connected to a central cloud, focusing on high availability at gate level - strong consistency for slot state - real-time synchronization - safe recovery from network failures - clear separation between Gate Node and Cloud responsibilities.

2. Architecture

The system is composed of Gate Nodes and a Cloud Server communicating via REST and WebSocket, where each Gate Node operates independently using a local database while synchronizing state with the Cloud Server when available.

3. Core Components
3.1 Gate Node

Each gate node is a self-contained execution unit responsible for vehicle entry and exit processing - license plate recognition using camera and OCR - slot suggestion based on distance calculation - offline operation using local SQLite storage - forwarding events to the Cloud when connectivity is restored.

Technologies used in the Gate Node include Python and Tkinter for UI - OpenCV, YOLO and EasyOCR for vision processing - FastAPI for the local API - SQLite for offline persistence - WebSocket client for real-time synchronization.

3.2 Cloud Server

The Cloud Server acts as the system authority responsible for central slot and vehicle state management - conflict detection and resolution - transaction and fee calculation - real-time broadcast to all connected gates - admin management and reporting services.

Technologies used in the Cloud Server include FastAPI for REST APIs - PostgreSQL for persistent storage - Redis for TTL-based coordination and Pub/Sub - WebSocket for real-time communication.

4. Distributed System Design
4.1 Offline-First Strategy

Gate Nodes remain fully operational without cloud connectivity by relying on a local SQLite database to store slot state and pending events, which are automatically synchronized with the Cloud when connectivity is restored.

4.2 Slot Coordination Using Redis TTL

Slot conflicts between multiple gates are prevented using Redis TTL-based reservations instead of database locking, providing non-blocking coordination - automatic expiration - safe concurrent access across distributed nodes.

4.3 Real-Time Synchronization

The system uses WebSocket instead of polling to deliver real-time slot updates - vehicle events - heartbeat signals - round-trip time measurement for network health monitoring.

4.4 Idempotency and Deduplication

All critical operations support optional event identifiers, with processed events stored centrally to ensure idempotent behavior and safely ignore duplicated or retried requests.

5. Data Storage

The Cloud database uses PostgreSQL to store slots - vehicles - transactions - payments - processed events - gates - users, while each Gate Node maintains a local SQLite database for local slot cache - offline event queue - temporary vehicle records.

6. Security

The system applies token-based authentication using Bearer tokens - role-based access control for Admin and Guard roles - Cloud-side protection for admin-only APIs - gate identity validation during login and WebSocket connection.

7. Payment Support

The system supports multiple payment methods including VietQR-based bank transfer - cash payment - manual online confirmation, with payment status tracked and linked to parking transactions.

8. User Interfaces

The Gate Interface provides a real-time slot map - vehicle IN and OUT operations - cloud connectivity and RTT indicators, while the Security Control Interface offers live camera feeds - OCR-assisted processing - dual IN and OUT control panels, and the Admin Dashboard delivers gate monitoring - slot management - transaction history - revenue statistics - PDF report export.

9. Technology Stack

UI uses Tkinter - backend services use FastAPI - real-time communication is implemented with WebSocket - OCR relies on YOLO and EasyOCR - databases include PostgreSQL and SQLite - Redis is used for coordination - OpenCV and Pillow handle imaging - ReportLab and Matplotlib support reporting and visualization.

10. Running the System

The Cloud Server can be started using Docker Compose, while each Gate Node is initialized by creating the local database and launching the gate UI application.

11. Testing Scope

Testing covers unit tests for fee calculation and validation - integration tests between Gate Nodes and the Cloud Server - offline and reconnect scenarios - concurrent slot reservation handling - event deduplication and retry behavior.

12. Future Work

Planned improvements include enhanced OCR accuracy - mobile admin applications - automated payment confirmation - horizontal scaling for cloud services - support for multi-site and multi-tenant deployments.

13. License

This project is intended for educational and demonstration purposes.
