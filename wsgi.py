"""gunicorn 入口：gunicorn --bind :80 wsgi:app
本地开发：python wsgi.py
"""

import os

from app import create_app

app = create_app()

if __name__ == '__main__':
    # 仅本地开发用。云托管里由 gunicorn 接管。
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5000)), debug=True)
