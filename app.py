from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
from flask_migrate import Migrate
from flask import abort
from datetime import timedelta
from datetime import datetime
from flask_wtf import CSRFProtect
from flask import jsonify

# ---------- تنظیمات اولیه ----------
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///store.db'
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
csrf = CSRFProtect(app)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
migrate = Migrate(app, db)
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)  # مثلاً یک ماه لاگین بمونه
app.config['REMEMBER_COOKIE_REFRESH_EACH_REQUEST'] = True

login_manager.init_app(app)

favorites = db.Table('favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('product_id', db.Integer, db.ForeignKey('product.id'))
)

# این خط خیلی مهمه
login_manager.login_view = 'login'  # نام تابع (view function) صفحه ورود
# ---------- مدل‌ها ----------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50))
    image = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)  # ✅ اضافه شد
    expiration_date = db.Column(db.Date, nullable=True)  # ✅ تاریخ انقضا
    stock = db.Column(db.Integer, default=0)  # ✅ موجودی انبار


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    product = db.relationship('Product')
    user = db.relationship('User')

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')  # ✅ نقش: user یا admin
    favorites = db.relationship('Product', secondary=favorites, backref='favorited_by')

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='در حال پردازش')  # یا: ارسال شده، لغو شده
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='orders')


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)

    order = db.relationship('Order', backref='items')
    product = db.relationship('Product')


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))


    product = db.relationship('Product')

# ---------- بارگذاری کاربر ----------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- ساخت دیتابیس ----------
with app.app_context():
    db.create_all()

# ---------- روت‌ها ----------
# @app.route('/')
@app.route('/dashboard')
def dashboard():
    q = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '')
    sort = request.args.get('sort', '')  # ✅ اضافه شد

    products_query = Product.query
    if q:
        products_query = products_query.filter(Product.name.contains(q))
    if category_filter:
        products_query = products_query.filter_by(category=category_filter)

    # مرتب‌سازی
    if sort == 'price_asc':
        products_query = products_query.order_by(Product.price.asc())
    elif sort == 'price_desc':
        products_query = products_query.order_by(Product.price.desc())

    categories = Category.query.all()  # این خط رو اضافه کردم

    if current_user.is_authenticated and current_user.role == 'admin':
        total_products = Product.query.count()
        total_users = User.query.count()
        total_orders = Order.query.count()
        total_income = db.session.query(db.func.sum(Order.total_price)).scalar() or 0
        products = products_query.all()
        return render_template('dashboard.html', products=products, categories=categories,
                               total_products=total_products, total_users=total_users,
                               total_orders=total_orders, total_income=total_income)

    products = products_query.all()
    return render_template('dashboard.html', products=products, categories=categories, sort=sort)



@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('shop'))
    else:
        return redirect(url_for('register'))

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if not is_admin():
        abort(403)

    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price')
        category = request.form.get('category')
        image = request.files.get('image')
        description = request.form.get('description')

        if name and price and category and image:
            image_filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

            try:
                price_float = float(price)
            except ValueError:
                flash('قیمت نامعتبر است.', 'danger')
                return redirect(url_for('add_product'))

            product = Product(
                name=name,
                price=price_float,
                category=category,
                image=image_filename,
                description=description
            )

            db.session.add(product)
            db.session.commit()

            flash('محصول با موفقیت اضافه شد.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('لطفاً همه فیلدها را کامل کنید.', 'danger')

    categories = [c.name for c in Category.query.all()]
    return render_template('add_product.html', categories=categories)


@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    categories = ['الکترونیکی', 'پوشاک', 'خوراکی', 'لوازم خانه']

    if request.method == 'POST':
        product.name = request.form['name']
        product.price = request.form['price']
        product.category = request.form['category']

        image_file = request.files['image']
        if image_file:
            image_filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            image_file.save(image_path)
            product.image = image_filename

        db.session.commit()
        flash('محصول ویرایش شد.', 'info')
        return redirect(url_for('dashboard'))

    return render_template('edit_product.html', product=product, categories=categories)


@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('محصول حذف شد.', 'warning')
    return redirect(url_for('dashboard'))


@app.route('/shop')
def shop():
    products = Product.query.all()
    q = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '')
    sort = request.args.get('sort', '')  # ✅ اضافه شد

    products_query = Product.query
    if q:
        products_query = products_query.filter(Product.name.contains(q))
    if category_filter:
        products_query = products_query.filter_by(category=category_filter)

    # ✅ مرتب‌سازی
    if sort == 'price_asc':
        products_query = products_query.order_by(Product.price.asc())
    elif sort == 'price_desc':
        products_query = products_query.order_by(Product.price.desc())

    products = products_query.all()
    categories = Category.query.all()
    return render_template('shop.html', products=products, categories=categories, sort=sort)


@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    categories = Category.query.all()
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name:
            existing = Category.query.filter_by(name=name).first()
            if not existing:
                db.session.add(Category(name=name))
                db.session.commit()
    return render_template('categories.html', categories=categories)


@app.route('/categories/delete/<int:category_id>', methods=['POST'])
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    flash('دسته‌بندی حذف شد.', 'info')
    return redirect(url_for('manage_categories'))


@app.route('/cart')
@login_required
def view_cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in items)
    return render_template('cart.html', items=items, total=total)



@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    # چک می‌کنیم آیتمی با این محصول قبلا در سبد هست یا نه
    existing_item = CartItem.query.filter_by(product_id=product.id, user_id=current_user.id).first()

    if existing_item:
        existing_item.quantity += 1
    else:
        new_item = CartItem(product_id=product.id, user_id=current_user.id, quantity=1)
        db.session.add(new_item)

    db.session.commit()
    flash('محصول به سبد خرید اضافه شد.', 'success')
    return redirect(url_for('shop'))


@app.route('/cart/remove/<int:item_id>', methods=['POST'])
def remove_from_cart(item_id):
    item = CartItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash('آیتم حذف شد.', 'warning')
    return redirect(url_for('view_cart'))


# @app.route('/checkout', methods=['POST'])
# @login_required
# def checkout1():
#     CartItem.query.delete()
#     db.session.commit()
#     flash('پرداخت با موفقیت انجام شد!', 'success')
#     return redirect(url_for('shop'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('shop'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('این نام کاربری قبلاً ثبت شده.', 'warning')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        is_first_user = User.query.count() == 0
        role = 'admin' if is_first_user else 'user'

        new_user = User(username=username, password=hashed_password, role=role)
        db.session.add(new_user)
        db.session.commit()

        flash('ثبت‌ نام با موفقیت انجام شد.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')





@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        print(f"Login attempt: username={username}")

        user = User.query.filter_by(username=username).first()
        if not user:
            print("User not found")
            flash('نام کاربری یا رمز اشتباه است.', 'danger')
            return redirect(url_for('login'))

        if not password:
            print("Empty password")
            flash('رمز عبور را وارد کنید.', 'danger')
            return redirect(url_for('login'))

        if check_password_hash(user.password, password):
            login_user(user, remember=True)
            flash('ورود موفقیت‌آمیز بود.', 'success')
            if user.role == 'admin':
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('shop'))
        else:
            print("Wrong password")
            flash('نام کاربری یا رمز اشتباه است.', 'danger')

    return render_template('login1.html')





@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('خروج انجام شد.', 'info')
    return redirect(url_for('login'))


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('product_detail.html', product=product)

def is_admin():
    return current_user.is_authenticated and current_user.role == 'admin'

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403

@app.route('/checkout_test', methods=['POST'])
@login_required
def checkout_test():
    # حذف آیتم‌های کاربر از سبد خرید
    CartItem.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()

    flash('پرداخت آزمایشی با موفقیت انجام شد!', 'success')
    return redirect(url_for('shop'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash('سبد خرید شما خالی است.', 'warning')
        return redirect(url_for('shop'))

    total_price = sum(item.product.price * item.quantity for item in cart_items)

    # ایجاد سفارش
    new_order = Order(user_id=current_user.id, total_price=total_price)
    db.session.add(new_order)
    db.session.commit()

    # اضافه کردن آیتم‌ها
    for item in cart_items:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=item.product.id,
            quantity=item.quantity
        )
        db.session.add(order_item)

    # پاک‌کردن سبد خرید
    CartItem.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()

    flash('پرداخت با موفقیت انجام شد و سفارش ثبت شد.', 'success')
    return redirect(url_for('shop'))

@app.route('/admin/orders')
@login_required
def admin_orders():
    if not is_admin():
        abort(403)

    username = request.args.get('username', '').strip()

    orders_query = Order.query.join(User)
    if username:
        orders_query = orders_query.filter(User.username.contains(username))

    orders = orders_query.order_by(Order.created_at.desc()).all()
    return render_template('admin_orders.html', orders=orders)

@app.route('/admin/order/<int:order_id>/status', methods=['POST'])
@login_required
def change_order_status(order_id):
    if not is_admin():
        abort(403)

    status = request.form.get('status')
    order = Order.query.get_or_404(order_id)
    order.status = status
    db.session.commit()
    flash('وضعیت سفارش بروزرسانی شد.', 'info')
    return redirect(url_for('admin_orders'))


@app.route('/add_to_favorite', methods=['POST'])
@login_required
def add_to_favorite():
    data = request.get_json()
    product_id = data.get('product_id')

    if not product_id or not current_user.is_authenticated:
        return jsonify({'error': 'Unauthorized'}), 401

    existing = Favorite.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        return jsonify({'message': 'Already in favorites'}), 200

    new_fav = Favorite(user_id=current_user.id, product_id=product_id)
    db.session.add(new_fav)
    db.session.commit()
    return jsonify({'message': 'Added to favorites'}), 200


@app.route('/favorites')
@login_required
def view_favorites():
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    return render_template('favorites.html', favorites=favorites)


@app.route('/favorite/<int:product_id>', methods=['POST'])
@login_required
def favorite(product_id):
    if product_id in current_user.favorite_ids:
        current_user.favorite_ids.remove(product_id)
        db.session.commit()
        return jsonify({'status': 'removed'})
    else:
        current_user.favorite_ids.append(product_id)
        db.session.commit()
        return jsonify({'status': 'added'})

# ---------- اضافه کردن دسته‌بندی‌های پیش‌فرض ----------
# در فایل init:
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'

with app.app_context():
    db.create_all()

    # دسته‌بندی‌های پیش‌فرض
    default_categories = ['وسیله نقلیه', 'پوشاک', 'خوراکی', 'لوازم خانگی', 'الکترونیکی', 'دیجیتال']
    existing_categories = [cat.name for cat in Category.query.all()]

    for cat in default_categories:
        if cat not in existing_categories:
            db.session.add(Category(name=cat))

    # ✅ ساخت ادمین ثابت
    admin_user = User.query.filter_by(username=ADMIN_USERNAME).first()
    if not admin_user:
        hashed_password = generate_password_hash(ADMIN_PASSWORD)
        admin_user = User(username=ADMIN_USERNAME, password=hashed_password, role='admin')
        db.session.add(admin_user)

    db.session.commit()


# ---------- اجرا ----------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=True, host="0.0.0.0", port=port)

