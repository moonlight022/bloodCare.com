import os
from getpass import getpass
import mysql.connector
from werkzeug.security import generate_password_hash

connection = mysql.connector.connect(
    host=os.environ.get("DB_HOST", "localhost"),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASSWORD", ""),
    database=os.environ.get("DB_NAME", "bloodcare_db"),
)
username = input("Choose admin username: ").strip()
password = getpass("Choose admin password (minimum 12 characters): ")
if not username or len(password) < 12:
    raise SystemExit("Username is required and password must be at least 12 characters.")
try:
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
        (username, generate_password_hash(password)),
    )
    connection.commit()
    print("Admin account created. Keep the password private.")
except mysql.connector.Error as exc:
    connection.rollback()
    print("Could not create admin. Ensure schema.sql has been applied and username is unique.")
    print(exc)
finally:
    try:
        cursor.close()
        connection.close()
    except Exception:
        pass
