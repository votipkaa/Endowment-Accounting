# Deploying Endowment Manager to Render

This gets the app live on the internet in about 10 minutes. You'll need a free GitHub account and a free Render account.

---

## Step 1 — Put the files on GitHub

1. Go to **github.com** and sign in (or create a free account)
2. Click the **+** icon → **New repository**
3. Name it `endowment-manager`, set it to **Private**, click **Create repository**
4. On the next page, click **uploading an existing file**
5. Drag the entire **`Endowment Accounting Software`** folder contents into the upload area
   - Upload everything: `app/`, `wsgi.py`, `requirements.txt`, `Procfile`, `render.yaml`, `.gitignore`, `runtime.txt`
6. Click **Commit changes**

---

## Step 2 — Create a Render account

1. Go to **render.com** → click **Get Started for Free**
2. Sign up with your GitHub account (easiest — it links them automatically)

---

## Step 3 — Deploy with render.yaml (one click)

1. In Render, click **New +** → **Blueprint**
2. Connect your GitHub account if prompted
3. Select your `endowment-manager` repository
4. Render will detect the `render.yaml` file and automatically configure:
   - A **web service** running the Flask app
   - A **free PostgreSQL database**
   - A randomly generated secret key
5. Click **Apply** — Render starts building (~3–5 minutes)

---

## Step 4 — Get your URL

Once the build completes (green checkmark):

1. Click on the **endowment-manager** web service
2. Your URL appears at the top — something like `https://endowment-manager-xxxx.onrender.com`
3. Open it in your browser
4. Log in with:
   - **Username:** `admin`
   - **Password:** `Admin1234!`
5. **Change the password immediately** in Admin → Users

---

## Notes

- **Free tier spin-up:** Render's free tier "sleeps" after 15 minutes of inactivity. The first visit after sleeping takes ~30 seconds to wake up. This is normal.
- **Data persistence:** Your data is stored in the free PostgreSQL database and persists across deploys and restarts.
- **Updates:** Push changes to GitHub → Render auto-deploys (configured in render.yaml).
- **Upgrade:** If you want the app to never sleep, Render's paid tier starts at $7/month.

---

## Troubleshooting

**Build fails with "module not found":**
Make sure all files were uploaded including the `app/` folder with its subdirectories.

**"Application error" on first load:**
Check Render's logs (click your service → Logs tab). Usually a missing env var or database not ready yet — wait 1 minute and refresh.

**Can't log in:**
The admin user is created automatically on first startup. If it didn't work, check the Logs tab for `✓ Default admin created`.
