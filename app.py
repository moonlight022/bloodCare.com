import os
import re
import secrets
import smtplib
from email.message import EmailMessage
from datetime import date, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import mysql.connector
from flask import Flask, request, redirect, session, send_from_directory, render_template_string
from mysql.connector import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("BLOODCARE_SECRET_KEY", "change-this-development-secret")
BASE_DIR = Path(__file__).resolve().parent
VALID_GROUPS = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
PRIVATE_UPLOAD_DIR = BASE_DIR.parent / "bloodcare_private_uploads"
ALLOWED_PRESCRIPTION_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_PRESCRIPTION_BYTES = 5 * 1024 * 1024



def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "Farhatshk@109"),
        database=os.environ.get("DB_NAME", "bloodcare_db")
    )


def render_file(filename, **context):
    return render_template_string((BASE_DIR / filename).read_text(encoding="utf-8"), **context)


def logged_in_user():
    return session.get("user_id")


def get_donor_eligibility(donor_id, gender, cursor):
    """Return (last donation date, next estimated eligibility date, is eligible).

    First-time donors are eligible for matching if their other donor checks pass.
    """
    cursor.execute(
        """
        SELECT MAX(donation_date) AS last_date
        FROM donations
        WHERE donor_id = %s AND status = 'Completed'
        """,
        (donor_id,)
    )
    result = cursor.fetchone()
    last_date = result["last_date"] if result else None

    if last_date is None:
        return None, None, True

    if gender == "Male":
        waiting_days = 90
    elif gender == "Female":
        waiting_days = 120
    else:
        return last_date, None, False

    next_date = last_date + timedelta(days=waiting_days)
    return last_date, next_date, date.today() >= next_date


def admin_required():
    return session.get("admin_id") is not None


@app.route("/")
@app.route("/index.html")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/style.css")
def serve_css():
    return send_from_directory(BASE_DIR, "style.css")


@app.route("/test-db")
def test_db():
    try:
        connection = get_db_connection()
        connection.close()
        return "MySQL database connected successfully."
    except mysql.connector.Error:
        app.logger.exception("Database connection test failed")
        return "Database connection failed. Check your database settings.", 500


@app.route("/register", methods=["POST"])
def register():
    fullname = request.form.get("fullname", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    city = request.form.get("city", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirmPassword", "")
    terms = request.form.get("terms")

    if not all([fullname, email, phone, city, password]):
        return "Please fill in all required fields.", 400
    if terms != "yes":
        return "Please accept the terms to continue.", 400
    if len(password) < 8:
        return "Password must be at least 8 characters.", 400
    if password != confirm_password:
        return "Passwords do not match. Please go back and try again.", 400
    if len(phone) != 10 or not phone.isdigit():
        return "Enter a valid 10-digit mobile number.", 400

    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """INSERT INTO users (full_name, email, phone, city, password_hash)
               VALUES (%s, %s, %s, %s, %s)""",
            (fullname, email, phone, city, generate_password_hash(password))
        )
        connection.commit()
        session.clear()
        session["user_id"] = cursor.lastrowid
        return redirect("/donor.html")
    except IntegrityError:
        if connection:
            connection.rollback()
        return "This email is already registered. Please sign in instead.", 409
    except mysql.connector.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Registration failed")
        return "Could not save your registration. Please try again.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT user_id, password_hash FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return "Invalid email or password.", 401
        session.clear()
        session["user_id"] = user["user_id"]
        cursor.execute("SELECT donor_id FROM donors WHERE user_id = %s", (user["user_id"],))
        return redirect("/donor-dashboard.html" if cursor.fetchone() else "/donor.html")
    except mysql.connector.Error:
        app.logger.exception("Login failed")
        return "Login could not be completed. Please try again.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login.html")


@app.route("/donor.html")
def donor_page():
    user_id = logged_in_user()
    if not user_id:
        return redirect("/login.html")
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT full_name, phone, city FROM users WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
        if not user:
            session.clear()
            return redirect("/login.html")
        cursor.execute("SELECT blood_group, age, city, gender FROM donors WHERE user_id=%s", (user_id,))
        donor = cursor.fetchone() or {}
        return render_file("donor.html", user=user, donor=donor)
    except mysql.connector.Error:
        app.logger.exception("Loading donor form failed")
        return "Could not load your account details.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/save-donor", methods=["POST"])
def save_donor():
    user_id = logged_in_user()
    if not user_id:
        return redirect("/login.html")
    blood_group = request.form.get("blood_group", "").strip()
    age_text = request.form.get("age", "").strip()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    district = request.form.get("district", "").strip()
    gender = request.form.get("gender", "").strip()
    if blood_group not in VALID_GROUPS or not city:
        return "Please enter a valid blood group and city.", 400
    if gender not in ("Male", "Female"):
        return "Please select a valid gender.", 400
    try:
        age = int(age_text)
    except (TypeError, ValueError):
        return "Please enter a valid age.", 400
    if not 18 <= age <= 65:
        return "Age must be between 18 and 65.", 400

    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT donor_id FROM donors WHERE user_id=%s", (user_id,))
        existing = cursor.fetchone()
       
        if existing:
            cursor.execute(
                """UPDATE donors
                   SET blood_group=%s, age=%s, city=%s,
                       gender=%s, state=%s, district=%s
                   WHERE user_id=%s""",
                (
                    blood_group, age, city,
                    gender, state, district, user_id
                )
            )
        else:
            cursor.execute(
                cursor.execute(
                    """INSERT INTO donors
                        (user_id, blood_group, age, city, gender, status, availability)
                        VALUES (%s, %s, %s, %s, %s, 'Verified', 'Available')""",
                    (user_id, blood_group, age, city, gender)
                )               
            )

        connection.commit()
        return redirect("/donor-dashboard.html")
    except mysql.connector.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Saving donor profile failed")
        return "Could not save donor details. Please check the database schema and try again.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/donor-dashboard.html")
def donor_dashboard():
    user_id = logged_in_user()

    if not user_id:
        return redirect("/login.html")

    connection = cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """SELECT u.full_name, u.phone, u.email,
                      d.donor_id, d.blood_group, d.age,
                      d.city AS donor_city, d.status,
                      d.availability, d.gender
               FROM users u
               LEFT JOIN donors d ON u.user_id = d.user_id
               WHERE u.user_id = %s""",
            (user_id,)
        )

        donor = cursor.fetchone()

        if not donor:
            session.clear()
            return redirect("/login.html")

        total = 0
        last_date = None
        next_date = None
        days_remaining = None

        if donor["donor_id"]:
            cursor.execute(
                """SELECT
                       COUNT(CASE WHEN status = 'Completed'
                                  THEN 1 END) AS total,
                       MAX(CASE WHEN status = 'Completed'
                                THEN donation_date END) AS last_date
                   FROM donations
                   WHERE donor_id = %s""",
                (donor["donor_id"],)
            )

            stats = cursor.fetchone()
            total = stats["total"] or 0
            last_date = stats["last_date"]

            # Calculate eligibility using the latest completed donation.
            if last_date:
                if donor["gender"] == "Male":
                    waiting_days = 90
                elif donor["gender"] == "Female":
                    waiting_days = 120
                else:
                    waiting_days = None

                if waiting_days is not None:
                    next_date = last_date + timedelta(days=waiting_days)
                    eligible = date.today() >= next_date
                    days_remaining = max(
                        0, (next_date - date.today()).days
                    )
                else:
                    eligible = False
            else:
                # A first-time donor has no previous completed donation.
                eligible = True

            # Refresh the saved availability from the calculated eligibility.
            new_availability = (
                "Available" if eligible else "Unavailable"
            )

            cursor.execute(
                """UPDATE donors
                   SET availability = %s
                   WHERE donor_id = %s""",
                (new_availability, donor["donor_id"])
            )

            donor["availability"] = new_availability
            connection.commit()

        cursor.execute(
            """SELECT request_id, blood_group, units, city,
                      needed_by, status, created_at
               FROM blood_requests
               WHERE user_id = %s
               ORDER BY created_at DESC
               LIMIT 10""",
            (user_id,)
        )

        my_requests = cursor.fetchall()

        return render_file(
            "donor-dashboard.html",
            donor=donor,
            total_donations=total,
            last_donation_date=(
                last_date.strftime("%d-%m-%Y")
                if last_date else "No donations yet"
            ),
            next_eligible_date=(
                next_date.strftime("%d-%m-%Y")
                if next_date else "Not available yet"
            ),
            days_remaining=days_remaining,
            my_requests=my_requests
        )

    except mysql.connector.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Donor dashboard failed")
        return (
            "Could not load donor profile. "
            "Check the database tables."
        ), 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


@app.route("/request-blood.html")
def request_blood_page():
    return send_from_directory(BASE_DIR, "request-blood.html")

@app.route("/submit-blood-request", methods=["POST"])
def submit_blood_request():
    user_id = logged_in_user()

    patient = request.form.get("patient_name", "").strip()
    patient_gender = request.form.get("patient_gender", "").strip()
    email = request.form.get("email", "").strip().lower()
    group = request.form.get("blood_group", "").strip()
    city = request.form.get("city", "").strip()
    phone = request.form.get("contact_phone", "").strip()
    units_text = request.form.get("units", "").strip()
    needed_text = request.form.get("needed_by", "").strip()

    if patient_gender not in ("Male", "Female"):
        return "Please select a valid patient gender.", 400

    if not all([patient, email, group, city, phone, units_text, needed_text]):
        return "Please fill in all fields.", 400

    # Server-side validation: the browser's JavaScript can be bypassed.
    phone_pattern = r"^\\+91[6-9][0-9]{9}$"
    email_pattern = r"^[A-Za-z0-9]+(?:[._%+-][A-Za-z0-9]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\\.)+[A-Za-z]{2,}$"

    if not re.fullmatch(phone_pattern, phone):
        return render_template_string("""
        <!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Invalid Phone Number | BloodCare</title>
        <style>body{font-family:Arial,sans-serif;background:#f7f7f9;padding:24px;color:#333}
        main{max-width:600px;margin:40px auto;background:#fff;padding:28px;border-radius:12px}
        h1,.error{color:#b51224}a{color:#b51224}</style></head><body><main>
        <h1>Please check your phone number</h1><p class="error">{{ message }}</p>
        <p>Enter +91 followed by a valid 10-digit Indian mobile number.</p>
        <a href="/request-blood.html">Go back to the blood request form</a>
        </main></body></html>
        """, message="Invalid phone number. Example: +919876543210."), 400

    if len(email) > 254 or not re.fullmatch(email_pattern, email):
        return render_template_string("""
        <!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Invalid Email | BloodCare</title>
        <style>body{font-family:Arial,sans-serif;background:#f7f7f9;padding:24px;color:#333}
        main{max-width:600px;margin:40px auto;background:#fff;padding:28px;border-radius:12px}
        h1,.error{color:#b51224}a{color:#b51224}</style></head><body><main>
        <h1>Please check your email</h1><p class="error">{{ message }}</p>
        <p>Enter a valid email address, such as name@gmail.com or name@gmail.in.</p>
        <a href="/request-blood.html">Go back to the blood request form</a>
        </main></body></html>
        """, message="Invalid email address. Please check its format."), 400

    if group not in VALID_GROUPS:
        return "Invalid blood group.", 400

    try:
        units = int(units_text)
        needed = date.fromisoformat(needed_text)
    except ValueError:
        return "Please enter valid units and required date.", 400

    if not 1 <= units <= 20:
        return "Units must be between 1 and 20.", 400

    if needed < date.today():
        return "Required date cannot be in the past.", 400

    connection = cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Save the request for both guest and logged-in recipients.
        
        cursor.execute(
            """INSERT INTO blood_requests
               (user_id, patient_name, patient_gender, email,
                blood_group, units, city, contact_phone, needed_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id or None, patient, patient_gender, email,
             group, units, city, phone, needed)
        )


        request_id = cursor.lastrowid
        connection.commit()
        fulfillment_token = secrets.token_urlsafe(32)

        cursor.execute(
            """UPDATE blood_requests
               SET fulfillment_token = %s
               WHERE request_id = %s""",
            (fulfillment_token, request_id)
        )

        connection.commit()

        # Find NGO-verified, available donors matching blood group and city.
        # Eligibility is checked fresh for every new request/search.
        cursor.execute(
            """SELECT d.donor_id, d.gender, u.full_name, u.email, u.phone,
                      d.blood_group, d.city
               FROM donors d
               JOIN users u ON u.user_id = d.user_id
               WHERE UPPER(TRIM(d.blood_group)) = UPPER(TRIM(%s))
                 AND LOWER(TRIM(d.city)) = LOWER(TRIM(%s))
               ORDER BY u.full_name""",
            (group, city)
        )

        potential_matches = cursor.fetchall()
        matches = []
        for donor_match in potential_matches:
            last_donation, next_eligibility, is_eligible = get_donor_eligibility(
                donor_match["donor_id"], donor_match["gender"], cursor
            )
            if is_eligible:
                matches.append(donor_match)

        import html

        if matches:
            rows = "".join(
                "<tr><td><input type=\"radio\" name=\"donor_id\" value=\"{}\" required></td>"
                "<td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    int(d["donor_id"]),
                    html.escape(str(d["full_name"] or "")),
                    html.escape(str(d["blood_group"] or "")),
                    html.escape(str(d["city"] or "")),
                    html.escape(str(d["phone"] or "Not provided")),
                    html.escape(str(d["email"] or "Not provided"))
                )
                for d in matches
            )

            match_section = (
                f"<h2>Potential matching donors: {len(matches)}</h2>"
                "<p>Select the donor you actually received blood from. "
                "A qualified blood bank must confirm compatibility.</p>"
                f"<form method=\"POST\" action=\"/select-donor/{request_id}/{fulfillment_token}\">"
                "<table><tr><th>Select</th><th>Name</th><th>Blood group</th>"
                "<th>City</th><th>Phone</th><th>Email</th></tr>"
                + rows + "</table><p><button type=\"submit\">Select Donor</button></p></form>"
            )
        else:
            match_section = (
                "<h2>No matching verified and available donors found</h2>"
                "<p>Your request has been saved. The NGO team can review "
                "it and follow up.</p>"
            )

        return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Request Result | BloodCare</title>
          <style>
            body {
              font-family: Arial, sans-serif;
              background: #f7f7f9;
              color: #333;
              padding: 24px;
            }
            main {
              max-width: 900px;
              margin: 30px auto;
              background: white;
              padding: 28px;
              border-radius: 12px;
            }
            h1, h2 { color: #b51224; }
            table {
              border-collapse: collapse;
              width: 100%;
              margin-top: 18px;
            }
            td, th {
              border: 1px solid #ddd;
              padding: 10px;
              text-align: left;
            }
            p { line-height: 1.6; }
            a { color: #b51224; }
          </style>
        </head>
        <body>
          <main>
            <h1>Blood request submitted successfully</h1>
            <p>Request number: <strong>#{{ request_id }}</strong></p>
            <p>Your request is saved with status <strong>Pending</strong>.
            A submission does not guarantee blood availability.</p>
            
            {{ match_section|safe }}
            <p><a href="/index.html">Home</a></p>
          </main>
        </body>
        </html>
        """, request_id=request_id, fulfillment_token=fulfillment_token, match_section=match_section)

    except mysql.connector.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Blood request failed")
        return (
            "Unable to save the request. Check the database and Flask terminal.",
            500
        )

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        return send_from_directory(BASE_DIR, "admin-login.html")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT admin_id, username, password_hash FROM admins WHERE username=%s", (username,))
        admin = cursor.fetchone()
        if not admin or not check_password_hash(admin["password_hash"], password):
            return "Invalid admin username or password.", 401
        session.clear()
        session["admin_id"] = admin["admin_id"]
        session["admin_username"] = admin["username"]
        return redirect("/admin-dashboard")
    except mysql.connector.Error:
        app.logger.exception("Admin login failed")
        return "Admin login failed. Ensure an admin account has been created.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()




@app.route("/admin/update-donor", methods=["POST"])
def admin_update_donor():
    if not admin_required():
        return redirect("/admin-login")

    return "Manual donor status updates are disabled.", 403

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Registered Donors
        cursor.execute(
            """SELECT d.donor_id, u.full_name, u.phone, u.email,
                      d.blood_group, d.age, d.city, d.gender,
                      d.status, d.availability
               FROM donors d
               JOIN users u ON u.user_id = d.user_id
               ORDER BY d.donor_id DESC"""
        )
        donors = cursor.fetchall()
        
        # Refresh donor availability using completed donation history.
        for donor in donors:
            last_date, next_date, eligible = get_donor_eligibility(
                donor["donor_id"],
                donor["gender"],
                cursor
            )

            current_availability = (
                "Available" if eligible else "Unavailable"
            )

            cursor.execute(
                """
                UPDATE donors
                SET availability = %s
                WHERE donor_id = %s
                """,
                (current_availability, donor["donor_id"])
            )

            donor["availability"] = current_availability

        connection.commit()


        # Blood Requests
        cursor.execute(
            """SELECT r.request_id, r.patient_name, r.email,
                      r.blood_group, r.units, r.city,
                      r.contact_phone, r.needed_by, r.status,
                      r.created_at,
                      CASE WHEN r.status = 'Pending' AND r.created_at <= NOW() - INTERVAL 6 HOUR THEN 1 ELSE 0 END AS needs_followup,
                      COALESCE(u.full_name, 'Guest Recipient') AS requester
               FROM blood_requests r
               LEFT JOIN users u ON u.user_id = r.user_id
               ORDER BY r.created_at DESC"""
        )
        requests = cursor.fetchall()

        # Donation Records
        cursor.execute(
            """SELECT dn.donation_id, d.donor_id, u.full_name,
                      d.blood_group, d.city, dn.donation_date,
                      dn.status, dn.notes
               FROM donations dn
               JOIN donors d ON d.donor_id = dn.donor_id
               JOIN users u ON u.user_id = d.user_id
               ORDER BY dn.donation_date DESC, dn.donation_id DESC
               LIMIT 100"""
        )
        donations = cursor.fetchall()

        # Contact Enquiries
        cursor.execute(
            """SELECT enquiry_id, name, email, message,
                      submitted_at, status
               FROM contact_enquiries
               ORDER BY submitted_at DESC, enquiry_id DESC"""
        )
        enquiries = cursor.fetchall()

        # Diagnostic information in terminal
        app.logger.info(
            "Admin dashboard loaded %s contact enquiries",
            len(enquiries)
        )

        return render_file(
            "admin-dashboard.html",
            donors=donors,
            requests=requests,
            donations=donations,
            enquiries=enquiries,
            admin_username=session.get("admin_username", "Admin")
        )

    except mysql.connector.Error:
        app.logger.exception("Admin dashboard database query failed")
        return "Could not load admin dashboard. Check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


@app.route("/admin-dashboard")

def admin_dashboard():

    if not admin_required():

        return redirect("/admin-login")

    connection = None

    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor(dictionary=True)

        # Registered Donors

        cursor.execute(

            """SELECT d.donor_id, u.full_name, u.phone, u.email,

                      d.blood_group, d.age, d.city, d.gender,

                      d.status, d.availability

               FROM donors d

               JOIN users u ON u.user_id = d.user_id

               ORDER BY d.donor_id DESC"""

        )

        donors = cursor.fetchall()

        
        # Blood Requests
        cursor.execute(
            """SELECT r.request_id, r.patient_name, r.patient_gender,
                      r.email, r.blood_group, r.units, r.city,
                      r.contact_phone, r.needed_by, r.status,
                      r.created_at,
                      COALESCE(u.full_name, 'Guest Recipient') AS requester
               FROM blood_requests r
               LEFT JOIN users u ON u.user_id = r.user_id
               ORDER BY r.created_at DESC"""
        )
        requests = cursor.fetchall()


        # Donation Records

        cursor.execute(

            """SELECT dn.donation_id, d.donor_id, u.full_name,

                      d.blood_group, d.city, dn.donation_date,

                      dn.status, dn.notes

               FROM donations dn

               JOIN donors d ON d.donor_id = dn.donor_id

               JOIN users u ON u.user_id = d.user_id

               ORDER BY dn.donation_date DESC, dn.donation_id DESC

               LIMIT 100"""

        )

        donations = cursor.fetchall()

        # Contact Enquiries

        cursor.execute(

            """SELECT enquiry_id, name, email, message,

                      submitted_at, status

               FROM contact_enquiries

               ORDER BY submitted_at DESC, enquiry_id DESC"""

        )

        enquiries = cursor.fetchall()

        # Diagnostic information in terminal

        app.logger.info(

            "Admin dashboard loaded %s contact enquiries",

            len(enquiries)

        )

        return render_file(

            "admin-dashboard.html",

            donors=donors,

            requests=requests,

            donations=donations,

            enquiries=enquiries,

            admin_username=session.get("admin_username", "Admin")

        )

    except mysql.connector.Error:

        app.logger.exception("Admin dashboard database query failed")

        return "Could not load admin dashboard. Check the Flask terminal.", 500

    finally:

        if cursor:

            cursor.close()

        if connection and connection.is_connected():

            connection.close()


@app.route("/admin/update-request", methods=["POST"])
def admin_update_request():
    if not admin_required():
        return redirect("/admin-login")

    return "Manual status updates are disabled.", 403


@app.route("/admin/record-donation", methods=["POST"])
def admin_record_donation():
    if not admin_required():
        return redirect("/admin-login")
    donor_id = request.form.get("donor_id", type=int)
    donation_date_text = request.form.get("donation_date", "")
    status = request.form.get("status", "")
    notes = request.form.get("notes", "").strip()[:255]
    if status not in ("Pending", "Completed", "Cancelled"):
        return "Invalid donation status.", 400
    try:
        donation_date = date.fromisoformat(donation_date_text)
    except ValueError:
        return "Please provide a valid donation date.", 400
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO donations (donor_id, donation_date, status, verified_by, notes) VALUES (%s,%s,%s,%s,%s)",
            (donor_id, donation_date, status, session["admin_id"], notes or None)
        )
        connection.commit()
        return redirect("/admin-dashboard#donations")
    except mysql.connector.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Recording donation failed")
        return "Could not record donation. Check that donor ID exists.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    user_id = session.get("user_id")

    if not user_id:
        return "Please log in first.", 401

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE blood_requests
            SET status = 'Fulfilled',
                fulfilled_at = %s
            WHERE request_id = %s
              AND user_id = %s
              AND status <> 'Fulfilled'
            """,
            (datetime.now(), request_id, user_id)
        )

        connection.commit()

        if cursor.rowcount == 0:
            return "Request not found or already fulfilled.", 404

        

        return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Thank You | BloodCare</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #fff1f2, #fef2f2, #ffffff);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
            color: #333;
        }
        .thankyou-card {
            background: #fff;
            width: 100%;
            max-width: 600px;
            padding: 45px 30px;
            text-align: center;
            border-radius: 22px;
            box-shadow: 0 12px 40px rgba(181, 18, 36, 0.12);
        }
        .logo {
            font-size: 27px;
            font-weight: bold;
            color: #b51224;
            margin-bottom: 30px;
        }
        .success-icon {
            width: 90px;
            height: 90px;
            margin: 0 auto 25px;
            border-radius: 50%;
            background: #e7f8ec;
            color: #218838;
            font-size: 48px;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        h1 {
            color: #b51224;
            font-size: 30px;
            margin-bottom: 18px;
        }
        .message {
            font-size: 16px;
            line-height: 1.8;
            color: #555;
            margin-bottom: 20px;
        }
        .thank-you {
            background: #fff5f5;
            border-radius: 12px;
            padding: 18px;
            margin: 25px 0;
            line-height: 1.7;
            color: #555;
        }
        .thank-you strong {
            color: #b51224;
        }
        .home-btn {
            display: inline-block;
            background: #b51224;
            color: white;
            text-decoration: none;
            padding: 14px 30px;
            border-radius: 9px;
            font-size: 16px;
            font-weight: bold;
            transition: 0.3s;
        }
        .home-btn:hover {
            background: #8f0e1c;
            transform: translateY(-2px);
        }
        .footer {
            margin-top: 28px;
            color: #888;
            font-size: 13px;
            line-height: 1.6;
        }
        @media (max-width: 480px) {
            .thankyou-card {
                padding: 35px 20px;
            }
            h1 {
                font-size: 25px;
            }
        }
    </style>
</head>
<body>
    <main class="thankyou-card">
        <div class="logo">❤️ BloodCare</div>
        <div class="success-icon">&#10003;</div>

        <h1>Thank You!</h1>

        <p class="message">
            Your blood request has been successfully marked as fulfilled.
            We hope you received the support you needed.
        </p>

        <div class="thank-you">
            <strong>Thank you for being part of BloodCare!</strong>
            <br>
            Every request matters, and every act of kindness
            brings us closer to saving lives.
            <br>
            We appreciate your trust in our community.
        </div>

        <a href="/index.html" class="home-btn">Back to Home</a>

        <div class="footer">
            Together, we can make a difference. ❤️
            <br>
            BloodCare — Connecting Lives, Sharing Hope.
        </div>
    </main>
</body>
</html>
        """)

    except Exception:
        if connection:
            connection.rollback()
        app.logger.exception("Fulfilment update failed")
        return "Could not update request.", 500

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/admin/delete-request", methods=["POST"])
def admin_delete_request():
    if not admin_required():
        return redirect("/admin-login")

    request_id = request.form.get("request_id", type=int)

    if not request_id:
        return "Invalid request ID.", 400

    connection = cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            "DELETE FROM blood_requests WHERE request_id = %s",
            (request_id,)
        )
        connection.commit()

        if cursor.rowcount == 0:
            return "Request not found.", 404

        return redirect("/admin-dashboard")

    except mysql.connector.Error:
        if connection:
            connection.rollback()
        app.logger.exception("Deleting blood request failed")
        return "Could not delete blood request.", 500

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/admin-logout")
def admin_logout():
    session.clear()
    return redirect("/admin-login")


@app.route("/<path:filename>")
def serve_project_files(filename):
    # Do not serve source or secret/config files.
    if (filename.endswith((".py", ".sql", ".env")) or filename.startswith(".")
            or filename.startswith("bloodcare_private_uploads/")):
        return "Not found", 404
    return send_from_directory(BASE_DIR, filename)

print("DELETE ROUTE CHECK:")
print(app.url_map)


@app.route("/submit-enquiry", methods=["POST"])
def submit_enquiry():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    message = request.form.get("message", "").strip()

    if not name or not email or not message:
        return "Please fill in all fields.", 400

    if len(name) > 100 or len(email) > 254 or len(message) > 2000:
        return "Input is too long.", 400

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """INSERT INTO contact_enquiries (name, email, message)
               VALUES (%s, %s, %s)""",
            (name, email, message)
        )

        connection.commit()

        return """
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Enquiry Submitted | BloodCare</title>
        </head>
        <body style="font-family:Arial;text-align:center;padding:60px 20px;">
            <h1 style="color:#b51224;">Thank You!</h1>
            <p>Your enquiry has been submitted successfully.</p>
            <a href="/" style="color:#b51224;">Back to BloodCare</a>
        </body>
        </html>
        """

    except Exception:
        if connection:
            connection.rollback()
        app.logger.exception("Saving contact enquiry failed")
        return "Could not submit your enquiry. Please try again.", 500

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()



def send_blood_request_reminders():
    """Send one reminder for each still-pending request older than 10 minutes.

    Configure SMTP_EMAIL, SMTP_APP_PASSWORD, and BLOODCARE_PUBLIC_URL in the
    environment. Failures are logged and do not stop the scheduler.
    """
    smtp_email = os.environ.get("SMTP_EMAIL", "").strip()
    smtp_password = os.environ.get("SMTP_APP_PASSWORD", "").strip().replace(" ", "")
    public_url = os.environ.get("BLOODCARE_PUBLIC_URL", "http://127.0.0.1:5001").rstrip("/")
    if not smtp_email or not smtp_password:
        app.logger.warning("Email reminders skipped: SMTP_EMAIL/SMTP_APP_PASSWORD not configured")
        return

    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT request_id, patient_name, email, fulfillment_token
            FROM blood_requests
            WHERE status = 'Pending'
              AND created_at <= NOW() - INTERVAL 10 MINUTE
              AND reminder_sent_at IS NULL
              AND fulfillment_token IS NOT NULL
            ORDER BY created_at ASC
            LIMIT 50
        """)
        requests_to_remind = cursor.fetchall()
    except Exception:
        app.logger.exception("Could not load blood requests for email reminders")
        return
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    for blood_request in requests_to_remind:
        request_id = blood_request["request_id"]
        token = blood_request["fulfillment_token"]
        link = f"{public_url}/reminder-request/{request_id}/{token}"
        message = EmailMessage()
        message["Subject"] = "BloodCare: Please update your blood request"
        message["From"] = smtp_email
        message["To"] = blood_request["email"]
        message.set_content(
            f"Hello {blood_request['patient_name']},\n\n"
            "Your BloodCare request is still marked as pending. If you have already received the required blood, "
            "please use the secure link below to review your request and confirm it. "
            "If you have not received blood, no action is needed.\n\n"
            f"Review your request: {link}\n\nBloodCare"
        )
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
                smtp.login(smtp_email, smtp_password)
                smtp.send_message(message)

            # Mark as sent only after successful delivery submission; condition
            # prevents overwriting a request that was updated in the meantime.
            conn2 = get_db_connection()
            cur2 = conn2.cursor()
            cur2.execute("""
                UPDATE blood_requests
                SET reminder_sent_at = NOW()
                WHERE request_id = %s AND status = 'Pending' AND reminder_sent_at IS NULL
            """, (request_id,))
            conn2.commit()
            cur2.close()
            conn2.close()
            app.logger.info("Sent blood request reminder for request #%s", request_id)
        except Exception:
            app.logger.exception("Failed to send reminder for blood request #%s", request_id)


def _fulfilled_confirmation_page(request_id):
    """Show confirmation on the secure request page after fulfillment."""
    return render_template_string("""<!doctype html>
    <html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Confirmation Successful | BloodCare</title>
    <style>body{font-family:Arial,sans-serif;background:#f7f7f9;color:#333;max-width:650px;margin:50px auto;padding:20px}main{border:1px solid #eee;border-radius:12px;padding:28px;background:#fff}h1{color:#b51224}.success{color:#218838;font-weight:bold}</style>
    </head><body><main><h1>Thank You!</h1>
    <p class="success">Blood receipt confirmed successfully!</p>
    <p>BloodCare request #{{ request_id }} has been marked as fulfilled.</p>
    <p>You can use your browser's Back button to return to the previous page.</p>
    </main></body></html>""", request_id=request_id)


def _pending_thank_you_page(request_id):
    """Thank the requester without changing the request or donor records."""
    return render_template_string("""<!doctype html>
    <html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Thank You | BloodCare</title>
    <style>body{font-family:Arial,sans-serif;background:#f7f7f9;color:#333;max-width:650px;margin:50px auto;padding:20px}main{border:1px solid #eee;border-radius:12px;padding:28px;background:#fff}h1{color:#b51224}</style>
    </head><body><main><h1>Thank You for Visiting BloodCare</h1>
    <p>Your response for request #{{ request_id }} has been noted.</p>
    <p>Your request remains <strong>Pending</strong>. No request or donor details were changed.</p>
    </main></body></html>""", request_id=request_id)


@app.route("/reminder-request/<int:request_id>/<token>", methods=["GET"])
def reminder_request_page(request_id, token):
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""SELECT request_id, patient_name, blood_group, status, donor_id
                           FROM blood_requests
                           WHERE request_id=%s AND fulfillment_token=%s""", (request_id, token))
        blood_request = cursor.fetchone()
        if not blood_request:
            return "Invalid or expired request link.", 404
        if blood_request["status"] == "Fulfilled":
            return _fulfilled_confirmation_page(request_id)
        if blood_request["status"] != "Pending":
            return "This request has already been processed.", 409
        return render_template_string("""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Review Blood Request | BloodCare</title><style>body{font-family:Arial,sans-serif;background:#f7f7f9;max-width:650px;margin:50px auto;padding:20px;color:#333}main{border:1px solid #eee;border-radius:12px;padding:24px;background:#fff}h1{color:#b51224}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}button{background:#b51224;color:white;border:0;border-radius:8px;padding:12px 18px;cursor:pointer}.secondary{background:#555}</style></head><body><main><h1>BloodCare Request #{{ r.request_id }}</h1><p>Patient: {{ r.patient_name }}</p><p>Blood group: {{ r.blood_group }}</p><p>Your request is currently <strong>Pending</strong>.</p><p>If you have received the required blood, confirm below. If you have not received it, choose the second option; your request will remain pending.</p><div class='actions'><form method='POST' action='/mark-fulfilled/{{ r.request_id }}/{{ token }}' onsubmit="return confirm('Have you actually received the required blood?');"><button type='submit'>I Have Received My Blood</button></form><form method='POST' action='/not-received/{{ r.request_id }}/{{ token }}'><button class='secondary' type='submit'>I Have Not Received Blood</button></form></div></main></body></html>""", r=blood_request, token=token)
    except Exception:
        app.logger.exception("Could not open request reminder link")
        return "Could not open this request right now. Please try again later.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/not-received/<int:request_id>/<token>", methods=["POST"])
def requester_not_received(request_id, token):
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT request_id, status FROM blood_requests WHERE request_id=%s AND fulfillment_token=%s", (request_id, token))
        blood_request = cursor.fetchone()
        if not blood_request:
            return "Invalid or expired request link.", 404
        if blood_request["status"] == "Fulfilled":
            return _fulfilled_confirmation_page(request_id)
        if blood_request["status"] != "Pending":
            return "This request has already been processed.", 409
        # Intentionally do not update the database: request stays Pending.
        return _pending_thank_you_page(request_id)
    except Exception:
        app.logger.exception("Could not record requester response")
        return "Could not open this response right now. Please try again later.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def expire_old_blood_requests():
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE blood_requests
            SET status = 'Expired'
            WHERE status = 'Pending'
              AND created_at <= NOW() - INTERVAL 7 DAY
            """
        )

        updated_count = cursor.rowcount
        connection.commit()

        if updated_count:
            app.logger.info(
                "Marked %s old blood requests as Expired",
                updated_count
            )

    except Exception:
        if connection:
            connection.rollback()
        app.logger.exception("Expiring old blood requests failed")

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()



@app.route("/select-donor/<int:request_id>/<token>", methods=["POST"])
def select_donor_for_request(request_id, token):
    donor_id = request.form.get("donor_id", type=int)
    if not donor_id:
        return "Please select a donor.", 400

    connection = cursor = None
    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """SELECT request_id, blood_group, city, status
               FROM blood_requests
               WHERE request_id=%s AND fulfillment_token=%s
               FOR UPDATE""",
            (request_id, token)
        )
        blood_request = cursor.fetchone()
        if not blood_request:
            connection.rollback()
            return "Invalid request or confirmation link.", 404
        if blood_request["status"] != "Pending":
            connection.rollback()
            return "This request has already been processed.", 409

        cursor.execute(
            """SELECT d.donor_id, d.gender, d.blood_group, d.city,
                      d.availability, d.status
               FROM donors d
               WHERE d.donor_id=%s
                 AND UPPER(TRIM(d.blood_group))=UPPER(TRIM(%s))
                 AND LOWER(TRIM(d.city))=LOWER(TRIM(%s))
               FOR UPDATE""",
            (donor_id, blood_request["blood_group"], blood_request["city"])
        )
        donor = cursor.fetchone()
        if not donor:
            connection.rollback()
            return "This donor no longer matches the request or is unavailable.", 400

        _, _, eligible = get_donor_eligibility(donor_id, donor["gender"], cursor)
        if not eligible:
            connection.rollback()
            return "This donor is not currently eligible. Please search again.", 409

        cursor.execute(
            "UPDATE blood_requests SET donor_id=%s WHERE request_id=%s AND status='Pending'",
            (donor_id, request_id)
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return "Could not link donor to request. Please try again.", 409
        connection.commit()

        return render_template_string("""<!doctype html>
        <html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Confirm Blood Received | BloodCare</title>
        <style>body{font-family:Arial;background:#f7f7f9;padding:24px;color:#333}main{max-width:650px;margin:40px auto;background:white;padding:28px;border-radius:12px}h1{color:#b51224}button{background:#b51224;color:white;border:0;padding:12px 18px;border-radius:7px;cursor:pointer}</style></head>
        <body><main><h1>Donor selected</h1><p>Request #{{ request_id }} is now linked to your selected donor.</p>
        <p>Only click below after the blood has actually been received. The donation will then be recorded as completed.</p>
        <form method="POST" action="/mark-fulfilled/{{ request_id }}/{{ token }}" onsubmit="return confirm('Have you actually received the required blood from this donor?');">
        <button type="submit">I Have Received Blood</button></form><p><a href="/index.html">Home</a></p></main></body></html>""",
            request_id=request_id, token=token
        )
    except Exception:
        if connection:
            connection.rollback()
        app.logger.exception("Selecting donor for request failed")
        return "Could not select donor. Please check the Flask terminal.", 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/mark-fulfilled/<int:request_id>/<token>", methods=["POST"])
def mark_request_fulfilled(request_id, token):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        # Lock and verify the request before updating it.
        cursor.execute(
            """
            SELECT request_id, donor_id, status
            FROM blood_requests
            WHERE request_id = %s
              AND fulfillment_token = %s
            FOR UPDATE
            """,
            (request_id, token)
        )
        blood_request = cursor.fetchone()

        if not blood_request:
            connection.rollback()
            return "Invalid request or confirmation link.", 404

        if blood_request["status"] != "Pending":
            connection.rollback()
            return "This request has already been processed.", 409

        donor_id = blood_request["donor_id"]

        if donor_id is None:
            connection.rollback()
            # No donor is associated, so do not mark fulfilled or create a donation.
            # Show a thank-you page while leaving the request Pending.
            return _pending_thank_you_page(request_id)

        # Confirm the linked donor exists.
        cursor.execute(
            "SELECT donor_id FROM donors WHERE donor_id = %s",
            (donor_id,)
        )
        if not cursor.fetchone():
            connection.rollback()
            return "The linked donor was not found.", 400

        confirmation_time = datetime.now()

        # Update the blood request.
        cursor.execute(
            """
            UPDATE blood_requests
            SET status = 'Fulfilled',
                fulfilled_at = %s
            WHERE request_id = %s
              AND status = 'Pending'
            """,
            (confirmation_time, request_id)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return "Request could not be confirmed.", 409

        # Save a requester-confirmed donation record.
        
        cursor.execute(
            """
            INSERT INTO donations
                (donor_id, donation_date, status, notes)
            VALUES (%s, %s, 'Completed', %s)
            """,
            (
                donor_id,
                confirmation_time.date(),
                f"Requester-confirmed completed donation for blood request #{request_id}"
            )
        )

        # Mark the donor as unavailable after the confirmed donation.
        cursor.execute(
            """
            UPDATE donors
            SET availability = 'Unavailable'
            WHERE donor_id = %s
            """,
            (donor_id,)
        )

        connection.commit()


        # Redirect to the secure request page using GET, avoiding POST resubmission.
        # That page will display the success confirmation for the fulfilled request.
        return redirect(f"/reminder-request/{request_id}/{token}")
    except Exception:
        if connection:
            connection.rollback()
        app.logger.exception("Fulfilment update failed")
        return "Could not update request. Please check the Flask terminal.", 500

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()




# ---------------------------------------------------------------------------
# ADDITIVE REQUESTER PORTAL. Existing donor/admin routes and 7-day expiry
# scheduler are intentionally retained.
# ---------------------------------------------------------------------------
def _requester_id():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT role FROM users WHERE user_id=%s", (uid,))
        row = cur.fetchone()
        return uid if row and row["role"] == "requester" else None
    except mysql.connector.Error:
        app.logger.exception("Checking requester role failed")
        return None
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


def _portal_page(title, body):
    return render_template_string("""<!doctype html><html lang="en"><head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{{ title }} | BloodCare</title><style>
    body{font-family:Arial;background:#f7f7f9;color:#333;padding:22px}
    main{max-width:1100px;margin:auto;background:white;padding:24px;border-radius:12px}
    h1,h2{color:#b51224}label{display:block;margin:12px 0 5px}
    input,select,textarea{box-sizing:border-box;width:100%;padding:10px;border:1px solid #ccc;border-radius:6px}
    button,.btn{display:inline-block;background:#b51224;color:white;padding:10px 14px;border:0;border-radius:6px;text-decoration:none;cursor:pointer;margin:4px}
    .secondary{background:#555}.card{border:1px solid #ddd;border-radius:9px;padding:15px;margin:14px 0}
    table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #ddd;padding:8px;text-align:left}
    </style></head><body><main><h1>{{ title }}</h1>{{ body|safe }}</main></body></html>""",
    title=title, body=body)


@app.route("/requester-register", methods=["GET", "POST"])
def requester_register():
    if request.method == "GET":
        return _portal_page("Requester Registration", """
        <form method="post">
        <label>Full name</label><input name="full_name" maxlength="120" required>
        <label>Email</label><input name="email" type="email" maxlength="190" required>
        <label>Phone (10 digits)</label><input name="phone" pattern="[0-9]{10}" required>
        <label>City</label><input name="city" maxlength="100" required>
        <label>Password (minimum 8 characters)</label><input name="password" type="password" minlength="8" required>
        <label>Confirm password</label><input name="confirm_password" type="password" minlength="8" required>
        <button>Create account</button></form><p>Already registered? <a href="/requester-login">Sign in</a></p>""")
    name=request.form.get("full_name","").strip()
    email=request.form.get("email","").strip().lower()
    phone=request.form.get("phone","").strip()
    city=request.form.get("city","").strip()
    pw=request.form.get("password","")
    cpw=request.form.get("confirm_password","")
    if not all([name,email,phone,city,pw]) or len(phone)!=10 or not phone.isdigit() or len(pw)<8 or pw!=cpw:
        return "Check the required fields, phone number and matching password.",400
    conn=cur=None
    try:
        conn=get_db_connection(); cur=conn.cursor()
        cur.execute("""INSERT INTO users(full_name,email,phone,city,password_hash,role)
                       VALUES(%s,%s,%s,%s,%s,'requester')""",
                    (name,email,phone,city,generate_password_hash(pw)))
        conn.commit(); session.clear(); session["user_id"]=cur.lastrowid
        return redirect("/requester-dashboard")
    except IntegrityError:
        if conn: conn.rollback()
        return "This email is already registered.",409
    except mysql.connector.Error:
        if conn: conn.rollback()
        app.logger.exception("Requester registration failed")
        return "Could not register requester. Check Flask terminal.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/requester-login", methods=["GET","POST"])
def requester_login():
    if request.method=="GET":
        return _portal_page("Requester Sign In", """
        <form method="post"><label>Email</label><input name="email" type="email" required>
        <label>Password</label><input name="password" type="password" required>
        <button>Sign in</button></form><p><a href="/requester-register">Create requester account</a></p>""")
    email=request.form.get("email","").strip().lower(); pw=request.form.get("password","")
    conn=cur=None
    try:
        conn=get_db_connection(); cur=conn.cursor(dictionary=True)
        cur.execute("SELECT user_id,password_hash,role FROM users WHERE email=%s",(email,))
        u=cur.fetchone()
        if not u or u["role"]!="requester" or not check_password_hash(u["password_hash"],pw):
            return "Invalid requester email or password.",401
        session.clear(); session["user_id"]=u["user_id"]
        return redirect("/requester-dashboard")
    except mysql.connector.Error:
        app.logger.exception("Requester login failed")
        return "Could not sign in.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/requester-logout")
def requester_logout():
    session.clear()
    return redirect("/requester-login")


@app.route("/requester-dashboard")
def requester_dashboard():
    uid=_requester_id()
    if not uid: return redirect("/requester-login")
    conn=cur=None
    try:
        conn=get_db_connection(); cur=conn.cursor(dictionary=True)
        cur.execute("SELECT full_name,email,phone,city FROM users WHERE user_id=%s",(uid,))
        profile=cur.fetchone()
        cur.execute("SELECT COUNT(*) total,MAX(created_at) last_date FROM blood_requests WHERE user_id=%s",(uid,))
        stats=cur.fetchone()
        cur.execute("""SELECT r.request_id,r.patient_name,r.blood_group,r.units,r.city,
                       r.status,r.created_at,r.disease,r.document_status,r.requester_response,
                       r.donor_id,r.fulfilled_at,du.full_name donor_name
                       FROM blood_requests r LEFT JOIN donors d ON d.donor_id=r.donor_id
                       LEFT JOIN users du ON du.user_id=d.user_id
                       WHERE r.user_id=%s ORDER BY r.created_at DESC""",(uid,))
        records=cur.fetchall()
        import html
        rows=[]
        for r in records:
            actions=""
            if r["status"]=="Pending":
                actions=f"""<form method="post" action="/requester-response/{r['request_id']}" style="display:inline" onsubmit="return confirm('Confirm you have actually received blood?')"><input type="hidden" name="response" value="received"><button>I Have Received My Blood</button></form>
                <form method="post" action="/requester-response/{r['request_id']}" style="display:inline"><input type="hidden" name="response" value="not_received"><button class="secondary">I Have Not Received My Blood</button></form>"""
            rows.append("<tr><td>#{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                r["request_id"],html.escape(str(r["patient_name"] or "")),
                html.escape(str(r["blood_group"] or "")),r["units"],
                html.escape(str(r["status"] or "")),html.escape(str(r["document_status"] or "Pending")),
                html.escape(str(r["requester_response"] or "No response")),
                html.escape(str(r["donor_name"] or "Not linked"))+"<br>"+actions))
        table="<table><tr><th>Request</th><th>Patient</th><th>Blood group</th><th>Units</th><th>Status</th><th>Prescription status</th><th>Your response</th><th>Donor / Action</th></tr>"+"".join(rows)+"</table>" if rows else "<p>No requests yet.</p>"
        last=stats["last_date"].strftime("%d-%m-%Y %H:%M") if stats["last_date"] else "None"
        body=f"""<section class="card"><h2>Welcome, {html.escape(profile['full_name'])}</h2>
        <p>{html.escape(profile['email'])} | {html.escape(profile['phone'])} | {html.escape(profile['city'])}</p>
        <p><b>Total requests:</b> {stats['total']} &nbsp; <b>Last request:</b> {last}</p>
        <a class="btn" href="/requester-request-blood">Request Blood</a><a class="btn secondary" href="/requester-logout">Sign out</a></section>
        <h2>My Requests</h2>{table}<p>Pending requests automatically expire after 7 days from their original creation time.</p>"""
        return _portal_page("Requester Dashboard",body)
    except mysql.connector.Error:
        app.logger.exception("Requester dashboard failed")
        return "Could not load requester dashboard.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/requester-request-blood", methods=["GET","POST"])
def requester_request_blood():
    uid=_requester_id()
    if not uid: return redirect("/requester-login")
    if request.method=="GET":
        return _portal_page("Request Blood", """
        <form method="post" enctype="multipart/form-data">
        <label>Patient name</label><input name="patient_name" maxlength="120" required>
        <label>Patient gender</label><select name="patient_gender" required><option value="">Select</option><option>Male</option><option>Female</option></select>
        <label>Contact email</label><input name="email" type="email" required>
        <label>Blood group</label><select name="blood_group" required><option value="">Select</option><option>A+</option><option>A-</option><option>B+</option><option>B-</option><option>O+</option><option>O-</option><option>AB+</option><option>AB-</option></select>
        <label>Units (1-20)</label><input name="units" type="number" min="1" max="20" required>
        <label>City</label><input name="city" maxlength="100" required>
        <label>Contact phone (10 digits)</label><input name="contact_phone" pattern="[0-9]{10}" required>
        <label>Required by</label><input name="needed_by" type="date" required>
        <label>Disease / medical condition</label><textarea name="disease" maxlength="255" required></textarea>
        <label>Doctor prescription (PDF/JPG/PNG, max 5 MB)</label><input name="prescription" type="file" accept=".pdf,.jpg,.jpeg,.png" required>
        <button>Submit request</button></form><p><a href="/requester-dashboard">Back to dashboard</a></p>""")
    patient=request.form.get("patient_name","").strip()
    gender=request.form.get("patient_gender","").strip()
    email=request.form.get("email","").strip().lower()
    group=request.form.get("blood_group","").strip()
    city=request.form.get("city","").strip()
    phone=request.form.get("contact_phone","").strip()
    disease=request.form.get("disease","").strip()[:255]
    upload=request.files.get("prescription")
    try:
        units=int(request.form.get("units",""))
        needed=date.fromisoformat(request.form.get("needed_by",""))
    except ValueError:
        return "Invalid units or required date.",400
    if not all([patient,email,group,city,phone,disease,upload,upload.filename]) or gender not in ("Male","Female") or group not in VALID_GROUPS:
        return "Complete all fields and upload a valid prescription.",400
    if not 1<=units<=20 or needed<date.today() or len(phone)!=10 or not phone.isdigit():
        return "Check units, date and phone number.",400
    ext=Path(secure_filename(upload.filename)).suffix.lower()
    if ext not in ALLOWED_PRESCRIPTION_EXTENSIONS: return "Prescription must be PDF, JPG, JPEG or PNG.",400
    upload.stream.seek(0,os.SEEK_END); size=upload.stream.tell(); upload.stream.seek(0)
    if size>MAX_PRESCRIPTION_BYTES: return "Prescription must be 5 MB or smaller.",400
    stored=secrets.token_hex(24)+ext
    conn=cur=None; saved=None
    try:
        PRIVATE_UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
        saved=PRIVATE_UPLOAD_DIR/stored; upload.save(saved)
        conn=get_db_connection(); cur=conn.cursor()
        cur.execute("""INSERT INTO blood_requests(user_id,patient_name,patient_gender,email,blood_group,units,city,contact_phone,needed_by,disease,prescription_filename,document_status)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Pending')""",
                    (uid,patient,gender,email,group,units,city,phone,needed,disease,stored))
        rid=cur.lastrowid
        cur.execute("UPDATE blood_requests SET fulfillment_token=%s WHERE request_id=%s AND user_id=%s",(secrets.token_urlsafe(32),rid,uid))
        conn.commit()
        return redirect("/requester-dashboard")
    except mysql.connector.Error:
        if conn: conn.rollback()
        if saved and saved.exists(): saved.unlink()
        app.logger.exception("Requester request submission failed")
        return "Could not save request. Check Flask terminal.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/requester-response/<int:request_id>", methods=["POST"])
def requester_response(request_id):
    uid=_requester_id()
    if not uid: return redirect("/requester-login")
    choice=request.form.get("response","")
    if choice not in ("received","not_received"): return "Invalid response.",400
    conn=cur=None
    try:
        conn=get_db_connection(); conn.start_transaction(); cur=conn.cursor(dictionary=True)
        cur.execute("SELECT request_id,user_id,status,donor_id,created_at,document_status FROM blood_requests WHERE request_id=%s AND user_id=%s FOR UPDATE",(request_id,uid))
        r=cur.fetchone()
        if not r: conn.rollback(); return "Request not found for your account.",404
        if r["status"]!="Pending": conn.rollback(); return "Request is no longer pending.",409
        if r["created_at"] <= datetime.now()-timedelta(days=7):
            cur.execute("UPDATE blood_requests SET status='Expired' WHERE request_id=%s AND user_id=%s AND status='Pending'",(request_id,uid))
            conn.commit(); return "This request has expired after 7 days.",409
        if choice=="not_received":
            cur.execute("UPDATE blood_requests SET requester_response='Not Received',response_note='Requester reports blood has not been received' WHERE request_id=%s AND user_id=%s AND status='Pending'",(request_id,uid))
            conn.commit(); return redirect("/requester-dashboard")
        if not r["donor_id"]: conn.rollback(); return "A donor must be linked before confirming receipt. Contact BloodCare team.",409
        if r["document_status"] != "Verified":
            conn.rollback()
            return "Your prescription must be verified by the BloodCare admin before confirming receipt.", 409
        cur.execute("SELECT donor_id FROM donors WHERE donor_id=%s FOR UPDATE",(r["donor_id"],))
        if not cur.fetchone(): conn.rollback(); return "Linked donor not found.",409
        now=datetime.now()
        cur.execute("""UPDATE blood_requests SET status='Fulfilled',fulfilled_at=%s,requester_response='Received',response_note=NULL
                       WHERE request_id=%s AND user_id=%s AND status='Pending'""",(now,request_id,uid))
        if cur.rowcount!=1: conn.rollback(); return "Request already processed.",409
        cur.execute("INSERT INTO donations(donor_id,donation_date,status,notes) VALUES(%s,%s,'Completed',%s)",
                    (r["donor_id"],now.date(),f"Requester-confirmed blood request #{request_id}"))
        cur.execute("UPDATE donors SET availability='Unavailable' WHERE donor_id=%s",(r["donor_id"],))
        conn.commit()
        return redirect("/requester-dashboard")
    except mysql.connector.Error:
        if conn: conn.rollback()
        app.logger.exception("Requester response update failed")
        return "Could not update request.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/admin/request-review")
def admin_request_review():
    if not admin_required(): return redirect("/admin-login")
    conn=cur=None
    try:
        conn=get_db_connection(); cur=conn.cursor(dictionary=True)
        cur.execute("""SELECT r.request_id,r.patient_name,r.email,r.blood_group,r.units,r.city,r.status,
                       r.disease,r.document_status,r.prescription_filename,r.requester_response,
                       r.donor_id,COALESCE(u.full_name,'Guest Recipient') requester
                       FROM blood_requests r LEFT JOIN users u ON u.user_id=r.user_id
                       ORDER BY r.created_at DESC""")
        records=cur.fetchall(); import html
        rows=[]
        for r in records:
            doc="No prescription"
            verify=""
            if r["prescription_filename"]:
                doc=f'<a href="/admin/prescription/{r["request_id"]}">Open private prescription</a>'
                if r["document_status"]!="Verified":
                    verify=f'<form method="post" action="/admin/verify-prescription/{r["request_id"]}"><button>Mark document verified</button></form>'
            link=""
            if r["status"]=="Pending":
                link=f'<form method="post" action="/admin/link-donor"><input type="hidden" name="request_id" value="{r["request_id"]}"><label>Donor ID</label><input type="number" min="1" name="donor_id" required><button>Link donor</button></form>'
            rows.append(f"<tr><td>#{r['request_id']}</td><td>{html.escape(str(r['requester'] or ''))}</td><td>{html.escape(str(r['patient_name'] or ''))}</td><td>{html.escape(str(r['disease'] or ''))}</td><td>{html.escape(str(r['blood_group'] or ''))}</td><td>{r['units']}</td><td>{html.escape(str(r['status'] or ''))}</td><td>{html.escape(str(r['document_status'] or 'Pending'))}</td><td>{doc}{verify}</td><td>{html.escape(str(r['requester_response'] or 'No response'))}</td><td>{html.escape(str(r['donor_id'] or 'Not linked'))}</td><td>{link}</td></tr>")
        table="<table><tr><th>ID</th><th>Requester</th><th>Patient</th><th>Disease</th><th>Group</th><th>Units</th><th>Status</th><th>Document</th><th>Prescription</th><th>Response</th><th>Donor ID</th><th>Link donor</th></tr>"+"".join(rows)+"</table>"
        return _portal_page("Admin Request Review",table+'<p><a href="/admin-dashboard">Back to admin dashboard</a></p>')
    except mysql.connector.Error:
        app.logger.exception("Admin request review failed")
        return "Could not load admin request review.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/admin/verify-prescription/<int:request_id>",methods=["POST"])
def admin_verify_prescription(request_id):
    if not admin_required(): return redirect("/admin-login")
    conn=cur=None
    try:
        conn=get_db_connection(); cur=conn.cursor()
        cur.execute("UPDATE blood_requests SET document_status='Verified' WHERE request_id=%s AND prescription_filename IS NOT NULL",(request_id,))
        conn.commit()
        if cur.rowcount!=1: return "Prescription not found.",404
        return redirect("/admin/request-review")
    except mysql.connector.Error:
        if conn: conn.rollback()
        app.logger.exception("Prescription verification failed")
        return "Could not verify prescription.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/admin/prescription/<int:request_id>")
def admin_private_prescription(request_id):
    if not admin_required(): return redirect("/admin-login")
    conn=cur=None
    try:
        conn=get_db_connection(); cur=conn.cursor()
        cur.execute("SELECT prescription_filename FROM blood_requests WHERE request_id=%s",(request_id,))
        row=cur.fetchone()
        if not row or not row[0]: return "Prescription not found.",404
        name=Path(row[0]).name; file_path=PRIVATE_UPLOAD_DIR/name
        if not file_path.is_file(): return "Prescription file not found on server.",404
        return send_from_directory(PRIVATE_UPLOAD_DIR,name,as_attachment=True)
    except mysql.connector.Error:
        app.logger.exception("Prescription download failed")
        return "Could not retrieve prescription.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/admin/link-donor",methods=["POST"])
def admin_link_donor():
    if not admin_required(): return redirect("/admin-login")
    rid=request.form.get("request_id",type=int); did=request.form.get("donor_id",type=int)
    if not rid or not did: return "Valid request and donor IDs are required.",400
    conn=cur=None
    try:
        conn=get_db_connection(); conn.start_transaction(); cur=conn.cursor(dictionary=True)
        cur.execute("SELECT request_id,blood_group,city,status,created_at FROM blood_requests WHERE request_id=%s FOR UPDATE",(rid,))
        r=cur.fetchone()
        if not r or r["status"]!="Pending": conn.rollback(); return "Request is not pending.",409
        if r["created_at"]<=datetime.now()-timedelta(days=7):
            cur.execute("UPDATE blood_requests SET status='Expired' WHERE request_id=%s AND status='Pending'",(rid,))
            conn.commit(); return "Request expired after 7 days.",409
        cur.execute("SELECT donor_id,blood_group,city,gender,status FROM donors WHERE donor_id=%s FOR UPDATE",(did,))
        d=cur.fetchone()
        if not d: conn.rollback(); return "Donor not found.",404
        if d["status"]!="Verified" or str(d["blood_group"]).strip().upper()!=str(r["blood_group"]).strip().upper() or str(d["city"]).strip().lower()!=str(r["city"]).strip().lower():
            conn.rollback(); return "Donor must be verified and match blood group and city.",400
        _,_,eligible=get_donor_eligibility(did,d["gender"],cur)
        if not eligible: conn.rollback(); return "Donor is not currently eligible.",409
        cur.execute("UPDATE blood_requests SET donor_id=%s WHERE request_id=%s AND status='Pending'",(did,rid))
        conn.commit(); return redirect("/admin/request-review")
    except mysql.connector.Error:
        if conn: conn.rollback()
        app.logger.exception("Donor linking failed")
        return "Could not link donor.",500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()



if __name__ == "__main__":
    expire_old_blood_requests()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        expire_old_blood_requests,
        trigger="interval",
        hours=1,
        id="expired_blood_request_cleanup",
        replace_existing=True
    )
    scheduler.add_job(
        send_blood_request_reminders,
        trigger="interval",
        minutes=1,
        id="blood_request_email_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )
    scheduler.start()

    try:
        app.run(port=5001, debug=False, use_reloader=False)
    finally:
        scheduler.shutdown()
