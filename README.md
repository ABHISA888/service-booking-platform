# Service Booking and Review Platform API

## Overview
A backend RESTful API built with **FastAPI** for managing service time slot bookings, provider-customer interactions, and review summarisation.

## Current Implementation Scope (Phase 1 — Project Foundation)
- Initial FastAPI application structure.
- Application configuration management using Pydantic `BaseSettings`.
- Operational `/health` check endpoint.
- Ruff code linting and Pytest unit test setup.

---

## Getting Started

### 1. Prerequisites
- Python 3.12+

### 2. Environment Setup & Installation
Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create environment configuration file from template:

```bash
cp .env.example .env
```

### 3. Starting Development Server
Run the FastAPI development server with Uvicorn:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Health Check Endpoint**: `http://localhost:8000/health`
- **Interactive OpenAPI Documentation**: `http://localhost:8000/docs`

### 4. Running Validation & Tests

```bash
# Run Ruff Linter
ruff check .

# Run Pytest Suite
pytest -v
```
