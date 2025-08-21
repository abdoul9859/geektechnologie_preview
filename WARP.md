# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

GEEK TECHNOLOGIE is a comprehensive inventory management and billing application developed with **FastAPI** and **Bootstrap 5**. It's a French-language system specifically designed for technology product management (smartphones, laptops, tablets) with advanced features like product variants, IMEI/serial number tracking, and complete billing workflow.

## Architecture

### Backend Structure
- **FastAPI** application with SQLAlchemy ORM
- **PostgreSQL** (production) / **SQLite** (development) database
- **JWT** authentication with role-based access control
- **Modular router architecture** with API endpoints under `/api/`
- **Jinja2 templates** for server-side rendering

### Key Components
- `main.py` - Main FastAPI application with route definitions
- `start.py` - Application startup script with configuration
- `app/database.py` - SQLAlchemy models and database configuration
- `app/auth.py` - JWT authentication and authorization
- `app/routers/` - API route modules (products, clients, invoices, etc.)
- `app/schemas.py` - Pydantic models for request/response validation
- `app/init_db.py` - Database initialization and seeding
- `templates/` - HTML templates (Jinja2)
- `static/` - CSS, JavaScript, and asset files

### Core Business Logic
The system implements advanced product management with:
- **Product variants** with IMEI/serial tracking
- **Smart barcode system** - main products with variants don't have barcodes, individual variants do
- **Condition tracking** (neuf/occasion/venant) at both product and variant levels
- **Complete billing workflow** (quotations → invoices → delivery notes → payments)

## Development Commands

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables (edit .env file)
# Default development database: PostgreSQL localhost
# Default users: admin/admin123, user/user123
```

### Running the Application
```bash
# Development server (with auto-reload)
python start.py

# Direct uvicorn (alternative)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Database Management
```bash
# Initialize/recreate database with default data
# Set INIT_DB_ON_STARTUP=true and SEED_DEFAULT_DATA=true in .env
python start.py

# Manual database initialization
python -c "from app.init_db import init_database; init_database()"
```

### Docker Deployment
```bash
# Build image
docker build -t geektechnologie .

# Run container
docker run -p 8000:8000 geektechnologie
```

## API Architecture

### Authentication
- JWT tokens with configurable expiration (default: 24 hours)
- Role-based access: `admin`, `manager`, `user`
- Cookie-based authentication (`gt_access` HttpOnly cookie)
- Optional JWT claims trust mode (`AUTH_TRUST_JWT_CLAIMS=true`)

### Core API Modules
- `/api/auth` - Authentication (login, verify, logout)
- `/api/products` - Product and variant management
- `/api/clients` - Customer management
- `/api/stock-movements` - Inventory tracking
- `/api/invoices` - Invoice management with payments
- `/api/quotations` - Quote management and conversion
- `/api/suppliers` - Supplier management
- `/api/delivery-notes` - Delivery tracking
- `/api/bank-transactions` - Financial transactions
- `/api/reports` - Business reporting
- `/api/migrations` - Data migration tools

### Key Business Rules

#### Product Variants System
- Products with `requires_variants=True` cannot have direct barcodes
- Individual variants have unique IMEI/serial numbers and optional barcodes
- Product quantities calculated from variant count
- Supports configurable attributes (color, storage, etc.)

#### Stock Management
- All movements tracked in `stock_movements` table
- Automatic audit logging on deletions
- Real-time statistics and reporting
- Support for IMEI/serial number lookup

#### Billing Workflow
1. **Quotations** → Convert to invoices
2. **Invoices** → Track payments and generate delivery notes  
3. **Delivery Notes** → Track product delivery with signatures
4. **Payments** → Multiple payment methods and installments

## Database Schema

### Key Tables
- `users` - User authentication and roles
- `clients` - Customer information
- `products` - Main product catalog
- `product_variants` - Product variants with IMEI/serials
- `product_variant_attributes` - Dynamic variant attributes
- `stock_movements` - All inventory movements
- `quotations` / `quotation_items` - Sales quotes
- `invoices` / `invoice_items` / `invoice_payments` - Billing
- `delivery_notes` / `delivery_note_items` - Delivery tracking
- `bank_transactions` - Financial operations

### Database Configuration
- **Development**: PostgreSQL localhost (fallback SQLite)
- **Production**: PostgreSQL with connection pooling
- **Environment**: Configure via `DATABASE_URL` and `DB_*` variables
- **Migrations**: Manual schema updates via init_db.py

## Frontend Architecture

### Technology Stack  
- **Bootstrap 5** with custom CSS styling
- **Vanilla JavaScript** (ES6+) with modular organization
- **Server-side rendering** with Jinja2 templates
- **Responsive design** optimized for desktop/tablet/mobile

### Key Features
- Real-time barcode scanning interface
- Dynamic product variant management
- Invoice/quotation printing with company branding
- Advanced search and filtering
- Role-based UI element visibility

## Configuration

### Environment Variables
Key variables in `.env`:
- `DATABASE_URL` - Database connection string
- `SECRET_KEY` - JWT signing key (change in production)
- `ACCESS_TOKEN_EXPIRE_MINUTES` - Token expiration
- `AUTH_TRUST_JWT_CLAIMS` - Skip DB lookups for auth
- `INIT_DB_ON_STARTUP` - Auto-initialize database
- `SEED_DEFAULT_DATA` - Create default users/categories

### Application Settings
- User settings stored in `user_settings` table
- Company information for invoices/quotes
- Configurable product conditions (neuf/occasion/venant)
- Customizable category attributes

## Testing and Development

### Default Accounts
- **Administrator**: `admin` / `admin123`
- **Standard User**: `user` / `user123`

### Development Features
- Hot reload enabled in development mode
- Comprehensive error handling and logging
- Data seeding for testing (large datasets available)
- Migration tools for data import/export

## Deployment Platforms

### Supported Platforms
- **Koyeb** (koyeb.yaml configuration)
- **Vercel** (vercel.json configuration) 
- **Heroku** (Procfile configuration)
- **Docker** (Dockerfile included)

### Production Considerations
- Set `RELOAD=false` for production
- Use PostgreSQL instead of SQLite
- Configure proper SSL settings
- Set secure JWT secret key
- Enable connection pooling for high traffic

## Business Domain Notes

This is a French-language application designed for West African markets (specifically Senegal), with:
- CFA franc currency formatting
- French date formats (YYYY-MM-DD)
- Senegalese business compliance (RC, NINEA numbers)
- Local business practices (cash, mobile money, bank transfers)

The system handles complex inventory scenarios common in technology retail:
- Product variants with unique identifiers (IMEI, serial numbers)
- Condition tracking (new, used, refurbished)
- Complete audit trail for regulatory compliance
- Multi-stage billing workflow with payment tracking
