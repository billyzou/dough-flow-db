import os

SQLALCHEMY_DATABASE_URI = "postgresql+psycopg2://superset:superset@postgres/superset_meta"
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "")
