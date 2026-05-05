import streamlit as st
import mysql.connector
import pandas as pd
from decimal import Decimal
from datetime import datetime, timedelta

MAX_ATTEMPTS = 3
LOCK_MINUTES = 5
# ----------------------------------------------------
# PAGE CONFIG & HEADER
# ----------------------------------------------------
st.set_page_config(
    page_title="BankDB Transaction Monitoring System",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown(
    """
    <style>
    /* Force dark background */
    html, body, [class*="css"] {
        background-color: #0e1117 !important;
        color: #e6e6e6 !important;
    }

    /* Main content area */
    section[data-testid="stAppViewContainer"] {
        background-color: #0e1117 !important;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #0b0f14 !important;
    }

    /* Text inputs, select boxes */
    input, textarea, select {
        background-color: #111827 !important;
        color: #e6e6e6 !important;
        border: 1px solid #22d3ee !important;
    }

    /* Buttons */
    button {
        background-color: #22d3ee !important;
        color: #000000 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }

    button:hover {
        background-color: #06b6d4 !important;
        color: #000000 !important;
    }

    /* Headings (cyan theme) */
    h1, h2, h3, h4, h5, h6 {
        color: #22d3ee !important;
    }

    /* Hide Streamlit footer ONLY */
    footer {
        visibility: hidden;
    }

    /* Hide Streamlit footer ONLY */
    header [data-testid="stToolbar"] {
    visibility: visible;
    }

    /* Keep header visible so sidebar toggle works */
    header {
        background: transparent !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ----------------------------------------------------
# SESSION STATE INITIALIZATION (LOGIN)
# ----------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "role" not in st.session_state:
    st.session_state.role = None  # "admin" or "user"

if "user_customer_id" not in st.session_state:
    st.session_state.user_customer_id = None

if "user_name" not in st.session_state:
    st.session_state.user_name = None
# ----------------------------------------------------
# SESSION STATE INITIALIZATION (MESSAGES)
# ----------------------------------------------------
if "success_msg" not in st.session_state:
    st.session_state.success_msg = None

if "error_msg" not in st.session_state:
    st.session_state.error_msg = None



st.title("BankDB Transaction Monitoring System")
st.caption("Secure banking operations • Auto DB & schema initialization • Real-time monitoring")
st.markdown("---")

# ----------------------------------------------------
# DATABASE + SCHEMA INITIALIZATION
# ----------------------------------------------------
def initialize_database():
    # Connect without DB
    temp_con = mysql.connector.connect(
        host="localhost",
        user="root",
        password="root"
    )
    cursor = temp_con.cursor()

    # ---- DATABASE ----
    check_db_query = "SHOW DATABASES LIKE 'BankDB'"
    create_db_query = "CREATE DATABASE BankDB"

    cursor.execute(check_db_query)
    if not cursor.fetchone():
        cursor.execute(create_db_query)

    cursor.execute("USE BankDB")

    # ---- TABLES ----
    customers_table_query = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(100),
    phone VARCHAR(50) NOT NULL,
    city VARCHAR(50) NOT NULL,
    failed_attempts INT DEFAULT 0,
    lock_until DATETIME DEFAULT NULL
)
"""


    accounts_table_query = """
    CREATE TABLE IF NOT EXISTS accounts (
        account_number BIGINT AUTO_INCREMENT PRIMARY KEY,
        customer_id INT,
        branch VARCHAR(50),
        balance DECIMAL(12,2) DEFAULT 1000 CHECK (balance >= 1000),
        account_type ENUM('savings','current'),
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    )
    """

    set_account_start_query = "ALTER TABLE accounts AUTO_INCREMENT = 1001"

    transactions_table_query = """
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id INT AUTO_INCREMENT PRIMARY KEY,
        account_number BIGINT,
        transaction_type ENUM('deposit','withdraw'),
        amount DECIMAL(12,2),
        transaction_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_number) REFERENCES accounts(account_number)
    )
    """

    alerts_table_query = """
    CREATE TABLE IF NOT EXISTS alerts (
        alert_id INT AUTO_INCREMENT PRIMARY KEY,
        account_number BIGINT,
        amount DECIMAL(12,2),
        alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message VARCHAR(255),
        FOREIGN KEY (account_number) REFERENCES accounts(account_number)
    )
    """

    cursor.execute(customers_table_query)
    cursor.execute(accounts_table_query)
    cursor.execute(set_account_start_query)
    cursor.execute(transactions_table_query)
    cursor.execute(alerts_table_query)

    create_admin_logs_table = """
CREATE TABLE IF NOT EXISTS admin_logs (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(50),
    operation_type VARCHAR(20),   -- INSERT / UPDATE / DELETE
    record_id VARCHAR(50),
    old_data TEXT,
    new_data TEXT,
    action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
    cursor.execute(create_admin_logs_table)

    create_security_logs_table = """
    CREATE TABLE IF NOT EXISTS security_logs (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT,
    event_type VARCHAR(50),        -- FAILED_LOGIN / ACCOUNT_LOCKED / ACCOUNT_UNLOCKED
    failed_attempts INT,
    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details VARCHAR(255),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
)
"""
    cursor.execute(create_security_logs_table)


    # ---- STORED PROCEDURE ----
    drop_proc_query = "DROP PROCEDURE IF EXISTS perform_transactions"

    create_proc_query = """
    CREATE PROCEDURE perform_transactions(
        IN acc_no BIGINT,
        IN txn_type VARCHAR(10),
        IN amt DECIMAL(12,2)
    )
    BEGIN
        DECLARE current_balance DECIMAL(12,2);

        SELECT balance INTO current_balance
        FROM accounts
        WHERE account_number = acc_no;

        IF txn_type = 'deposit' THEN
            UPDATE accounts
            SET balance = balance + amt
            WHERE account_number = acc_no;

            INSERT INTO transactions(account_number, transaction_type, amount)
            VALUES (acc_no, 'deposit', amt);

        ELSEIF txn_type = 'withdraw' THEN
            IF current_balance - amt >= 1000 THEN
                UPDATE accounts
                SET balance = balance - amt
                WHERE account_number = acc_no;

                INSERT INTO transactions(account_number, transaction_type, amount)
                VALUES (acc_no, 'withdraw', amt);
            ELSE
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Minimum balance of 1000 must be maintained';
            END IF;
        END IF;
    END
    """

    cursor.execute(drop_proc_query)
    cursor.execute(create_proc_query)

    # ---- TRIGGER ----
    drop_alert_trigger_query = "DROP TRIGGER IF EXISTS high_value_transaction_alert"

    create_alert_trigger_query = """
    CREATE TRIGGER high_value_transaction_alert
    AFTER INSERT ON transactions
    FOR EACH ROW
    BEGIN
        IF NEW.amount >= 50000 THEN
            INSERT INTO alerts(account_number, amount, message)
            VALUES (
                NEW.account_number,
                NEW.amount,
                CONCAT('High value ', NEW.transaction_type, ' detected')
            );
        END IF;
    END
    """

    cursor.execute(drop_alert_trigger_query)
    cursor.execute(create_alert_trigger_query)

    drop_customer_insert_trigger = "DROP TRIGGER IF EXISTS customer_insert_log"

    create_customer_insert_trigger = """
CREATE TRIGGER customer_insert_log
AFTER INSERT ON customers
FOR EACH ROW
BEGIN
    INSERT INTO admin_logs
    (table_name, operation_type, record_id, old_data, new_data)
    VALUES (
        'customers',
        'INSERT',
        NEW.customer_id,
        NULL,
        CONCAT(
            'Name:', NEW.full_name,
            ', Email:', NEW.email,
            ', Phone:', NEW.phone,
            ', City:', NEW.city
        )
    );
END;

"""
    drop_customer_update_trigger = "DROP TRIGGER IF EXISTS customer_update_log"

    create_customer_update_trigger = """
CREATE TRIGGER customer_update_log
AFTER UPDATE ON customers
FOR EACH ROW
BEGIN
    -- Log ONLY business fields (ignore security fields)
    IF
        OLD.full_name <> NEW.full_name OR
        OLD.email <> NEW.email OR
        OLD.phone <> NEW.phone OR
        OLD.city <> NEW.city
    THEN
        INSERT INTO admin_logs
        (table_name, operation_type, record_id, old_data, new_data)
        VALUES (
            'customers',
            'UPDATE',
            NEW.customer_id,
            CONCAT(
                'Name:', OLD.full_name,
                ', Email:', OLD.email,
                ', Phone:', OLD.phone,
                ', City:', OLD.city
            ),
            CONCAT(
                'Name:', NEW.full_name,
                ', Email:', NEW.email,
                ', Phone:', NEW.phone,
                ', City:', NEW.city
            )
        );
    END IF;
END;
"""

    drop_customer_delete_trigger = "DROP TRIGGER IF EXISTS customer_delete_log"

    create_customer_delete_trigger = """
CREATE TRIGGER customer_delete_log
AFTER DELETE ON customers
FOR EACH ROW
BEGIN
    INSERT INTO admin_logs
    (table_name, operation_type, record_id, old_data, new_data)
    VALUES (
        'customers',
        'DELETE',
        OLD.customer_id,
        CONCAT(
            'Name:', OLD.full_name,
            ', Email:', OLD.email,
            ', Phone:', OLD.phone,
            ', City:', OLD.city
        ),
        NULL
    );
END;

"""

    drop_account_insert_trigger = "DROP TRIGGER IF EXISTS account_insert_log"

    create_account_insert_trigger = """
CREATE TRIGGER account_insert_log
AFTER INSERT ON accounts
FOR EACH ROW
BEGIN
    INSERT INTO admin_logs
    (table_name, operation_type, record_id, old_data, new_data)
    VALUES (
        'accounts',
        'INSERT',
        NEW.account_number,
        NULL,
        CONCAT(
            'Customer ID:', NEW.customer_id,
            ', Branch:', NEW.branch,
            ', Type:', NEW.account_type,
            ', Balance:', NEW.balance
        )
    );
END;

"""

    drop_account_update_trigger = "DROP TRIGGER IF EXISTS account_update_log"

    create_account_update_trigger = """
CREATE TRIGGER account_update_log
AFTER UPDATE ON accounts
FOR EACH ROW
BEGIN
    -- Log ONLY admin-level structural changes
    IF
        OLD.branch <> NEW.branch OR
        OLD.account_type <> NEW.account_type
    THEN
        INSERT INTO admin_logs
        (table_name, operation_type, record_id, old_data, new_data)
        VALUES (
            'accounts',
            'UPDATE',
            NEW.account_number,
            CONCAT(
                'Branch:', OLD.branch,
                ', Type:', OLD.account_type
            ),
            CONCAT(
                'Branch:', NEW.branch,
                ', Type:', NEW.account_type
            )
        );
    END IF;
END;

"""

    drop_account_delete_trigger = "DROP TRIGGER IF EXISTS account_delete_log"

    create_account_delete_trigger = """
CREATE TRIGGER account_delete_log
AFTER DELETE ON accounts
FOR EACH ROW
BEGIN
    INSERT INTO admin_logs
    (table_name, operation_type, record_id, old_data, new_data)
    VALUES (
        'accounts',
        'DELETE',
        OLD.account_number,
        CONCAT(
            'Customer ID:', OLD.customer_id,
            ', Branch:', OLD.branch,
            ', Type:', OLD.account_type,
            ', Balance:', OLD.balance
        ),
        NULL
    );
END;

"""
    drop_customer_security_trigger="DROP TRIGGER IF EXISTS customer_security_update"

    create_customer_security_trigger = """
CREATE TRIGGER customer_security_update
AFTER UPDATE ON customers
FOR EACH ROW
BEGIN
    -- Failed login attempt
    IF NEW.failed_attempts > OLD.failed_attempts THEN
        INSERT INTO security_logs
        (customer_id, event_type, failed_attempts, details)
        VALUES
        (NEW.customer_id, 'FAILED_LOGIN', NEW.failed_attempts, 'Invalid login attempt');
    END IF;

    -- Account locked
    IF NEW.lock_until IS NOT NULL AND OLD.lock_until IS NULL THEN
        INSERT INTO security_logs
        (customer_id, event_type, failed_attempts, details)
        VALUES
        (NEW.customer_id, 'ACCOUNT_LOCKED', NEW.failed_attempts, 'Account locked due to max attempts');
    END IF;

    -- Account unlocked
    IF NEW.lock_until IS NULL AND OLD.lock_until IS NOT NULL THEN
        INSERT INTO security_logs
        (customer_id, event_type, failed_attempts, details)
        VALUES
        (NEW.customer_id, 'ACCOUNT_UNLOCKED', 0, 'Account unlocked by admin');
    END IF;
END
"""
    

    cursor.execute(drop_customer_insert_trigger)
    cursor.execute(create_customer_insert_trigger)

    cursor.execute(drop_customer_update_trigger)
    cursor.execute(create_customer_update_trigger)

    cursor.execute(drop_customer_delete_trigger)
    cursor.execute(create_customer_delete_trigger)

    cursor.execute(drop_account_insert_trigger)
    cursor.execute(create_account_insert_trigger)

    cursor.execute(drop_account_update_trigger)
    cursor.execute(create_account_update_trigger)

    cursor.execute(drop_account_delete_trigger)
    cursor.execute(create_account_delete_trigger)

    cursor.execute(drop_customer_security_trigger)

    cursor.execute(create_customer_security_trigger)


    temp_con.commit()
    cursor.close()
    temp_con.close()


# ----------------------------------------------------
# DB CONNECTION (SAFE)
# ----------------------------------------------------
def get_connection():
    initialize_database()
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="BankDB"
    )

# ----------------------------------------------------
# ACCOUNT VALIDATION
# ----------------------------------------------------
def account_exists(cursor, acc_no):
    check_account_query = "SELECT 1 FROM accounts WHERE account_number = %s"
    cursor.execute(check_account_query, (acc_no,))
    return cursor.fetchone() is not None

# ----------------------------------------------------
# LOGIN PAGE
# ----------------------------------------------------
if not st.session_state.logged_in:

    st.title("Login")

    login_type = st.radio(
        "Login As",
        ["Admin", "User"],
        horizontal=True
    )

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_btn = st.form_submit_button("Login")

    if login_btn:

        # ---------------- ADMIN LOGIN ----------------
        if login_type == "Admin":
            if username == "admin" and password == "admin@1234":
                st.session_state.logged_in = True
                st.session_state.role = "admin"
                st.success("Admin login successful")
                st.rerun()
            else:
                st.error("Invalid admin credentials")

        # ---------------- USER LOGIN ----------------
        else:
            con = get_connection()
            cursor = con.cursor(dictionary=True)

            cursor.execute("""
                SELECT customer_id, full_name, failed_attempts, lock_until
                FROM customers
                WHERE full_name = %s AND email = %s
            """, (username.strip(), password.strip()))

            user = cursor.fetchone()

            # ---------- USER FOUND ----------
            if user:

                # ----- CHECK LOCK -----
                if user["lock_until"] and datetime.now() < user["lock_until"]:
                    remaining = int(
                        (user["lock_until"] - datetime.now()).total_seconds() // 60
                    )
                    st.error(f"Account locked. Try again in {remaining} minutes")

                else:
                    # ----- AUTO UNLOCK -----
                    cursor.execute("""
                        UPDATE customers
                        SET failed_attempts = 0, lock_until = NULL
                        WHERE customer_id = %s
                    """, (user["customer_id"],))
                    con.commit()

                    st.session_state.logged_in = True
                    st.session_state.role = "user"
                    st.session_state.user_customer_id = user["customer_id"]
                    st.session_state.user_name = user["full_name"]

                    st.success("User login successful")
                    cursor.close()
                    con.close()
                    st.rerun()

            # ---------- INVALID LOGIN ----------
            else:
                cursor.execute("""
                    SELECT customer_id, failed_attempts
                    FROM customers
                    WHERE full_name = %s
                """, (username.strip(),))

                fail_user = cursor.fetchone()

                if fail_user:
                    new_attempts = fail_user["failed_attempts"] + 1

                    if new_attempts >= MAX_ATTEMPTS:
                        lock_time = datetime.now() + timedelta(minutes=LOCK_MINUTES)
                        cursor.execute("""
                            UPDATE customers
                            SET failed_attempts = %s, lock_until = %s
                            WHERE customer_id = %s
                        """, (new_attempts, lock_time, fail_user["customer_id"]))

                        st.error(
                            f"Account locked after {MAX_ATTEMPTS} failed attempts. "
                            f"Try again after {LOCK_MINUTES} minutes"
                        )
                    else:
                        cursor.execute("""
                            UPDATE customers
                            SET failed_attempts = %s
                            WHERE customer_id = %s
                        """, (new_attempts, fail_user["customer_id"]))

                        remaining = MAX_ATTEMPTS - new_attempts
                        st.error(f"Invalid credentials. {remaining} attempts remaining")

                    con.commit()
                else:
                    st.error("Invalid user credentials")

                cursor.close()
                con.close()

    st.stop()

# ----------------------------------------------------
# ROLE-BASED SIDEBAR MENU
# ----------------------------------------------------
st.sidebar.markdown("### Navigation")

if st.session_state.role == "admin":
    menu = st.sidebar.selectbox(
        "Select Operation",
        (
            "Home",
            "Add Customer",
            "View Customers",
            "Edit / Delete Customers",
            "Create Account",
            "View Accounts",
            "Edit / Delete Accounts",
            "Deposit / Withdraw",
            "Check Balance",
            "View Transactions",
            "View Alerts",
            "Admin Logs",
            "Locked Accounts",
            "Security Logs"


        )
)

elif st.session_state.role == "user":
    menu = st.sidebar.selectbox(
        "Select Operation",
        (
            "Home",
            "Create Account",
            "View Accounts",        
            "Deposit / Withdraw",
            "Check Balance",
            "View Transactions"
        )
    )


# Logout button
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

# ----------------------------------------------------
# GLOBAL MESSAGE DISPLAY
# ----------------------------------------------------
if st.session_state.success_msg:
    st.success(st.session_state.success_msg)
    st.session_state.success_msg = None

if st.session_state.error_msg:
    st.error(st.session_state.error_msg)
    st.session_state.error_msg = None

# ----------------------------------------------------
# ADD CUSTOMER
# ----------------------------------------------------
if menu == "Add Customer":
    st.subheader("Add Customer")

    with st.form("add_customer_form", clear_on_submit=True):
        name = st.text_input("Full Name")
        email = st.text_input("Email")
        phone = st.text_input(
    "Phone Number",
    max_chars=10,
    help="Enter 10 digit phone number"
)

        city = st.text_input("City")

        submit_customer = st.form_submit_button("Add Customer")

    if submit_customer:
        name = name.strip()
        email = email.strip()
        phone = phone.strip()
        city = city.strip()

    # STEP 1: empty check
        if name == "" or phone == "" or city == "":
            st.error("Full Name, Phone, and City cannot be empty")

    # STEP 2: phone number validation (ADD THIS)
        elif not phone.isdigit() or len(phone) != 10:
          st.error("Phone number must be exactly 10 digits")

    # STEP 3: database insert
        else:
            con = get_connection()
            cursor = con.cursor()

            insert_customer_query = """
        INSERT INTO customers (full_name, email, phone, city)
        VALUES (%s, %s, %s, %s)
        """

            cursor.execute(insert_customer_query, (name, email, phone, city))
            con.commit()

            cursor.close()
            con.close()

            st.success("Customer added successfully")

# ----------------------------------------------------
# VIEW CUSTOMERS (WITH REAL-TIME SEARCH)
# ----------------------------------------------------
elif menu == "View Customers":
    st.subheader("Customer Details")

    # --- Search box ---
    search_name = st.text_input(
        "Search by Customer Name",
        placeholder="Type customer name..."
    )

    con = get_connection()
    cursor = con.cursor()

    # --- Query with LIKE for real-time search ---
    if search_name.strip() != "":
        view_customers_query = """
            SELECT customer_id, full_name, email, phone, city
            FROM customers
            WHERE full_name LIKE %s
            ORDER BY customer_id
        """
        cursor.execute(view_customers_query, (f"%{search_name}%",))
    else:
        view_customers_query = """
            SELECT customer_id, full_name, email, phone, city
            FROM customers
            ORDER BY customer_id
        """
        cursor.execute(view_customers_query)

    rows = cursor.fetchall()
    cursor.close()
    con.close()

    # --- Display ---
    if rows:
        df = pd.DataFrame(
            rows,
            columns=["Customer ID", "Name", "Email", "Number", "City"]
        )

        st.dataframe(df, use_container_width=True)
    else:
        st.info("No matching customers found")


# ----------------------------------------------------
# EDIT / DELETE CUSTOMERS (SAFE DELETE - FIXED)
# ----------------------------------------------------

if menu == "Edit / Delete Customers":
    st.subheader("Edit / Delete Customer")

    # ---------- SEARCH ----------
    search_type = st.radio(
        "Search Customer By",
        ["Customer ID", "Customer Name"],
        horizontal=True,
        key="customer_search_type"
    )

    search_value = st.text_input(
        "Enter Customer's Details",
        key="customer_search_value"
    )

    if st.button("Fetch Customer", key="fetch_customer_btn"):
        con = get_connection()
        cursor = con.cursor(dictionary=True)

        if search_type == "Customer ID":
            cursor.execute(
                "SELECT * FROM customers WHERE customer_id=%s",
                (search_value,)
            )
        else:
            cursor.execute(
                "SELECT * FROM customers WHERE full_name=%s",
                (search_value,)
            )

        row = cursor.fetchone()
        cursor.close()
        con.close()

        if row:
            st.session_state.customer_data = row
        else:
            st.error("Customer not found")

    # ---------- UPDATE / DELETE SECTION ----------
    if "customer_data" in st.session_state:
        c = st.session_state.customer_data

        st.markdown("### Update Customer")

        with st.form("update_customer_form"):
            name = st.text_input("Full Name", c["full_name"])
            email = st.text_input("Email", c["email"])
            phone = st.text_input("Phone", c["phone"])
            city = st.text_input("City", c["city"])

            update_btn = st.form_submit_button("Update Customer")

        if update_btn:
            name = name.strip()
            email = email.strip()
            phone = phone.strip()
            city = city.strip()

            if name == "" or phone == "" or city == "":
                st.error("Full Name, Phone, and City cannot be empty")
            elif not phone.isdigit() or len(phone) != 10:
                st.error("Phone number must be exactly 10 digits")
            else:
                con = get_connection()
                cursor = con.cursor()

                cursor.execute("""
                    UPDATE customers
                    SET full_name=%s, email=%s, phone=%s, city=%s
                    WHERE customer_id=%s
                """, (name, email, phone, city, c["customer_id"]))

                con.commit()
                cursor.close()
                con.close()

                st.session_state.success_msg = "Customer updated successfully"
                del st.session_state.customer_data
                st.rerun()


        st.markdown("---")
        st.markdown("### Delete Customer")

        if st.button("Delete Customer", key="delete_customer_btn"):
            con = get_connection()
            cursor = con.cursor()

            # ---- DELETE SECURITY LOGS (FIX FK ISSUE) ----
            cursor.execute(
                "DELETE FROM security_logs WHERE customer_id=%s",
                (c["customer_id"],)
            )

            # ---- DELETE ALERTS ----
            cursor.execute("""
                DELETE FROM alerts
                WHERE account_number IN (
                    SELECT account_number FROM accounts WHERE customer_id=%s
                )
            """, (c["customer_id"],))

            # ---- DELETE TRANSACTIONS ----
            cursor.execute("""
                DELETE FROM transactions
                WHERE account_number IN (
                    SELECT account_number FROM accounts WHERE customer_id=%s
                )
            """, (c["customer_id"],))

            # ---- DELETE ACCOUNTS ----
            cursor.execute(
                "DELETE FROM accounts WHERE customer_id=%s",
                (c["customer_id"],)
            )

            # ---- DELETE CUSTOMER ----
            cursor.execute(
                "DELETE FROM customers WHERE customer_id=%s",
                (c["customer_id"],)
            )

            con.commit()
            cursor.close()
            con.close()

            st.session_state.success_msg = "Customer and all related records deleted successfully"
            del st.session_state.customer_data
            st.rerun()

# ----------------------------------------------------
# CREATE ACCOUNT (ROLE RESTRICTED)
# ----------------------------------------------------
elif menu == "Create Account":
    st.subheader("Create Account")

    # ---------------- ADMIN ----------------
    if st.session_state.role == "admin":

        with st.form("fetch_customer_form", clear_on_submit=True):
            customer_name = st.text_input("Customer Full Name")
            fetch_btn = st.form_submit_button("Fetch Customer")

        if fetch_btn:
            con = get_connection()
            cursor = con.cursor()
            cursor.execute(
                "SELECT customer_id FROM customers WHERE full_name = %s",
                (customer_name.strip(),)
            )
            row = cursor.fetchone()
            cursor.close()
            con.close()

            if row:
                st.session_state.ca_customer_id = row[0]
                st.success("Customer found. Enter account details below")
            else:
                st.error("Customer not found")

        if "ca_customer_id" in st.session_state and st.session_state.ca_customer_id:
            with st.form("create_account_form", clear_on_submit=True):
                branch = st.selectbox("Branch", ["Dasnagar", "Kona", "Balitikuri", "Amta"])
                account_type = st.selectbox("Account Type", ["savings", "current"])
                create_btn = st.form_submit_button("Create Account")

            if create_btn:
                con = get_connection()
                cursor = con.cursor()
                cursor.execute("""
                    INSERT INTO accounts (customer_id, branch, account_type)
                    VALUES (%s, %s, %s)
                """, (st.session_state.ca_customer_id, branch, account_type))
                con.commit()

                cursor.execute(
                    "SELECT account_number FROM accounts ORDER BY account_number DESC LIMIT 1"
                )
                acc_no = cursor.fetchone()[0]
                cursor.close()
                con.close()

                st.success(f"Account created successfully! Account No: **{acc_no}**")
                del st.session_state.ca_customer_id

    # ---------------- USER ----------------
    else:
        st.info(f"Creating account for **{st.session_state.user_name}**")

        with st.form("user_create_account_form", clear_on_submit=True):
            branch = st.selectbox("Branch", ["Dasnagar", "Kona", "Balitikuri", "Amta"])
            account_type = st.selectbox("Account Type", ["savings", "current"])
            create_btn = st.form_submit_button("Create Account")

        if create_btn:
            con = get_connection()
            cursor = con.cursor()
            cursor.execute("""
    INSERT INTO accounts (customer_id, branch, account_type)
    VALUES (%s, %s, %s)
""", (
    st.session_state.user_customer_id,
    branch,
    account_type
))

            con.commit()

            cursor.execute(
                "SELECT account_number FROM accounts ORDER BY account_number DESC LIMIT 1"
            )
            acc_no = cursor.fetchone()[0]
            cursor.close()
            con.close()

            st.success(f"Account created successfully! Account No: **{acc_no}**")

# ----------------------------------------------------
# VIEW ACCOUNTS (ADMIN + USER RESTRICTIONS)
# ----------------------------------------------------
elif menu == "View Accounts":
    st.subheader("Account Details")

    con = get_connection()
    cursor = con.cursor()

    # ================= ADMIN VIEW =================
    if st.session_state.role == "admin":

        col1, col2, col3 = st.columns(3)

        with col1:
            search_name = st.text_input(
                "Search by Customer Name",
                placeholder="Type customer name..."
            )

        with col2:
            branch_filter = st.selectbox(
                "Filter by Branch",
                ["All", "Dasnagar", "Kona", "Balitikuri", "Amta"]
            )

        # 🔹 NEW: Account Type Filter
        with col3:
            account_type_filter = st.selectbox(
                "Filter by Account Type",
                ["All", "savings", "current"]
            )

        query = """
            SELECT
                a.account_number,
                c.full_name,
                a.account_type,
                a.branch,
                a.balance
            FROM accounts a
            JOIN customers c
                ON a.customer_id = c.customer_id
            WHERE 1=1
        """

        params = []

        # ---- Customer Name Filter ----
        if search_name.strip():
            query += " AND c.full_name LIKE %s"
            params.append(f"%{search_name}%")

        # ---- Branch Filter ----
        if branch_filter != "All":
            query += " AND a.branch = %s"
            params.append(branch_filter)

        # 🔹 NEW: Account Type Filter
        if account_type_filter != "All":
            query += " AND a.account_type = %s"
            params.append(account_type_filter)

        cursor.execute(query, params)

    # ================= USER VIEW =================
    else:
        query = """
            SELECT
                a.account_number,
                c.full_name,
                a.account_type,
                a.branch,
                a.balance
            FROM accounts a
            JOIN customers c
                ON a.customer_id = c.customer_id
            WHERE a.customer_id = %s
        """

        cursor.execute(query, (st.session_state.user_customer_id,))

    rows = cursor.fetchall()
    cursor.close()
    con.close()

    if rows:
        df = pd.DataFrame(
            rows,
            columns=[
                "Account Number",
                "Customer Name",
                "Account Type",
                "Branch",
                "Balance"
            ]
        )
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No accounts found")



# ----------------------------------------------------
# EDIT / DELETE ACCOUNTS (SAFE DELETE)
# ----------------------------------------------------
if menu == "Edit / Delete Accounts":
    st.subheader("Edit / Delete Account")

    search_type = st.radio(
        "Search Account By",
        ["Account Number", "Customer Name"],
        horizontal=True
    )

    search_value = st.text_input("Enter Account Detail")

    if st.button("Fetch Account"):
        con = get_connection()
        cursor = con.cursor(dictionary=True)

        if search_type == "Account Number":
            cursor.execute("""
                SELECT a.*, c.full_name
                FROM accounts a
                JOIN customers c ON a.customer_id = c.customer_id
                WHERE a.account_number = %s
            """, (search_value,))
        else:
            cursor.execute("""
                SELECT a.*, c.full_name
                FROM accounts a
                JOIN customers c ON a.customer_id = c.customer_id
                WHERE c.full_name = %s
            """, (search_value,))

        account = cursor.fetchone()
        cursor.close()
        con.close()

        if account:
            st.session_state.account_data = account
        else:
            st.error("Account not found")

    # ---------- SHOW FORM ----------
    if "account_data" in st.session_state:
        a = st.session_state.account_data

        with st.form("edit_account_form"):
            st.text_input("Customer Name", a["full_name"], disabled=True)
            branch = st.selectbox("Branch", ["Dasnagar", "Kona", "Balitikuri", "Amta"])
            acc_type = st.selectbox(
                "Account Type",
                ["savings", "current"],
                index=0 if a["account_type"] == "savings" else 1
            )

            col1, col2 = st.columns(2)
            update_btn = col1.form_submit_button("Update Account")
            delete_btn = col2.form_submit_button("Delete Account")

        # ---------- UPDATE ----------
        if update_btn:
            con = get_connection()
            cursor = con.cursor()
            cursor.execute("""
                UPDATE accounts
                SET branch=%s, account_type=%s
                WHERE account_number=%s
            """, (branch, acc_type, a["account_number"]))
            con.commit()
            cursor.close()
            con.close()

            st.session_state.success_msg = "Account updated successfully"
            del st.session_state.account_data
            st.rerun()

        # ---------- DELETE (SAFE) ----------
        if delete_btn:
            con = get_connection()
            cursor = con.cursor()

            # ---- DELETE ALERTS ----
            cursor.execute(
                "DELETE FROM alerts WHERE account_number=%s",
                (a["account_number"],)
            )

            # ---- DELETE TRANSACTIONS ----
            cursor.execute(
                "DELETE FROM transactions WHERE account_number=%s",
                (a["account_number"],)
            )

            # ---- DELETE ACCOUNT ----
            cursor.execute(
                "DELETE FROM accounts WHERE account_number=%s",
                (a["account_number"],)
            )

            con.commit()
            cursor.close()
            con.close()

            st.session_state.success_msg = "Account deleted successfully"
            del st.session_state.account_data
            st.rerun()
# ----------------------------------------------------
# DEPOSIT / WITHDRAW (ADMIN shows name + account number)
# ----------------------------------------------------
elif menu == "Deposit / Withdraw":
    st.subheader("Deposit / Withdraw")

    con = get_connection()
    cursor = con.cursor()

    # ---------- FETCH ACCOUNT LIST ----------
    if st.session_state.role == "admin":
        cursor.execute("""
            SELECT a.account_number, c.full_name
            FROM accounts a
            JOIN customers c ON a.customer_id = c.customer_id
        """)
        account_rows = cursor.fetchall()

        # Create display mapping
        account_map = {
            f"{row[0]} - {row[1]}": row[0]
            for row in account_rows
        }

        account_display_list = ["Select"] + list(account_map.keys())

    else:
        cursor.execute(
            "SELECT account_number FROM accounts WHERE customer_id = %s",
            (st.session_state.user_customer_id,)
        )
        account_numbers = [row[0] for row in cursor.fetchall()]
        account_display_list = ["Select"] + account_numbers

    cursor.close()

    if len(account_display_list) == 1:
        st.warning("No accounts available")
        con.close()
        st.stop()

    # ---------- ACCOUNT SELECT ----------
    selected_account = st.selectbox(
        "Select Account Number",
        account_display_list
    )

    if selected_account == "Select":
        con.close()
        st.stop()

    # ---------- GET ACTUAL ACCOUNT NUMBER ----------
    if st.session_state.role == "admin":
        acc_no = account_map[selected_account]
    else:
        acc_no = selected_account

    # ---------- FETCH BALANCE ----------
    cursor = con.cursor()
    cursor.execute(
        "SELECT balance FROM accounts WHERE account_number = %s",
        (acc_no,)
    )
    balance = Decimal(cursor.fetchone()[0])
    cursor.close()

    st.info(f"Current Balance: ₹{balance}")

    # ---------- TRANSACTION FORM ----------
    with st.form("txn_form"):
        txn_type = st.radio("Transaction Type", ["Deposit", "Withdraw"])
        amount = st.number_input(
            "Enter Amount",
            min_value=100.0,
            step=100.0
        )
        submit_txn = st.form_submit_button("Submit Transaction")

    # ---------- PROCESS ----------
    if submit_txn:
        amount = Decimal(str(amount))

        if amount <= 0:
            st.error("Amount must be greater than 0")

        else:
            try:
                cursor = con.cursor()
                cursor.callproc(
                    "perform_transactions",
                    (acc_no, txn_type.lower(), amount)
                )
                con.commit()

                cursor.execute(
                    "SELECT balance FROM accounts WHERE account_number = %s",
                    (acc_no,)
                )
                new_balance = cursor.fetchone()[0]
                cursor.close()

                st.success(
                    f"{txn_type} successful!\n\nUpdated Balance: ₹{new_balance}"
                )

            except Exception as e:
                st.error(str(e))

    con.close()

# ----------------------------------------------------
# CHECK BALANCE (ROLE RESTRICTED)
# ----------------------------------------------------
elif menu == "Check Balance":
    st.subheader("Check Balance")

    con = get_connection()
    cursor = con.cursor()

    # ================= ADMIN =================
    if st.session_state.role == "admin":

        cursor.execute("""
            SELECT a.account_number, c.full_name
            FROM accounts a
            JOIN customers c ON a.customer_id = c.customer_id
        """)
        account_rows = cursor.fetchall()

        if not account_rows:
            st.warning("No accounts found")
            cursor.close()
            con.close()
            st.stop()

        # Create mapping
        account_map = {
            f"{row[0]} - {row[1]}": row[0]
            for row in account_rows
        }

        selected_display = st.selectbox(
            "Select Account",
            ["Select"] + list(account_map.keys())
        )

        if selected_display != "Select":
            acc_no = account_map[selected_display]

            cursor.execute(
                "SELECT balance FROM accounts WHERE account_number = %s",
                (acc_no,)
            )
            balance = cursor.fetchone()[0]

            st.success(
                f"Account Holder: **{selected_display.split(' - ')[1]}**\n\n"
                f"Current Balance: **₹{balance}**"
            )

    # ================= USER =================
    else:
        cursor.execute(
            "SELECT account_number FROM accounts WHERE customer_id = %s",
            (st.session_state.user_customer_id,)
        )

        accounts = [row[0] for row in cursor.fetchall()]

        if not accounts:
            st.warning("No accounts found")
            cursor.close()
            con.close()
            st.stop()

        acc_no = st.selectbox("Select Account", accounts)

        cursor.execute(
            "SELECT balance FROM accounts WHERE account_number = %s",
            (acc_no,)
        )
        balance = cursor.fetchone()[0]

        st.success(f"Current Balance: ₹{balance}")

    cursor.close()
    con.close()

# ----------------------------------------------------
# VIEW TRANSACTIONS (ROLE RESTRICTED)
# ----------------------------------------------------
elif menu == "View Transactions":
    st.subheader("Transaction History")

    con = get_connection()

    # ================= FILTERS =================
    col1, col2, col3 = st.columns(3)

    # -------- ADMIN FILTERS --------
    if st.session_state.role == "admin":
        with col1:
            # Fetch all account numbers
            cur = con.cursor()
            cur.execute("SELECT account_number FROM accounts")
            account_list = [row[0] for row in cur.fetchall()]
            cur.close()

            selected_account = st.selectbox(
                "Select Account Number",
                ["All"] + account_list
            )

    # -------- COMMON FILTERS --------
    with col2:
        txn_filter = st.selectbox(
            "Transaction Type",
            ["Both", "Deposit", "Withdraw"]
        )

    with col3:
        date_filter = st.date_input("Select Date (optional)")

    # ================= BASE QUERY =================
    query = """
        SELECT
            t.transaction_id,
            t.account_number,
            c.full_name,
            a.branch,
            t.transaction_type,
            t.amount,
            DATE(t.transaction_time) AS txn_date,
            t.transaction_time
        FROM transactions t
        JOIN accounts a ON t.account_number = a.account_number
        JOIN customers c ON a.customer_id = c.customer_id
        WHERE 1=1
    """

    params = []

    # ================= USER RESTRICTION =================
    if st.session_state.role == "user":
        query += " AND a.customer_id = %s"
        params.append(st.session_state.user_customer_id)

    # ================= ADMIN ACCOUNT FILTER =================
    if st.session_state.role == "admin" and selected_account != "All":
        query += " AND t.account_number = %s"
        params.append(selected_account)

    # ================= TRANSACTION TYPE FILTER =================
    if txn_filter != "Both":
        query += " AND t.transaction_type = %s"
        params.append(txn_filter.lower())

    # ================= DATE FILTER =================
    if date_filter:
        query += " AND DATE(t.transaction_time) = %s"
        params.append(date_filter)

    # ================= EXECUTE =================
    cursor = con.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()

    # ================= DISPLAY =================
    if rows:
        df = pd.DataFrame(
            rows,
            columns=[
                "Transaction ID",
                "Account Number",
                "Customer Name",
                "Branch",
                "Transaction Type",
                "Amount",
                "Transaction Date",
                "Transaction Time"
            ]
        )
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No transactions found for selected filters")

    # ================= ADMIN EXTRA: BRANCH BALANCE =================
    if st.session_state.role == "admin":
        st.markdown("---")
        if st.checkbox("Show Branch-wise Total Balance"):
            cur = con.cursor()
            cur.execute("""
                SELECT branch, SUM(balance)
                FROM accounts
                GROUP BY branch
            """)
            balance_rows = cur.fetchall()
            cur.close()

            balance_df = pd.DataFrame(
                balance_rows,
                columns=["Branch", "Total Balance"]
            )
            st.dataframe(balance_df, use_container_width=True)

    con.close()

# ----------------------------------------------------
# VIEW ALERTS
# ----------------------------------------------------
elif menu == "View Alerts":
    st.subheader("High Value Transaction Alerts")

    con = get_connection()

    # ---------- FILTERS ----------
    col1, col2 = st.columns(2)

    with col1:
        alert_type = st.selectbox(
            "Alert Type",
            ["Both", "Deposit", "Withdraw"]
        )

    with col2:
        alert_date = st.date_input("Select Date (optional)")

    # ---------- QUERY ----------
    query = """
        SELECT
            a.alert_id,
            a.account_number,
            c.full_name,
            ac.branch,
            a.amount,
            a.message,
            DATE(a.alert_time) AS alert_date,
            a.alert_time
        FROM alerts a
        JOIN accounts ac ON a.account_number = ac.account_number
        JOIN customers c ON ac.customer_id = c.customer_id
        WHERE 1=1
    """

    params = []

    if alert_type != "Both":
        query += " AND a.message LIKE %s"
        params.append(f"%{alert_type.lower()}%")

    if alert_date:
        query += " AND DATE(a.alert_time) = %s"
        params.append(alert_date)

    cursor = con.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()

    cursor.close()
    con.close()

    if rows:
        df = pd.DataFrame(
            rows,
            columns=[
                "Alert ID",
                "Account Number",
                "Customer Name",
                "Branch",
                "Amount",
                "Alert Message",
                "Alert Date",
                "Alert Time"
            ]
        )

        st.dataframe(df, use_container_width=True)
    else:
        st.info("No alerts found for selected filters")
# ----------------------------------------------------
# ADMIN LOGS (FILTERS + SORTING)
# ----------------------------------------------------
elif menu == "Admin Logs":
    st.subheader("Admin Activity Logs")

    con = get_connection()
    cursor = con.cursor()

    # ---------------- FILTERS ----------------
    col1, col2, col3 = st.columns(3)

    with col1:
        operation_filter = st.selectbox(
            "Filter by Operation",
            ["All", "INSERT", "UPDATE", "DELETE"]
        )

    with col2:
        start_date = st.date_input("Start Date", value=None)

    with col3:
        end_date = st.date_input("End Date", value=None)

    sort_order = st.radio(
        "Sort by Log ID",
        ["Descending", "Ascending"],
        horizontal=True
    )

    # ---------------- BASE QUERY ----------------
    query = """
    SELECT
        log_id,
        table_name,
        operation_type,
        record_id,
        old_data,
        new_data,
        action_time
    FROM admin_logs
    WHERE 1=1
"""
    params = []

    # ---------------- OPERATION FILTER ----------------
    if operation_filter != "All":
        query += " AND operation_type = %s"
        params.append(operation_filter)

    # ---------------- DATE RANGE FILTER ----------------
    if start_date:
        query += " AND DATE(action_time) >= %s"
        params.append(start_date)

    if end_date:
        query += " AND DATE(action_time) <= %s"
        params.append(end_date)

    # ---------------- SORTING ----------------
    if sort_order == "Ascending":
        query += " ORDER BY log_id ASC"
    else:
        query += " ORDER BY log_id DESC"

    # ---------------- EXECUTE ----------------
    cursor.execute(query, params)
    rows = cursor.fetchall()

    cursor.close()
    con.close()

    # ---------------- DISPLAY ----------------
    if rows:
        df = pd.DataFrame(
            rows,
            columns=[
                "Log ID",
                "Table",
                "Operation",
                "Record ID",
                "Old Data",
                "New Data",
                "Date & Time"
            ]
        )

        
        st.dataframe(df, use_container_width=True)

    else:
        st.info("No logs found for selected filters")

# ----------------------------------------------------
# HOME / DASHBOARD
# ----------------------------------------------------
elif menu == "Home":

    st.markdown("## BankDB Transaction Monitoring System")

    st.markdown(
        """
        Welcome to **BankDB**, a secure banking application designed for  
        real-time transaction monitoring, role-based access control,  
        and complete administrative auditing.
        """
    )

    st.markdown("---")

    # ================= ROLE BASED DASHBOARD =================
    if st.session_state.role == "admin":

        st.markdown("### Admin Dashboard")

        con = get_connection()
        cursor = con.cursor()

        cursor.execute("SELECT COUNT(*) FROM customers")
        total_customers = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM accounts")
        total_accounts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM transactions")
        total_transactions = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM alerts")
        total_alerts = cursor.fetchone()[0]
        cursor.execute("""
        SELECT COUNT(*)
        FROM customers
        WHERE lock_until IS NOT NULL
          AND lock_until > NOW()
    """)
        locked_accounts = cursor.fetchone()[0]
        

        cursor.close()
        con.close()

        col1, col2, col3, col4, col5 = st.columns(5)

        col1.metric("Total Customers", total_customers)
        col2.metric("Total Accounts", total_accounts)
        col3.metric("Total Transactions", total_transactions)
        col4.metric("System Alerts", total_alerts)
        
        col5.metric("Locked Accounts", locked_accounts)

        if locked_accounts > 0:
            col5.markdown(
        "<span style='color:#ef4444; font-weight:600;'>Attention</span>",
        unsafe_allow_html=True
    )
        st.markdown("---")

        st.markdown("### Admin Capabilities")
        st.markdown(
            """
            - Create, update, and delete customers  
            - Manage savings and current accounts  
            - Monitor deposits and withdrawals  
            - Detect suspicious or high-value transactions  
            - Track all admin actions using audit logs  
            """
        )

    # ================= USER DASHBOARD =================
    else:
        st.markdown(f"### Welcome, {st.session_state.user_name}")

        con = get_connection()
        cursor = con.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM accounts WHERE customer_id = %s",
            (st.session_state.user_customer_id,)
        )
        my_accounts = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT IFNULL(SUM(balance), 0)
            FROM accounts
            WHERE customer_id = %s
            """,
            (st.session_state.user_customer_id,)
        )
        total_balance = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM transactions t
            JOIN accounts a ON t.account_number = a.account_number
            WHERE a.customer_id = %s
            """,
            (st.session_state.user_customer_id,)
        )
        my_transactions = cursor.fetchone()[0]

        cursor.close()
        con.close()

        col1, col2, col3 = st.columns(3)

        col1.metric("My Accounts", my_accounts)
        col2.metric("Total Balance", f"Rs. {total_balance}")
        col3.metric("Total Transactions", my_transactions)

        st.markdown("---")

        st.markdown("### Available Features")
        st.markdown(
            """
            - Open new bank accounts  
            - Deposit and withdraw funds  
            - Check account balance  
            - View complete transaction history  
            """
        )

    st.markdown("---")

    st.info(
        "Security Notice: All sensitive operations are protected using role-based access "
        "and are logged for audit and compliance purposes."
    )
# ----------------------------------------------------
# LOCKED ACCOUNTS (ADMIN ONLY)
# ----------------------------------------------------
elif menu == "Locked Accounts":

    st.subheader("Locked User Accounts")

    con = get_connection()
    cursor = con.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            customer_id,
            full_name,
            email,
            failed_attempts,
            lock_until
        FROM customers
        WHERE lock_until IS NOT NULL
          AND lock_until > NOW()
        ORDER BY lock_until
    """)

    rows = cursor.fetchall()

    if not rows:
        st.success("No locked accounts at the moment")
        cursor.close()
        con.close()
        st.stop()

    df = pd.DataFrame(
        rows,
        columns=[
            "customer_id",
            "full_name",
            "email",
            "failed_attempts",
            "lock_until"
        ]
    )

    st.dataframe(df, use_container_width=True)

    st.markdown("---")
    st.markdown("### Unlock Account")

    locked_ids = [row["customer_id"] for row in rows]

    selected_customer = st.selectbox(
        "Select Customer ID to Unlock",
        locked_ids
    )

    if st.button("Unlock Selected Account"):
        cursor.execute("""
            UPDATE customers
            SET failed_attempts = 0,
                lock_until = NULL
            WHERE customer_id = %s
        """, (selected_customer,))

        con.commit()

        st.success("Account unlocked successfully")
        cursor.close()
        con.close()
        st.rerun()

    cursor.close()
    con.close()

# ----------------------------------------------------
# SECURITY LOGS (ADMIN ONLY)
# ----------------------------------------------------
elif menu == "Security Logs":

    st.subheader("Security Logs")

    con = get_connection()

    col1, col2, col3 = st.columns(3)

    with col1:
        event_filter = st.selectbox(
            "Event Type",
            ["All", "FAILED LOGIN", "ACCOUNT LOCKED", "ACCOUNT UNLOCKED"]
        )

        


    with col2:
        start_date = st.date_input("Start Date", value=None)

    with col3:
        end_date = st.date_input("End Date", value=None)


    event_map = {
    "FAILED LOGIN": "FAILED_LOGIN",
    "ACCOUNT LOCKED": "ACCOUNT_LOCKED",
    "ACCOUNT UNLOCKED": "ACCOUNT_UNLOCKED"
}
    query = """
        SELECT
            s.log_id,
            s.customer_id,
            c.full_name,
            s.event_type,
            s.failed_attempts,
            s.details,
            s.event_time
        FROM security_logs s
        JOIN customers c ON s.customer_id = c.customer_id
        WHERE 1=1
    """
    params = []

    if event_filter != "All":
        query += " AND s.event_type = %s"
        params.append(event_map[event_filter])

    if start_date:
        query += " AND DATE(s.event_time) >= %s"
        params.append(start_date)

    if end_date:
        query += " AND DATE(s.event_time) <= %s"
        params.append(end_date)

    query += " ORDER BY s.event_time DESC"

    df = pd.read_sql(query, con, params=params)
    # Make Event column human‑readable for UI
    df["event_type"] = df["event_type"].str.replace("_", " ")



    st.dataframe(
        df.rename(columns={
            "log_id": "Log ID",
            "customer_id": "Customer ID",
            "full_name": "Customer Name",
            "event_type": "Event",
            "failed_attempts": "Failed Attempts",
            "details": "Details",
            "event_time": "Timestamp"
        }),
        use_container_width=True
    )

    con.close()