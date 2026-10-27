-- BloodCare schema for MySQL 8
CREATE DATABASE IF NOT EXISTS bloodcare_db;
USE bloodcare_db;

CREATE TABLE IF NOT EXISTS users (
  user_id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  phone VARCHAR(20) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  city VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS donors (
  donor_id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL UNIQUE,
  blood_group VARCHAR(3) NOT NULL,
  age INT NOT NULL,
  city VARCHAR(100) NOT NULL,
  status VARCHAR(20) DEFAULT 'Pending',
  registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  availability VARCHAR(20) DEFAULT 'Pending',
  gender VARCHAR(20),
  CONSTRAINT fk_donors_user FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS blood_requests (
  request_id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  patient_name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL,
  blood_group VARCHAR(3) NOT NULL,
  units INT NOT NULL,
  city VARCHAR(100) NOT NULL,
  contact_phone VARCHAR(20) NOT NULL,
  needed_by DATE NOT NULL,
  status VARCHAR(30) DEFAULT 'Pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_requests_user FOREIGN KEY (user_id) REFERENCES users(user_id)
);

USE bloodcare_db;

ALTER TABLE blood_requests
ADD COLUMN donor_id INT NULL,
ADD COLUMN fulfilled_at DATETIME NULL,
ADD CONSTRAINT fk_blood_request_donor
FOREIGN KEY (donor_id) REFERENCES donors(donor_id);

CREATE TABLE IF NOT EXISTS admins (
  admin_id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(80) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL
);
USE bloodcare_db;

SELECT * FROM admins;

CREATE TABLE IF NOT EXISTS donations (
  donation_id INT AUTO_INCREMENT PRIMARY KEY,
  donor_id INT NOT NULL,
  donation_date DATE NOT NULL,
  donation_type VARCHAR(30) DEFAULT 'Whole Blood',
  status VARCHAR(20) DEFAULT 'Pending',
  verified_by INT NULL,
  notes VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_donations_donor FOREIGN KEY (donor_id) REFERENCES donors(donor_id),
  CONSTRAINT fk_donations_admin FOREIGN KEY (verified_by) REFERENCES admins(admin_id)
);

-- If these columns are missing from an EXISTING donors table, run the relevant
-- ALTER statement once. Skip any column that already exists:
-- ALTER TABLE donors ADD COLUMN gender VARCHAR(20) NULL;
-- ALTER TABLE donors ADD COLUMN availability VARCHAR(20) DEFAULT 'Pending';
-- ALTER TABLE donors ADD COLUMN status VARCHAR(20) DEFAULT 'Pending';

USE bloodcare_db;

ALTER TABLE blood_requests
MODIFY COLUMN user_id INT NULL;

USE bloodcare_db;

SELECT request_id, patient_name, blood_group, city, status
FROM blood_requests
ORDER BY request_id DESC;

USE bloodcare_db;

SELECT
    u.full_name,
    d.blood_group,
    d.city,
    d.status,
    d.availability
FROM donors d
JOIN users u ON u.user_id = d.user_id;

USE bloodcare_db;

USE bloodcare_db;

ALTER TABLE blood_requests
ADD COLUMN donor_id INT NULL;

ALTER TABLE blood_requests
ADD CONSTRAINT fk_blood_request_donor
FOREIGN KEY (donor_id) REFERENCES donors(donor_id);

ALTER TABLE blood_requests
ADD COLUMN fulfilled_at DATETIME NULL;

USE bloodcare_db;

ALTER TABLE blood_requests
ADD COLUMN fulfillment_token VARCHAR(64) NULL;

USE bloodcare_db;

SHOW COLUMNS FROM blood_requests;
USE bloodcare_db;

ALTER TABLE blood_requests
ADD COLUMN fulfillment_token VARCHAR(64) NULL;

SELECT request_id, status, fulfilled_at
FROM blood_requests
ORDER BY request_id DESC
LIMIT 5;

SELECT * FROM bloodcare_db.blood_requests;

USE bloodcare_db;

CREATE TABLE IF NOT EXISTS contact_enquiries (
    enquiry_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(254) NOT NULL,
    message TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'New'
);
SELECT * FROM bloodcare_db.contact_enquiries
ORDER BY enquiry_id DESC;


USE bloodcare_db;

SHOW COLUMNS FROM blood_requests;
SHOW CREATE TABLE blood_requests;

SHOW COLUMNS FROM donations;
SHOW CREATE TABLE donations;

USE bloodcare_db;

SHOW COLUMNS FROM donations;

USE bloodcare_db;

ALTER TABLE users
ADD COLUMN state VARCHAR(100) NULL,
ADD COLUMN district VARCHAR(100) NULL;

ALTER TABLE donors
ADD COLUMN state VARCHAR(100) NULL,
ADD COLUMN district VARCHAR(100) NULL;

USE bloodcare_db;

ALTER TABLE users
ADD COLUMN gender VARCHAR(20) NULL;

USE bloodcare_db;
DESCRIBE blood_requests;

USE bloodcare_db;

ALTER TABLE blood_requests
ADD COLUMN patient_gender VARCHAR(20) NULL;

