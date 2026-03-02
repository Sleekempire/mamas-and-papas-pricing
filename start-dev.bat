@echo off
echo ===================================================
echo  PricingOptimiser — Local Development Startup
echo ===================================================
echo.

:: Check if .env exists
if not exist ".env" (
    echo [INFO] Copying .env.template to .env for development...
    copy .env.template .env
)

:: Install dependencies
echo [INFO] Installing Python dependencies...
cd backend
pip install -r requirements.txt -q
echo [OK] Dependencies installed.
echo.

:: Start the API server
echo [INFO] Starting FastAPI server on http://localhost:8000
echo [INFO] API docs available at http://localhost:8000/api/docs
echo [INFO] Frontend: open frontend\login.html in your browser
echo.
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
