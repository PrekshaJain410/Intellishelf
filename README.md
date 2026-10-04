 # Intellishelf

### Smart Inventory & Procurement Management System

---

##  Overview

**IntelliShelf** is a web-based inventory management system that helps businesses manage their products, suppliers, purchases, and sales in one place.

The system is designed to reduce manual work and provide better control over stock and business operations.

---

##  Technologies Used

* **Backend:** Python (Flask)
* **Database:** MySQL
* **Frontend:** HTML, CSS, Bootstrap, JS
* **ORM:** SQLAlchemy

---

##  Features

###  User System

* User registration and login
* Secure authentication

###  Product Management

* Add, update, and delete products
* Track stock quantity
* Automatic stock status (In Stock / Low Stock / Out of Stock)

###  Supplier Management

* Store supplier details
* Link suppliers to products

###  Purchase Management

* Create and manage purchase orders
* Track order status

###  Sales Management

* Record sales transactions
* Calculate total sales amount

###  Notifications

* Alerts for low stock
* System notifications

###  Dashboard & Reports

* Overview of products, sales, and purchases
* Revenue and stock insights

---

##  Database Structure

The system uses the following main tables:

* Users
* Products
* Suppliers
* Purchases
* Purchase_Items
* Sales
* Sale_Items
* Notifications

---

##  System Flow

1. User logs into the system
2. Adds products and suppliers
3. Creates purchase entries to update stock
4. Records sales which reduce stock
5. System automatically updates stock status and generates alerts

---

## 📚 Conclusion

IntelliShelf provides a simple and efficient way to manage inventory and business operations, making it useful for small and medium-sized businesses.

---
