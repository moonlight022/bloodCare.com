USE bloodcare_db;

-- Run this once in MySQL Workbench to support one-time email reminders.
ALTER TABLE blood_requests
ADD COLUMN reminder_sent_at DATETIME NULL;
