# BloodCare integrated Flask project

## Included
- Existing BloodCare homepage, styles, scripts and images
- User registration and login
- Donor profile create/update and dashboard
- Recipient blood request form; after submission it shows matching donors only when the NGO has marked them **Verified** and **Available**
- Admin login and dashboard to verify donors, update availability, manage request status, and record completed donations
- Donation history and estimated next whole-blood donation date on the donor dashboard

## 1. Install packages
Open VS Code terminal in this folder and run:
```powershell
py -m pip install flask mysql-connector-python werkzeug
```

## 2. Configure database password (PowerShell)
Set your actual local MySQL root password in the terminal before running Flask. Do not write your password in `app.py`.
```powershell
$env:DB_PASSWORD = "YOUR_MYSQL_PASSWORD"
$env:BLOODCARE_SECRET_KEY = "replace-this-with-a-long-random-secret"
```
These settings last for that terminal session. Re-enter them if you open a new terminal.

## 3. Set up MySQL
Open MySQL Workbench, select/open the `schema.sql` file, and execute it.
If you already have `bloodcare_db`, CREATE TABLE IF NOT EXISTS preserves existing tables and does not add missing columns automatically. Check `donors` has `gender`, `availability`, and `status`; run only the matching commented ALTER statement in `schema.sql` if a column is absent.

## 4. Create an admin account
After the schema is ready and `DB_PASSWORD` is set, run:
```powershell
py create_admin.py
```
Choose a username and a strong password. The password is stored as a hash, not plain text.

## 5. Start the website
```powershell
py app.py
```
Open:
- Website: http://127.0.0.1:5000
- Admin login: http://127.0.0.1:5000/admin-login
- Database test: http://127.0.0.1:5000/test-db

## How the workflow works
1. User registers and signs in.
2. They can create/update their donor profile, or submit a blood request.
3. A request result page immediately shows matching donors in the same city and blood group **only if the NGO has verified and marked them available**. Otherwise it tells the requester the request was saved and can be reviewed by the NGO.
4. Admin contacts donors before changing their verification/availability. Admin can update request status and record a donation after confirmation.
5. The donor dashboard shows completed donation count and a rough next-date estimate (90 days for men, 120 days for women, based on the project's current rule). This is not medical clearance; a qualified blood bank must decide eligibility.

## Important security note
The ZIP you provided contained a database password in the original `app.py`. This integrated version removes it from the source and reads it from `DB_PASSWORD`. If the original password is used anywhere else or the ZIP was shared, change your MySQL password. Do not deploy this development Flask server publicly as-is; use HTTPS, CSRF protection, production configuration, and a proper WSGI server before deployment.


## Email reminders (optional; configure before enabling)
The app can send one reminder email when a blood request is still `Pending` and at least 10 minutes old. The admin dashboard highlights pending requests older than 6 hours.

1. In MySQL Workbench, run `email_reminder_migration.sql` once against `bloodcare_db`. Do not run it repeatedly after the column has been added.
2. In the same PowerShell terminal used to start Flask, set these environment variables (use your own values):
```powershell
$env:SMTP_EMAIL = "your-gmail-address@gmail.com"
$env:SMTP_APP_PASSWORD = "YOUR_GOOGLE_APP_PASSWORD"
$env:BLOODCARE_PUBLIC_URL = "http://127.0.0.1:5001"
```
3. Start the app with `py app.py`. The reminder scheduler runs while this process is running. Keep the App Password private; do not put it in `app.py`, the ZIP, screenshots, or chat.
4. For a requester opening the link on a different phone/computer, `BLOODCARE_PUBLIC_URL` must be your website's reachable HTTPS address. `127.0.0.1` is only for testing on the same computer. Do not expose Flask's development server directly to the public internet.

If SMTP variables are not configured, the app logs that reminders were skipped; other site features continue to work. Email sending requires working Gmail SMTP credentials and internet access. Test first with a request created at least 10 minutes earlier.
