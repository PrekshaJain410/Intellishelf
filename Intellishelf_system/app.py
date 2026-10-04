from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
from functools import wraps
import json
import os,re
import csv
import io
from flask import make_response
from sqlalchemy import func, extract

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:prank%4041005%25@localhost/inventory_system'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

# Password reset config
app.config['RESET_TOKEN_MAX_AGE'] = 3600  # 1 hour

# Email — set MAIL_ENABLED = True and fill SMTP creds to send real emails
app.config['MAIL_ENABLED'] = False
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@intellishelf.com')

mail = None
if app.config['MAIL_ENABLED']:
    try:
        from flask_mail import Mail
        mail = Mail(app)
    except ImportError:
        print("⚠️  Flask-Mail not installed. Falling back to console mode.")
        app.config['MAIL_ENABLED'] = False

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


# ============================================================
# DECORATORS
# ============================================================

def admin_required(f):
    """Restrict access to admin users only"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        if current_user.role != 'admin':
            flash('Access denied. Administrator privileges required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def non_admin_required(f):
    """Block admin from business pages (admin has no inventory)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        if current_user.role == 'admin':
            flash('Administrators manage users only. You do not have an inventory.', 'info')
            return redirect(url_for('user_management'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================================
# VALIDATION HELPERS
# ============================================================


def validate_product(data, owner_id, existing_id=None):
    """
    Validate product payload.
    Returns (is_valid: bool, error_message: str|None)
    """
    errors = []
    
    # --- Name ---
    name = (data.get('name') or '').strip()
    if not name:
        errors.append('Product name is required.')
    elif len(name) > 100:
        errors.append('Product name must be under 100 characters.')
    
    # --- Category ---
    category = (data.get('category') or '').strip()
    if not category:
        errors.append('Category is required.')
    elif len(category) > 50:
        errors.append('Category must be under 50 characters.')
    
    # --- Prices ---
    try:
        purchase_price = float(data.get('purchase_price', 0))
        if purchase_price <= 0:
            errors.append('Purchase price must be greater than 0.')
        elif purchase_price > 10_000_000:
            errors.append('Purchase price is too high.')
    except (ValueError, TypeError):
        errors.append('Purchase price must be a valid number.')
    
    try:
        selling_price = float(data.get('selling_price', 0))
        if selling_price <= 0:
            errors.append('Selling price must be greater than 0.')
        elif selling_price > 10_000_000:
            errors.append('Selling price is too high.')
    except (ValueError, TypeError):
        errors.append('Selling price must be a valid number.')
    
    # --- Quantity ---
    try:
        quantity = int(data.get('quantity', 0))
        if quantity < 0:
            errors.append('Quantity cannot be negative.')
        elif quantity > 1_000_000:
            errors.append('Quantity is unrealistically high.')
    except (ValueError, TypeError):
        errors.append('Quantity must be a whole number.')
    
    # --- Min stock ---
    try:
        min_stock = int(data.get('min_stock', 5))
        if min_stock < 0:
            errors.append('Minimum stock cannot be negative.')
        elif min_stock > 1_000_000:
            errors.append('Minimum stock is unrealistically high.')
    except (ValueError, TypeError):
        errors.append('Minimum stock must be a whole number.')
    
    # --- Description ---
    description = (data.get('description') or '').strip()
    if len(description) > 2000:
        errors.append('Description must be under 2000 characters.')
    
    # --- Supplier ownership ---
    supplier_id = data.get('supplier_id')
    if supplier_id:
        try:
            supplier_id_int = int(supplier_id)
            supplier = Supplier.query.filter_by(
                id=supplier_id_int, owner_id=owner_id
            ).first()
            if not supplier:
                errors.append('Selected supplier does not exist or belongs to another account.')
        except (ValueError, TypeError):
            errors.append('Invalid supplier.')
    
    # --- Duplicate name ---
    if name and not errors:
        dup_query = Product.query.filter(
            Product.owner_id == owner_id,
            db.func.lower(Product.name) == name.lower()
        )
        if existing_id:
            dup_query = dup_query.filter(Product.id != existing_id)
        if dup_query.first():
            errors.append(f'A product named "{name}" already exists in your inventory.')
    
    if errors:
        return False, ' '.join(errors)
    return True, None


def validate_supplier(data):
    """Validate supplier payload. Returns (is_valid, error_message)."""
    errors = []
    
    name = (data.get('name') or '').strip()
    if not name:
        errors.append('Contact name is required.')
    elif len(name) > 100:
        errors.append('Contact name must be under 100 characters.')
    
    company = (data.get('company') or '').strip()
    if not company:
        errors.append('Company name is required.')
    elif len(company) > 100:
        errors.append('Company name must be under 100 characters.')
    
    email = (data.get('email') or '').strip()
    if email:
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            errors.append('Email address is not valid.')
        elif len(email) > 100:
            errors.append('Email must be under 100 characters.')
    
    phone = (data.get('phone') or '').strip()
    if phone:
        if not re.match(r'^[\d\s\+\-\(\)]{5,20}$', phone):
            errors.append('Phone number is not valid.')
    
    address = (data.get('address') or '').strip()
    if len(address) > 500:
        errors.append('Address must be under 500 characters.')
    
    if errors:
        return False, ' '.join(errors)
    return True, None


def validate_sale_items(cart_items, owner_id):
    """
    Validate sale cart items. Returns (is_valid, error_message).
    """
    if not cart_items or not isinstance(cart_items, list):
        return False, 'Cart is empty.'
    
    if len(cart_items) > 100:
        return False, 'Too many items in one sale (max 100).'
    
    for i, item in enumerate(cart_items, 1):
        if not item.get('id'):
            return False, f'Item #{i}: missing product ID.'
        
        try:
            qty = int(item.get('qty', 0))
            if qty <= 0:
                return False, f'Item #{i}: quantity must be greater than 0.'
            if qty > 100_000:
                return False, f'Item #{i}: quantity is unrealistically high.'
        except (ValueError, TypeError):
            return False, f'Item #{i}: quantity must be a whole number.'
        
        product = Product.query.filter_by(
            id=item['id'], owner_id=owner_id
        ).first()
        if not product:
            return False, f'Item #{i}: product not found.'
        if product.is_discontinued:
            return False, f'"{product.name}" has been discontinued and cannot be sold.'
        if product.quantity < qty:
            return False, f'Only {product.quantity} units of {product.name} available.'
    
    return True, None

# ============================================================
# MODELS
# ============================================================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    company_name = db.Column(db.String(150), nullable=False, default='My Business')
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), default='user')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    products = db.relationship('Product', backref='owner', lazy=True, cascade='all, delete-orphan')
    suppliers = db.relationship('Supplier', backref='owner', lazy=True, cascade='all, delete-orphan')
    purchases = db.relationship('Purchase', backref='owner', lazy=True, cascade='all, delete-orphan')
    sales = db.relationship('Sale', backref='owner', lazy=True, cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='owner', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password = password
    
    def check_password(self, password):
        return self.password == password
    
    def get_role_display(self):
        roles = {
            'admin': 'Administrator',
            'user': 'User',
        }
        return roles.get(self.role, self.role)


class Supplier(db.Model):
    __tablename__ = 'suppliers'
    
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    company = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_discontinued = db.Column(db.Boolean, default=False, index=True)
    discontinued_at = db.Column(db.DateTime, nullable=True)

    products = db.relationship('Product', backref='supplier_rel', lazy=True, foreign_keys='Product.supplier_id')


class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    purchase_price = db.Column(db.Numeric(10, 2), nullable=False)
    selling_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=5)
    status = db.Column(db.Enum('In Stock', 'Low Stock', 'Out of Stock'), default='In Stock')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    is_discontinued = db.Column(db.Boolean, default=False, index=True)
    discontinued_at = db.Column(db.DateTime, nullable=True)
    
    def update_status(self):
        if self.quantity <= 0:
            self.status = 'Out of Stock'
        elif self.quantity < self.min_stock:
            self.status = 'Low Stock'
        else:
            self.status = 'In Stock'
    
    def discontinue(self):
        self.is_discontinued = True
        self.discontinued_at = datetime.utcnow()
    
    def restore(self):
        self.is_discontinued = False
        self.discontinued_at = None


class Purchase(db.Model):
    __tablename__ = 'purchases'
    
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    purchase_date = db.Column(db.Date, nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.Enum('Pending', 'Received', 'Cancelled'), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    supplier = db.relationship('Supplier', backref='purchases')
    items = db.relationship('PurchaseItem', backref='purchase', lazy=True, cascade='all, delete-orphan')


class PurchaseItem(db.Model):
    __tablename__ = 'purchase_items'
    
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    purchase_price = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    
    product = db.relationship('Product', backref='purchase_items')


class Sale(db.Model):
    __tablename__ = 'sales'
    
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    customer_name = db.Column(db.String(100))
    sale_date = db.Column(db.Date, nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    items = db.relationship('SaleItem', backref='sale', lazy=True, cascade='all, delete-orphan')


class SaleItem(db.Model):
    __tablename__ = 'sale_items'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    selling_price = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    
    product = db.relationship('Product', backref='sale_items')


class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    type = db.Column(db.Enum('Low Stock', 'Reorder', 'Forecast', 'System'), default='System')
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# USER LOADER
# ============================================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ============================================================
# AUTH ROUTES
# ============================================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated. Please contact administrator.', 'danger')
                return render_template('login.html')
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        company_name = request.form.get('company_name', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not first_name or not last_name or not email or not company_name or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please login.', 'danger')
            return render_template('register.html')
        
        full_name = f"{first_name} {last_name}".strip()
        
        user = User(
            full_name=full_name,
            company_name=company_name,
            email=email,
            role='user',
            is_active=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash(f'Welcome, {first_name}! Your workspace for {company_name} is ready. Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ============================================================
# PASSWORD RESET (Forgot Password)
# ============================================================

def _get_reset_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt='password-reset-salt')


def generate_reset_token(user):
    return _get_reset_serializer().dumps({'uid': user.id, 'email': user.email})


def verify_reset_token(token, max_age=3600):
    """Returns (user, None) on success, or (None, 'expired'|'invalid')."""
    try:
        data = _get_reset_serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        return None, 'expired'
    except BadSignature:
        return None, 'invalid'

    user = User.query.get(data.get('uid'))
    if not user or user.email != data.get('email'):
        return None, 'invalid'
    return user, None


def send_reset_email(user, reset_url):
    """Send real email if enabled, otherwise print to console."""
    if app.config['MAIL_ENABLED'] and mail is not None:
        try:
            from flask_mail import Message
            msg = Message(
                subject='IntelliShelf — Password Reset Request',
                recipients=[user.email],
                html=f"""
                <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;
                            padding:32px;background:#F4F6F1;border-radius:16px;
                            border:1px solid #A3B597;color:#3B4938;">
                    <h2 style="color:#3B4938;">Password Reset</h2>
                    <p style="color:#616C5E;line-height:1.6;">
                        Hi {user.full_name},<br><br>
                        Click below to reset your IntelliShelf password.
                        This link expires in <strong>1 hour</strong>.
                    </p>
                    <p style="text-align:center;margin:32px 0;">
                        <a href="{reset_url}"
                           style="background:#3B4938;color:#F4F6F1;text-decoration:none;
                                  padding:14px 32px;border-radius:10px;font-weight:700;">
                            Reset My Password
                        </a>
                    </p>
                    <p style="color:#8a9a85;font-size:12px;">
                        If you didn't request this, ignore this email.
                    </p>
                </div>
                """
            )
            mail.send(msg)
            print(f"✅ Reset email sent to {user.email}")
            return True
        except Exception as e:
            print(f"❌ Email failed: {e}")
            return False
    else:
        # DEV MODE — print to terminal
        print("\n" + "=" * 70)
        print("🔐  PASSWORD RESET LINK (DEV MODE)")
        print("=" * 70)
        print(f"  User : {user.full_name} <{user.email}>")
        print(f"  Link : {reset_url}")
        print(f"  Valid: 1 hour")
        print("=" * 70 + "\n")
        return True


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()

        if not email:
            flash('Please enter your email address.', 'danger')
            return render_template('forgot_password.html')

        user = User.query.filter(db.func.lower(User.email) == email).first()

        # Same message always (prevents email enumeration)
        generic = ('If an account exists for that email, a password reset link '
                   'has been sent. Please check your inbox.')

        if user:
            if not user.is_active:
                flash('This account has been deactivated. Please contact the administrator.', 'danger')
                return render_template('forgot_password.html')

            token = generate_reset_token(user)
            reset_url = url_for('reset_password', token=token, _external=True)
            send_reset_email(user, reset_url)

        flash(generic, 'info')
        return redirect(url_for('login'))

    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    user, err = verify_reset_token(token, app.config.get('RESET_TOKEN_MAX_AGE', 3600))

    if err == 'expired':
        flash('That reset link has expired. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))
    if err or user is None:
        flash('That reset link is invalid or has already been used.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_pwd = request.form.get('password') or ''
        confirm_pwd = request.form.get('confirm_password') or ''

        if len(new_pwd) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('reset_password.html', token=token, email=user.email)
        if new_pwd != confirm_pwd:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token, email=user.email)

        user.set_password(new_pwd)
        db.session.commit()
        flash('Your password has been reset successfully. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token, email=user.email)



# ============================================================
# PROFILE ROUTES
# ============================================================

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')


@app.route('/api/profile', methods=['PUT'])
@login_required
def api_update_profile():
    """Update current user's profile information."""
    try:
        data = request.get_json()
        errors = []

        first_name = (data.get('first_name') or '').strip()
        last_name = (data.get('last_name') or '').strip()
        email = (data.get('email') or '').strip()
        company_name = (data.get('company_name') or '').strip()

        if not first_name:
            errors.append('First name is required.')
        elif len(first_name) > 50:
            errors.append('First name must be under 50 characters.')

        if not last_name:
            errors.append('Last name is required.')
        elif len(last_name) > 50:
            errors.append('Last name must be under 50 characters.')

        if not email:
            errors.append('Email is required.')
        elif not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            errors.append('Email address is not valid.')
        elif len(email) > 100:
            errors.append('Email must be under 100 characters.')

        if not company_name:
            errors.append('Company name is required.')
        elif len(company_name) > 150:
            errors.append('Company name must be under 150 characters.')

        # Email uniqueness check (excluding self)
        if email and not errors:
            existing = User.query.filter(
                User.email == email,
                User.id != current_user.id
            ).first()
            if existing:
                errors.append('That email is already registered to another account.')

        if errors:
            return jsonify({'success': False, 'message': ' '.join(errors)}), 400

        current_user.full_name = f"{first_name} {last_name}".strip()
        current_user.email = email
        current_user.company_name = company_name

        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Profile updated successfully.',
            'user': {
                'full_name': current_user.full_name,
                'email': current_user.email,
                'company_name': current_user.company_name,
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/profile/password', methods=['PUT'])
@login_required
def api_update_password():
    """Update current user's password."""
    try:
        data = request.get_json()
        current_pwd = data.get('current_password') or ''
        new_pwd = data.get('new_password') or ''
        confirm_pwd = data.get('confirm_password') or ''

        if not current_pwd:
            return jsonify({'success': False, 'message': 'Current password is required.'}), 400
        if not current_user.check_password(current_pwd):
            return jsonify({'success': False, 'message': 'Current password is incorrect.'}), 400
        if len(new_pwd) < 6:
            return jsonify({'success': False, 'message': 'New password must be at least 6 characters.'}), 400
        if new_pwd != confirm_pwd:
            return jsonify({'success': False, 'message': 'New passwords do not match.'}), 400
        if new_pwd == current_pwd:
            return jsonify({'success': False, 'message': 'New password must be different from the current one.'}), 400

        current_user.set_password(new_pwd)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Password updated successfully.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/profile/stats', methods=['GET'])
@login_required
def api_profile_stats():
    """Return quick stats + role info for the profile page."""
    if current_user.role == 'admin':
        return jsonify({
            'products': 0,
            'sales': 0,
            'role_display': current_user.get_role_display(),
            'created_at': current_user.created_at.strftime('%b %Y') if current_user.created_at else '',
        })

    uid = current_user.id
    product_count = Product.query.filter_by(owner_id=uid, is_discontinued=False).count()
    sales_count = Sale.query.filter_by(owner_id=uid).count()

    return jsonify({
        'products': product_count,
        'sales': sales_count,
        'role_display': current_user.get_role_display(),
        'created_at': current_user.created_at.strftime('%b %Y') if current_user.created_at else '',
    })


# ============================================================
# DASHBOARD (admin vs user aware)
# ============================================================

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        inactive_users = User.query.filter_by(is_active=False).count()
        total_admins = User.query.filter_by(role='admin').count()
        
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        
        return render_template('admin_dashboard.html',
            total_users=total_users,
            active_users=active_users,
            inactive_users=inactive_users,
            total_admins=total_admins,
            recent_users=recent_users
        )
    
    uid = current_user.id
    
    total_products = Product.query.filter_by(owner_id=uid, is_discontinued=False).count()
    total_suppliers = Supplier.query.filter_by(owner_id=uid).count()
    total_sales = Sale.query.filter_by(owner_id=uid).count()
    total_purchases = Purchase.query.filter_by(owner_id=uid).count()
    
    revenue_result = db.session.query(db.func.sum(Sale.total_amount)).filter(
        Sale.owner_id == uid
    ).scalar()
    revenue = float(revenue_result) if revenue_result else 0
    
    stock_value_result = db.session.query(
        db.func.sum(Product.quantity * Product.selling_price)
    ).filter(
        Product.owner_id == uid,
        Product.is_discontinued == False
    ).scalar()
    total_stock_value = float(stock_value_result) if stock_value_result else 0
    
    thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
    predicted_result = db.session.query(
        db.func.sum(SaleItem.quantity)
    ).join(Sale, SaleItem.sale_id == Sale.id)\
     .filter(Sale.owner_id == uid)\
     .filter(Sale.sale_date >= thirty_days_ago)\
     .scalar()
    predicted_demand = int(predicted_result) if predicted_result else 0
    
    low_stock_products = Product.query.filter(
        Product.owner_id == uid,
        Product.quantity < Product.min_stock,
        Product.quantity > 0,
        Product.is_discontinued == False
    ).count()
    
    pending_purchases = Purchase.query.filter_by(owner_id=uid, status='Pending').count()
    
    recent_sales = Sale.query.filter_by(owner_id=uid)\
        .order_by(Sale.created_at.desc()).limit(5).all()
    
    low_stock_items = Product.query.filter(
        Product.owner_id == uid,
        Product.quantity < Product.min_stock,
        Product.quantity > 0,
        Product.is_discontinued == False
    ).limit(5).all()
    
    return render_template('dashboard.html',
        total_products=total_products,
        total_suppliers=total_suppliers,
        total_sales=total_sales,
        total_purchases=total_purchases,
        revenue=revenue,
        total_stock_value=total_stock_value,
        predicted_demand=predicted_demand,
        low_stock_products=low_stock_products,
        pending_purchases=pending_purchases,
        recent_sales=recent_sales,
        low_stock_items=low_stock_items
    )


# ============================================================
# BUSINESS PAGES (users only)
# ============================================================

@app.route('/inventory')
@login_required
@non_admin_required
def inventory():
    uid = current_user.id
    page = request.args.get('page', 1, type=int)
    per_page = 15
    search = request.args.get('search', '').strip()
    show = request.args.get('show', 'active')
    
    query = Product.query.filter_by(owner_id=uid)
    
    if show == 'active':
        query = query.filter_by(is_discontinued=False)
    elif show == 'discontinued':
        query = query.filter_by(is_discontinued=True)
    
    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.category.ilike(f'%{search}%')
            )
        )
    
    pagination = query.order_by(Product.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    active_count = Product.query.filter_by(owner_id=uid, is_discontinued=False).count()
    discontinued_count = Product.query.filter_by(owner_id=uid, is_discontinued=True).count()
    
    suppliers = Supplier.query.filter_by(owner_id=uid, is_discontinued=False).all()
    
    return render_template('inventory.html',
        products=pagination.items,
        pagination=pagination,
        suppliers=suppliers,
        search=search,
        show=show,
        active_count=active_count,
        discontinued_count=discontinued_count
    )


@app.route('/suppliers')
@login_required
@non_admin_required
def suppliers():
    suppliers_list = Supplier.query.filter_by(owner_id=current_user.id).all()
    return render_template('suppliers.html', suppliers=suppliers_list)


@app.route('/purchases')
@login_required
@non_admin_required
def purchases():
    uid = current_user.id
    page = request.args.get('page', 1, type=int)
    per_page = 15
    
    pagination = Purchase.query.filter_by(owner_id=uid)\
        .order_by(Purchase.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    
    suppliers_list = Supplier.query.filter_by(owner_id=uid, is_discontinued=False).all()
    products_list = Product.query.filter_by(owner_id=uid, is_discontinued=False).all()
    
    return render_template('purchases.html',
        purchases=pagination.items,
        pagination=pagination,
        suppliers=suppliers_list,
        products=products_list
    )


@app.route('/sales')
@login_required
@non_admin_required
def sales():
    uid = current_user.id
    page = request.args.get('page', 1, type=int)
    per_page = 15
    
    pagination = Sale.query.filter_by(owner_id=uid)\
        .order_by(Sale.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    
    products_list = Product.query.filter_by(owner_id=uid, is_discontinued=False).all()
    
    return render_template('sales.html',
        sales=pagination.items,
        pagination=pagination,
        products=products_list
    )


@app.route('/forecasting')
@login_required
@non_admin_required
def forecasting():
    products = Product.query.filter_by(
        owner_id=current_user.id,
        is_discontinued=False
    ).all()
    return render_template('forecasting.html', products=products)


@app.route('/reports')
@login_required
@non_admin_required
def reports():
    from sqlalchemy import func, extract
    
    uid = current_user.id
    
    total_sales = Sale.query.filter_by(owner_id=uid).count()
    total_purchases = Purchase.query.filter_by(owner_id=uid).count()
    total_products = Product.query.filter_by(owner_id=uid).count()
    
    revenue_result = db.session.query(db.func.sum(Sale.total_amount)).filter(
        Sale.owner_id == uid
    ).scalar()
    revenue = float(revenue_result) if revenue_result else 0
    
    monthly_data = db.session.query(
        extract('month', Sale.sale_date).label('month'),
        func.sum(Sale.total_amount).label('total')
    ).filter(Sale.owner_id == uid)\
     .group_by('month').order_by('month').all()
    
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    monthly_labels = []
    monthly_revenue = []
    data_map = {int(m): float(t) for m, t in monthly_data}
    for i in range(1, 13):
        monthly_labels.append(month_names[i-1])
        monthly_revenue.append(data_map.get(i, 0))
    
    category_stats_raw = db.session.query(
        Product.category,
        func.count(Product.id),
        func.sum(Product.quantity * Product.selling_price)
    ).filter(Product.owner_id == uid)\
     .group_by(Product.category).all()
    
    category_stats = [{
        'name': c[0],
        'count': c[1],
        'value': float(c[2]) if c[2] else 0
    } for c in category_stats_raw]
    
    category_labels = [c['name'] for c in category_stats]
    category_values = [c['value'] for c in category_stats]
    
    top_raw = db.session.query(
        Product.name,
        func.sum(SaleItem.quantity).label('units'),
        func.sum(SaleItem.total).label('revenue')
    ).join(SaleItem, SaleItem.product_id == Product.id)\
     .join(Sale, SaleItem.sale_id == Sale.id)\
     .filter(Sale.owner_id == uid)\
     .group_by(Product.id)\
     .order_by(func.sum(SaleItem.quantity).desc())\
     .limit(10).all()
    
    top_products = [{
        'name': t[0],
        'units': int(t[1]),
        'revenue': float(t[2])
    } for t in top_raw]
    
    return render_template('reports.html',
        total_sales=total_sales,
        total_purchases=total_purchases,
        total_products=total_products,
        revenue=revenue,
        monthly_labels=monthly_labels,
        monthly_revenue=monthly_revenue,
        category_stats=category_stats,
        category_labels=category_labels,
        category_values=category_values,
        top_products=top_products
    )


@app.route('/alerts')
@login_required
def alerts():
    if current_user.role == 'admin':
        return redirect(url_for('user_management'))
    
    uid = current_user.id
    notifications = Notification.query.filter_by(owner_id=uid)\
        .order_by(Notification.created_at.desc()).all()
    unread_count = Notification.query.filter_by(owner_id=uid, is_read=False).count()
    return render_template('alerts.html', notifications=notifications, unread_count=unread_count)


# ============================================================
# USER MANAGEMENT (Admin only)
# ============================================================

@app.route('/user-management')
@login_required
@admin_required
def user_management():
    users_list = User.query.all()
    return render_template('users.html', users=users_list)


@app.route('/api/user-management/users', methods=['GET'])
@login_required
@admin_required
def api_get_users():
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'full_name': u.full_name,
        'email': u.email,
        'role': u.role,
        'role_display': u.get_role_display(),
        'is_active': u.is_active,
        'created_at': u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else '',
        'status': 'Active' if u.is_active else 'Inactive'
    } for u in users])


@app.route('/api/user-management/<int:id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def api_toggle_user_status(id):
    if id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot deactivate your own account'})
    
    user = User.query.get_or_404(id)
    user.is_active = not user.is_active
    db.session.commit()
    
    status = 'activated' if user.is_active else 'deactivated'
    return jsonify({'success': True, 'message': f'User {status} successfully', 'is_active': user.is_active})


@app.route('/api/user-management/<int:id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_user(id):
    if id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot delete your own account'})
    
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'User deleted successfully'})


# ============================================================
# API ROUTES - Products
# ============================================================

@app.route('/api/products', methods=['GET'])
@login_required
@non_admin_required
def api_get_products():
    products = Product.query.filter_by(
        owner_id=current_user.id,
        is_discontinued=False
    ).all()
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'category': p.category,
        'supplier': p.supplier_rel.company if p.supplier_rel else None,
        'supplier_id': p.supplier_id,
        'purchase_price': float(p.purchase_price),
        'quantity': p.quantity,
        'min_stock': p.min_stock,
        'selling_price': float(p.selling_price),
        'status': p.status
    } for p in products])


@app.route('/api/products/<int:id>', methods=['GET'])
@login_required
@non_admin_required
def api_get_product(id):
    product = Product.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    return jsonify({
        'id': product.id,
        'name': product.name,
        'category': product.category,
        'description': product.description,
        'supplier_id': product.supplier_id,
        'purchase_price': float(product.purchase_price),
        'selling_price': float(product.selling_price),
        'quantity': product.quantity,
        'min_stock': product.min_stock
    })


@app.route('/api/products', methods=['POST'])
@login_required
@non_admin_required
def api_add_product():
    try:
        data = request.get_json()
        
        # Validate
        is_valid, error = validate_product(data, owner_id=current_user.id)
        if not is_valid:
            return jsonify({'success': False, 'message': error}), 400
        
        product = Product(
            owner_id=current_user.id,
            name=data['name'].strip(),
            category=data['category'].strip(),
            description=(data.get('description') or '').strip(),
            supplier_id=data.get('supplier_id'),
            purchase_price=float(data['purchase_price']),
            selling_price=float(data['selling_price']),
            quantity=int(data['quantity']),
            min_stock=int(data.get('min_stock', 10))
        )
        product.update_status()
        db.session.add(product)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Product added successfully', 'id': product.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/products/<int:id>', methods=['PUT'])
@login_required
@non_admin_required
def api_update_product(id):
    try:
        product = Product.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
        data = request.get_json()
        
        # Validate (skip duplicate check for self)
        is_valid, error = validate_product(data, owner_id=current_user.id, existing_id=id)
        if not is_valid:
            return jsonify({'success': False, 'message': error}), 400
        
        product.name = data['name'].strip()
        product.category = data['category'].strip()
        product.description = (data.get('description') or '').strip()
        product.supplier_id = data.get('supplier_id')
        product.purchase_price = float(data['purchase_price'])
        product.selling_price = float(data['selling_price'])
        product.quantity = int(data['quantity'])
        product.min_stock = int(data.get('min_stock', 10))
        product.update_status()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Product updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/products/<int:id>/discontinue', methods=['POST'])
@login_required
@non_admin_required
def api_discontinue_product(id):
    try:
        product = Product.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
        
        if product.is_discontinued:
            return jsonify({
                'success': False,
                'message': f'"{product.name}" is already discontinued.'
            }), 400
        
        product.discontinue()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'"{product.name}" has been discontinued.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/products/<int:id>/restore', methods=['POST'])
@login_required
@non_admin_required
def api_restore_product(id):
    try:
        product = Product.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
        
        if not product.is_discontinued:
            return jsonify({
                'success': False,
                'message': f'"{product.name}" is not discontinued.'
            }), 400
        
        product.restore()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'"{product.name}" has been restored.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# API ROUTES - Suppliers
# ============================================================

@app.route('/api/suppliers', methods=['GET'])
@login_required
@non_admin_required
def api_get_suppliers():
    suppliers = Supplier.query.filter_by(owner_id=current_user.id).all()
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'company': s.company,
        'email': s.email,
        'phone': s.phone,
        'address': s.address
    } for s in suppliers])


@app.route('/api/suppliers', methods=['POST'])
@login_required
@non_admin_required
def api_add_supplier():
    try:
        data = request.get_json()
        
        # Validate
        is_valid, error = validate_supplier(data)
        if not is_valid:
            return jsonify({'success': False, 'message': error}), 400
        
        supplier = Supplier(
            owner_id=current_user.id,
            name=data['name'].strip(),
            company=data['company'].strip(),
            email=(data.get('email') or '').strip(),
            phone=(data.get('phone') or '').strip(),
            address=(data.get('address') or '').strip()
        )
        db.session.add(supplier)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Supplier added successfully', 'id': supplier.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/suppliers/<int:id>/discontinue', methods=['POST'])
@login_required
@non_admin_required
def api_discontinue_supplier(id):
    try:
        supplier = Supplier.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
        
        if supplier.is_discontinued:
            return jsonify({
                'success': False,
                'message': f'"{supplier.company}" is already discontinued.'
            }), 400
        
        supplier.is_discontinued = True
        supplier.discontinued_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'"{supplier.company}" has been discontinued.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/suppliers/<int:id>/restore', methods=['POST'])
@login_required
@non_admin_required
def api_restore_supplier(id):
    try:
        supplier = Supplier.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
        
        if not supplier.is_discontinued:
            return jsonify({
                'success': False,
                'message': f'"{supplier.company}" is not discontinued.'
            }), 400
        
        supplier.is_discontinued = False
        supplier.discontinued_at = None
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'"{supplier.company}" has been restored.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# API ROUTES - Purchases
# ============================================================

@app.route('/api/purchases', methods=['POST'])
@login_required
@non_admin_required
def api_create_purchase():
    try:
        data = request.get_json()
        
        # Backward compat: wrap single-item payload
        if 'product_id' in data and 'items' not in data:
            data['items'] = [{
                'product_id': data['product_id'],
                'quantity': data.get('quantity', 1),
                'purchase_price': data.get('purchase_price', 0)
            }]
        
        supplier_id = data.get('supplier_id')
        items = data.get('items', [])
        
        # Validate supplier
        if not supplier_id:
            return jsonify({'success': False, 'message': 'A supplier is required.'}), 400
        
        supplier = Supplier.query.filter_by(
            id=supplier_id, owner_id=current_user.id
        ).first()
        if not supplier:
            return jsonify({'success': False, 'message': 'Supplier not found.'}), 404
        
        # Validate items array
        if not items or not isinstance(items, list) or len(items) == 0:
            return jsonify({
                'success': False, 'message': 'Add at least one product to the order.'
            }), 400
        
        if len(items) > 100:
            return jsonify({
                'success': False, 'message': 'Too many items in one order (max 100).'
            }), 400
        
        total_amount = 0
        validated_items = []
        
        for i, item in enumerate(items, 1):
            product_id = item.get('product_id')
            try:
                quantity = int(item.get('quantity', 0))
                purchase_price = float(item.get('purchase_price', 0))
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'message': f'Item #{i}: quantity or price is not a valid number.'
                }), 400
            
            if quantity <= 0:
                return jsonify({
                    'success': False,
                    'message': f'Item #{i}: quantity must be greater than 0.'
                }), 400
            if quantity > 1_000_000:
                return jsonify({
                    'success': False,
                    'message': f'Item #{i}: quantity is unrealistically high.'
                }), 400
            if purchase_price <= 0:
                return jsonify({
                    'success': False,
                    'message': f'Item #{i}: unit price must be greater than 0.'
                }), 400
            if purchase_price > 10_000_000:
                return jsonify({
                    'success': False,
                    'message': f'Item #{i}: unit price is too high.'
                }), 400
            
            product = Product.query.filter_by(
                id=product_id, owner_id=current_user.id
            ).first()
            if not product:
                return jsonify({
                    'success': False,
                    'message': f'Item #{i}: product not found.'
                }), 404
            
            line_total = purchase_price * quantity
            total_amount += line_total
            
            validated_items.append({
                'product_id': product_id,
                'quantity': quantity,
                'purchase_price': purchase_price,
                'total': line_total
            })
        
        purchase = Purchase(
            owner_id=current_user.id,
            supplier_id=supplier_id,
            purchase_date=datetime.now().date(),
            total_amount=total_amount,
            status='Pending'
        )
        db.session.add(purchase)
        db.session.flush()
        
        for v in validated_items:
            purchase_item = PurchaseItem(
                purchase_id=purchase.id,
                product_id=v['product_id'],
                quantity=v['quantity'],
                purchase_price=v['purchase_price'],
                total=v['total']
            )
            db.session.add(purchase_item)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Purchase order created with {len(validated_items)} item(s).',
            'id': purchase.id,
            'total': total_amount
        })
    
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Purchase creation failed: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/purchases/<int:id>', methods=['GET'])
@login_required
@non_admin_required
def api_get_purchase(id):
    purchase = Purchase.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
    
    return jsonify({
        'id': purchase.id,
        'supplier_name': purchase.supplier.company if purchase.supplier else None,
        'supplier_id': purchase.supplier_id,
        'purchase_date': purchase.purchase_date.strftime('%Y-%m-%d'),
        'total_amount': float(purchase.total_amount),
        'status': purchase.status,
        'items': [{
            'id': item.id,
            'product_id': item.product_id,
            'product_name': item.product.name if item.product else 'Unknown',
            'quantity': item.quantity,
            'purchase_price': float(item.purchase_price),
            'total': float(item.total)
        } for item in purchase.items]
    })


@app.route('/api/purchases/<int:id>/receive', methods=['POST'])
@login_required
@non_admin_required
def api_receive_purchase(id):
    try:
        purchase = Purchase.query.filter_by(id=id, owner_id=current_user.id).first_or_404()
        purchase.status = 'Received'
        
        for item in purchase.items:
            product = Product.query.filter_by(
                id=item.product_id, 
                owner_id=current_user.id
            ).first()
            if product:
                product.quantity += item.quantity
                product.update_status()
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Purchase received successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


# ============================================================
# API ROUTES - Sales
# ============================================================

@app.route('/api/sales', methods=['POST'])
@login_required
@non_admin_required
def api_create_sale():
    try:
        data = request.get_json()
        cart_items = data.get('cart_items', [])
        customer_name = (data.get('customer_name') or '').strip()
        
        # Validate cart
        is_valid, error = validate_sale_items(cart_items, owner_id=current_user.id)
        if not is_valid:
            return jsonify({'success': False, 'message': error}), 400
        
        if len(customer_name) > 100:
            return jsonify({
                'success': False,
                'message': 'Customer name must be under 100 characters.'
            }), 400
        
        total_amount = 0
        sale = Sale(
            owner_id=current_user.id,
            customer_name=customer_name or 'Walk-in',
            sale_date=datetime.now().date(),
            total_amount=0
        )
        db.session.add(sale)
        db.session.flush()
        
        for item in cart_items:
            product = Product.query.filter_by(
                id=item['id'], 
                owner_id=current_user.id
            ).first()
            
            # Validation already checked these, but keep guards for safety
            if not product:
                return jsonify({'success': False, 'message': 'Product not found'})
            
            if product.is_discontinued:
                return jsonify({
                    'success': False,
                    'message': f'"{product.name}" has been discontinued and cannot be sold.'
                }), 400
            
            if product.quantity < item['qty']:
                return jsonify({'success': False, 'message': f'Insufficient stock for {product.name}'})
            
            amount = float(product.selling_price) * item['qty']
            total_amount += amount
            
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                quantity=item['qty'],
                selling_price=product.selling_price,
                total=amount
            )
            db.session.add(sale_item)
            
            product.quantity -= item['qty']
            product.update_status()
        
        sale.total_amount = total_amount
        db.session.commit()
        
        check_low_stock(current_user.id)
        
        return jsonify({'success': True, 'message': 'Sale completed successfully', 'total': total_amount})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


def check_low_stock(owner_id):
    """Check low stock for a specific user's products"""
    products = Product.query.filter(
        Product.owner_id == owner_id,
        Product.quantity < Product.min_stock,
        Product.quantity > 0,
        Product.is_discontinued == False
    ).all()
    
    for product in products:
        existing = Notification.query.filter_by(
            owner_id=owner_id,
            title=f'{product.name} - Low Stock',
            is_read=False
        ).first()
        if not existing:
            notification = Notification(
                owner_id=owner_id,
                type='Low Stock',
                title=f'{product.name} - Low Stock',
                message=f'{product.quantity} units remaining. Reorder level: {product.min_stock}'
            )
            db.session.add(notification)
    
    out_of_stock = Product.query.filter(
        Product.owner_id == owner_id,
        Product.quantity == 0,
        Product.is_discontinued == False
    ).all()
    for product in out_of_stock:
        existing = Notification.query.filter_by(
            owner_id=owner_id,
            title=f'{product.name} - Out of Stock',
            is_read=False
        ).first()
        if not existing:
            notification = Notification(
                owner_id=owner_id,
                type='Low Stock',
                title=f'{product.name} - Out of Stock',
                message=f'Product is completely out of stock. Reorder immediately!'
            )
            db.session.add(notification)
    
    db.session.commit()


# ============================================================
# API ROUTES - AI Forecasting
# ============================================================

@app.route('/api/forecast', methods=['POST'])
@login_required
@non_admin_required
def api_generate_forecast():
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        period = data.get('period', 30)
        
        product = Product.query.filter_by(
            id=product_id, 
            owner_id=current_user.id
        ).first()
        if not product:
            return jsonify({'success': False, 'message': 'Product not found'}), 404
        
        sales_items = SaleItem.query.filter_by(product_id=product_id).all()
        
        if not sales_items:
            historical = [120, 135, 98, 145, 160, 180, 200, 165, 190, 210, 230, 250]
        else:
            historical = [item.quantity for item in sales_items[-12:]]
            while len(historical) < 12:
                historical.insert(0, historical[0] if historical else 100)
        
        avg = sum(historical) / len(historical)
        trend = (historical[-1] - historical[0]) / historical[0] if historical[0] > 0 else 0
        predicted = int(avg * (1 + trend * 0.3) * (period / 30))
        confidence = int(75 + (20 * (1 - abs(trend) / 2)))
        if confidence > 95:
            confidence = 95
        
        current_stock = product.quantity
        recommended = int(predicted * 1.15)
        reorder_qty = max(0, recommended - current_stock)
        
        return jsonify({
            'success': True,
            'predicted_demand': predicted,
            'confidence_score': confidence,
            'current_stock': current_stock,
            'recommended_stock': recommended,
            'reorder_qty': reorder_qty,
            'historical_data': historical
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ============================================================
# API ROUTES - Alerts
# ============================================================

@app.route('/api/alerts/mark-read/<int:id>', methods=['POST'])
@login_required
@non_admin_required
def api_mark_alert_read(id):
    try:
        notification = Notification.query.filter_by(
            id=id, 
            owner_id=current_user.id
        ).first_or_404()
        notification.is_read = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/alerts/mark-all-read', methods=['POST'])
@login_required
@non_admin_required
def api_mark_all_alerts_read():
    try:
        Notification.query.filter_by(
            owner_id=current_user.id, 
            is_read=False
        ).update({'is_read': True})
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/alerts/unread-count', methods=['GET'])
@login_required
def api_get_unread_count():
    if current_user.role == 'admin':
        return jsonify({'count': 0})
    
    count = Notification.query.filter_by(
        owner_id=current_user.id, 
        is_read=False
    ).count()
    return jsonify({'count': count})

# ============================================================
# CSV EXPORT ENDPOINTS
# ============================================================

def csv_response(rows, headers, filename):
    """
    Build a CSV HTTP response.
    
    rows: list of lists (or list of dicts)
    headers: list of column headers
    filename: name of the downloaded file
    """
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    
    # Build response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@app.route('/export/inventory.csv')
@login_required
@non_admin_required
def export_inventory_csv():
    """Export all user's products as CSV"""
    products = Product.query.filter_by(owner_id=current_user.id)\
        .order_by(Product.name.asc()).all()
    
    headers = [
        'ID', 'Product Name', 'Category', 'Supplier', 'Description',
        'Purchase Price', 'Selling Price', 'Quantity', 'Min Stock',
        'Status', 'Discontinued', 'Created At'
    ]
    
    rows = []
    for p in products:
        rows.append([
            p.id,
            p.name,
            p.category,
            p.supplier_rel.company if p.supplier_rel else '',
            p.description or '',
            f"{float(p.purchase_price):.2f}",
            f"{float(p.selling_price):.2f}",
            p.quantity,
            p.min_stock,
            p.status,
            'Yes' if p.is_discontinued else 'No',
            p.created_at.strftime('%Y-%m-%d') if p.created_at else ''
        ])
    
    filename = f"inventory_{datetime.now().strftime('%Y-%m-%d')}.csv"
    return csv_response(rows, headers, filename)


@app.route('/export/sales.csv')
@login_required
@non_admin_required
def export_sales_csv():
    """Export all user's sales with line items as CSV"""
    sales = Sale.query.filter_by(owner_id=current_user.id)\
        .order_by(Sale.sale_date.desc()).all()
    
    headers = [
        'Sale ID', 'Date', 'Customer', 'Product', 'Quantity',
        'Unit Price', 'Line Total', 'Sale Total'
    ]
    
    rows = []
    for sale in sales:
        if sale.items:
            for item in sale.items:
                rows.append([
                    sale.id,
                    sale.sale_date.strftime('%Y-%m-%d') if sale.sale_date else '',
                    sale.customer_name or 'Walk-in',
                    item.product.name if item.product else 'Unknown',
                    item.quantity,
                    f"{float(item.selling_price):.2f}",
                    f"{float(item.total):.2f}",
                    f"{float(sale.total_amount):.2f}"
                ])
        else:
            # Sale with no items (edge case)
            rows.append([
                sale.id,
                sale.sale_date.strftime('%Y-%m-%d') if sale.sale_date else '',
                sale.customer_name or 'Walk-in',
                '—',
                0, '0.00', '0.00',
                f"{float(sale.total_amount):.2f}"
            ])
    
    filename = f"sales_{datetime.now().strftime('%Y-%m-%d')}.csv"
    return csv_response(rows, headers, filename)


@app.route('/export/purchases.csv')
@login_required
@non_admin_required
def export_purchases_csv():
    """Export all user's purchase orders as CSV"""
    purchases = Purchase.query.filter_by(owner_id=current_user.id)\
        .order_by(Purchase.purchase_date.desc()).all()
    
    headers = [
        'PO ID', 'Date', 'Supplier', 'Status', 'Product', 'Quantity',
        'Unit Cost', 'Line Total', 'Order Total'
    ]
    
    rows = []
    for po in purchases:
        if po.items:
            for item in po.items:
                rows.append([
                    po.id,
                    po.purchase_date.strftime('%Y-%m-%d') if po.purchase_date else '',
                    po.supplier.company if po.supplier else '—',
                    po.status,
                    item.product.name if item.product else 'Unknown',
                    item.quantity,
                    f"{float(item.purchase_price):.2f}",
                    f"{float(item.total):.2f}",
                    f"{float(po.total_amount):.2f}"
                ])
        else:
            rows.append([
                po.id,
                po.purchase_date.strftime('%Y-%m-%d') if po.purchase_date else '',
                po.supplier.company if po.supplier else '—',
                po.status,
                '—', 0, '0.00', '0.00',
                f"{float(po.total_amount):.2f}"
            ])
    
    filename = f"purchases_{datetime.now().strftime('%Y-%m-%d')}.csv"
    return csv_response(rows, headers, filename)


@app.route('/export/reports.csv')
@login_required
@non_admin_required
def export_reports_csv():
    """Export monthly revenue summary + top products as CSV"""
    uid = current_user.id
    
    # Monthly revenue
    monthly_data = db.session.query(
        extract('month', Sale.sale_date).label('month'),
        func.sum(Sale.total_amount).label('total'),
        func.count(Sale.id).label('count')
    ).filter(Sale.owner_id == uid)\
     .group_by('month').order_by('month').all()
    
    month_names = ['Jan','Feb','Mar','Apr','May','Jun',
                   'Jul','Aug','Sep','Oct','Nov','Dec']
    
    # Build CSV with two sections
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Section 1: Summary
    writer.writerow(['INTELLISHELF REPORT'])
    writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}'])
    writer.writerow([f'Company: {current_user.company_name}'])
    writer.writerow([])
    
    writer.writerow(['SUMMARY'])
    writer.writerow(['Metric', 'Value'])
    
    total_revenue = db.session.query(func.sum(Sale.total_amount))\
        .filter(Sale.owner_id == uid).scalar() or 0
    total_sales = Sale.query.filter_by(owner_id=uid).count()
    total_purchases = Purchase.query.filter_by(owner_id=uid).count()
    total_products = Product.query.filter_by(owner_id=uid, is_discontinued=False).count()
    
    writer.writerow(['Total Revenue', f"{float(total_revenue):.2f}"])
    writer.writerow(['Total Sales', total_sales])
    writer.writerow(['Total Purchases', total_purchases])
    writer.writerow(['Active Products', total_products])
    writer.writerow([])
    
    # Section 2: Monthly revenue
    writer.writerow(['MONTHLY REVENUE'])
    writer.writerow(['Month', 'Sales Count', 'Revenue'])
    
    data_map = {int(m): (float(t), c) for m, t, c in monthly_data}
    for i in range(1, 13):
        total, count = data_map.get(i, (0, 0))
        writer.writerow([month_names[i-1], count, f"{total:.2f}"])
    writer.writerow([])
    
    # Section 3: Top products
    writer.writerow(['TOP SELLING PRODUCTS'])
    writer.writerow(['Rank', 'Product', 'Units Sold', 'Revenue'])
    
    top_raw = db.session.query(
        Product.name,
        func.sum(SaleItem.quantity).label('units'),
        func.sum(SaleItem.total).label('revenue')
    ).join(SaleItem, SaleItem.product_id == Product.id)\
     .join(Sale, SaleItem.sale_id == Sale.id)\
     .filter(Sale.owner_id == uid)\
     .group_by(Product.id)\
     .order_by(func.sum(SaleItem.quantity).desc())\
     .limit(20).all()
    
    for i, (name, units, revenue) in enumerate(top_raw, 1):
        writer.writerow([i, name, int(units), f"{float(revenue):.2f}"])
    
    filename = f"report_{datetime.now().strftime('%Y-%m-%d')}.csv"
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

# ============================================================
# CONTEXT PROCESSOR
# ============================================================

@app.context_processor
def utility_processor():
    def get_unread_count():
        if current_user.is_authenticated and current_user.role != 'admin':
            return Notification.query.filter_by(
                owner_id=current_user.id, 
                is_read=False
            ).count()
        return 0
    
    return dict(
        get_unread_count=get_unread_count,
        now=datetime.now
    )


# ============================================================
# CREATE TABLES & SEED ADMIN
# ============================================================

with app.app_context():
    db.create_all()
    print("✅ Database tables created successfully!")
    
    admin = User.query.filter_by(email='admin@system.com').first()
    if not admin:
        admin = User(
            full_name='System Admin',
            company_name='System Administration',
            email='admin@system.com',
            role='admin',
            is_active=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()


if __name__ == '__main__':
    print("🚀 Starting IntelliShelf Server...")
    print("📍 Access at: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)