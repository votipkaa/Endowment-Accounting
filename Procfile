release: flask db upgrade
web: gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120
