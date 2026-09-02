# DisasterNet — Run Guide (Windows)

This package contains the FastAPI backend and React/Vite frontend.
`node_modules` is intentionally not included. Install dependencies on your own computer so npm selects the correct Windows binaries.

## Requirements

- Python 3.11+ recommended
- Node.js 20+ recommended
- npm

## First-time setup

Double-click `SETUP_WINDOWS.bat`, or run these commands manually:

### Backend

```powershell
cd backend
python -m pip install -r requirements.txt
```

### Frontend

```powershell
cd frontend
npm install
```

## Run the application

After setup, double-click `RUN_DISASTERNET.bat`.

Or run manually in two terminals:

**Terminal 1 — backend**

```powershell
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2 — frontend**

```powershell
cd frontend
npm run dev
```

Open the Vite URL shown in the frontend terminal, normally:

- Frontend: http://localhost:5173
- Backend API: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Admin | admin@disasternet.gov.bd | admin123 |
| Government | govt@disasternet.gov.bd | govt123 |
| Organization | ngo@redcrescent.org.bd | ngo123 |
| Citizen | citizen@gmail.com | citizen123 |

## Important

Keep the backend terminal running while using the frontend. The frontend is configured to call the API at `http://localhost:8000/api`.

## Emergency Resource Request feature

The application now includes two additional registration roles:

- **Hospital** — register a hospital, request emergency medicine or medical equipment, update patient statistics, report emergency capacity, track incoming medical supplies, and submit expenditure reports.
- **Disaster Shelter** — register a shelter, update capacity and occupancy, manage shelter resources, request emergency supplies, report shortages, and record distributed resources.

Each role has a separate dashboard and role-restricted backend API. Hospital and shelter emergency requests continue to use the existing DisasterNet resource-request workflow so registered organizations can coordinate dispatches without changing the previous logistics module.

## Updated startup flow

For users who are not already signed in, `http://localhost:5173` now opens the **registration / sign-up page first**. The former Public Dashboard has been removed from the application. Use **Sign In** on the registration page if an account already exists.

## Frontend-to-backend connection

The frontend now calls `/api` on the Vite development server. Vite proxies those requests to `http://127.0.0.1:8000`. This keeps login, signup, Hospital, Shelter and all existing dashboard API calls on one reliable connection path and avoids Windows `localhost`/IPv4 resolution issues.

`RUN_DISASTERNET.bat` starts the backend first and waits until its health endpoint responds before starting the frontend. If the backend cannot start, the script stops and tells you to check the backend terminal instead of opening a frontend that would show `Failed to fetch`.

## Google Maps, Shelter Locator and Route Optimization

DisasterNet now supports the requested Google Maps Platform features without removing the previous fallback logic.

### One-time Google Maps setup

1. Create a Google Maps Platform API key in Google Cloud.
2. Enable billing for the Google Cloud project.
3. Enable these APIs/services:
   - Maps JavaScript API
   - Places API (New)
   - Routes API
   - Distance Matrix API (Legacy)
4. Double-click `SET_GOOGLE_MAPS_API_KEY.bat` and paste the API key.
5. Restart `RUN_DISASTERNET.bat`.

The key is written locally to `frontend/.env.local` and is not hard-coded into the source code.

### Disaster Map & Shelter Locator

The **Disaster Map & Shelters** tab is available from the shared navigation for every logged-in role. With a valid Google Maps key it displays:

- disaster locations saved in the DisasterNet database;
- organization warehouse locations saved in the inventory database;
- nearby hospitals from Google Places;
- nearby disaster/cyclone shelters from Google Places;
- a suggested driving evacuation route from the active disaster location to the nearest emergency facility;
- active in-transit relief-delivery routes.

When a government user declares a disaster, DisasterNet attempts to geocode the first affected district with Google Maps before saving the event so the database map coordinates match the affected area. If Google Maps is unavailable, the existing coordinates/fallback behavior remains available.

### Delivery & Route Optimization

From the Organization dashboard, **Run Route Optimization & Dispatch** now:

1. finds organization warehouses that can supply the requested category;
2. sends their coordinates and the request destination to Google Distance Matrix;
3. selects the shortest drivable route;
4. assigns the existing DisasterNet emergency vehicle identifier;
5. saves the selected warehouse, route distance, ETA and `In-Transit` status in the existing `resource_requests` database row;
6. deducts available stock using the existing inventory logic.

Google currently classifies the JavaScript Distance Matrix service as legacy/deprecated. DisasterNet therefore tries the requested Distance Matrix service first and can fall back to Google's current Route Matrix service if the legacy service is unavailable. If Google Maps itself is unavailable, the project's previous Haversine optimizer remains as the final no-error fallback.

## SSLCOMMERZ Payment Gateway API setup

The donor workflow uses SSLCOMMERZ Hosted Checkout. Store credentials remain on the FastAPI backend and are never exposed to React.

Configure `backend/.env` with your Sandbox credentials:

```env
SSLCOMMERZ_STORE_ID=YOUR_SANDBOX_STORE_ID
SSLCOMMERZ_STORE_PASSWORD=YOUR_SANDBOX_STORE_PASSWORD
SSLCOMMERZ_SANDBOX=true
SSLCOMMERZ_BASE_URL=https://sandbox.sslcommerz.com
SSLCOMMERZ_FRONTEND_URL=http://127.0.0.1:5173
SSLCOMMERZ_CALLBACK_BASE_URL=https://YOUR-PUBLIC-HTTPS-BACKEND
```

For local development, expose FastAPI port `8000` through a public HTTPS tunnel such as ngrok and use that URL for `SSLCOMMERZ_CALLBACK_BASE_URL`. In the SSLCOMMERZ Sandbox store settings, set the IPN URL to:

```text
https://YOUR-PUBLIC-HTTPS-BACKEND/api/sslcommerz/ipn
```

Then start DisasterNet:

```powershell
.\RUN_DISASTERNET.bat
```

### Implemented payment flow

- DisasterNet creates a unique donation tracking ID and SSLCOMMERZ transaction ID.
- FastAPI creates the SSLCOMMERZ checkout session and redirects the donor to the hosted payment page.
- Payment details are entered on SSLCOMMERZ, not stored in the DisasterNet frontend.
- Success/fail/cancel callbacks and IPN notifications return to FastAPI.
- FastAPI validates successful payments with SSLCOMMERZ before marking a donation as completed.
- Only a validated completed payment increases the campaign's collected funds.
- Donors can synchronize payment status from Donation History.
- Tracking ID, donor QR, campaign utilization, receipts and transparency records continue to use the verified donation record.
- Store credentials are kept in `backend/.env`, which is excluded by `backend/.gitignore`.

The SQLite path is anchored to `backend/disasternet.db`, so starting Uvicorn from a different working directory will not silently create a second database file.
