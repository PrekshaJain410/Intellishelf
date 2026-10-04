-- ==========================================
-- IntelliShelf Database (MySQL)
-- ==========================================

CREATE DATABASE IF NOT EXISTS inventory_system;
USE inventory_system;

-- ==========================================
-- USERS TABLE
-- ==========================================
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    company_name VARCHAR(150) NOT NULL DEFAULT 'My Business',
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(100) NOT NULL,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ==========================================
-- SUPPLIERS TABLE
-- ==========================================
CREATE TABLE suppliers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    company VARCHAR(100) NOT NULL,
    email VARCHAR(100),
    phone VARCHAR(20),
    address TEXT,
    is_discontinued BOOLEAN DEFAULT FALSE,
    discontinued_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ==========================================
-- PRODUCTS TABLE
-- ==========================================
CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    description TEXT,
    supplier_id INT,
    purchase_price DECIMAL(10,2) NOT NULL,
    selling_price DECIMAL(10,2) NOT NULL,
    quantity INT DEFAULT 0,
    min_stock INT DEFAULT 5,
    status ENUM('In Stock', 'Low Stock', 'Out of Stock') DEFAULT 'In Stock',
    is_discontinued BOOLEAN DEFAULT FALSE,
    discontinued_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
);

-- ==========================================
-- PURCHASES TABLE
-- ==========================================
CREATE TABLE purchases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    supplier_id INT,
    purchase_date DATE NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    status ENUM('Pending', 'Received', 'Cancelled') DEFAULT 'Pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
);

-- ==========================================
-- PURCHASE ITEMS TABLE
-- ==========================================
CREATE TABLE purchase_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    purchase_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    purchase_price DECIMAL(10,2) NOT NULL,
    total DECIMAL(10,2) NOT NULL,

    FOREIGN KEY (purchase_id) REFERENCES purchases(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

-- ==========================================
-- SALES TABLE
-- ==========================================
CREATE TABLE sales (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    customer_name VARCHAR(100),
    sale_date DATE NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ==========================================
-- SALE ITEMS TABLE
-- ==========================================
CREATE TABLE sale_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sale_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    selling_price DECIMAL(10,2) NOT NULL,
    total DECIMAL(10,2) NOT NULL,

    FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

-- ==========================================
-- NOTIFICATIONS TABLE
-- ==========================================
CREATE TABLE notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    type ENUM('Low Stock', 'Reorder', 'Forecast', 'System') DEFAULT 'System',
    title VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);