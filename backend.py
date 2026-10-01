import os, sqlite3, secrets, hashlib, hmac, base64, json
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

APP = Flask(__name__)
CORS(APP, origins="*")  # Restrict to your GitHub Pages URL before production.

DB_PATH = os.getenv("CLASSFLOW_WEB_DB", "classflow_web.db")
CASHFREE_CLIENT_ID = os.getenv("CASHFREE_CLIENT_ID", "")
CASHFREE_CLIENT_SECRET = os.getenv("CASHFREE_CLIENT_SECRET", "")
CASHFREE_API_VERSION = os.getenv("CASHFREE_API_VERSION", "2025-01-01")
CASHFREE_BASE = os.getenv("CASHFREE_BASE", "https://sandbox.cashfree.com")
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "https://inderrr777.github.io/CLASSFLOW/")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
MODE = os.getenv("CASHFREE_MODE", "sandbox")

PLANS = {"Basic": 3999, "Pro": 5999}

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con=db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions(
      token TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS orders(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      plan TEXT NOT NULL,
      amount INTEGER NOT NULL,
      cashfree_order_id TEXT UNIQUE,
      payment_session_id TEXT,
      status TEXT NOT NULL DEFAULT 'CREATED',
      created_at TEXT NOT NULL
    );
    """)
    con.commit(); con.close()

def now():
    return datetime.now(timezone.utc).isoformat()

def hash_password(p):
    salt=secrets.token_bytes(16)
    dk=hashlib.pbkdf2_hmac("sha256",p.encode(),salt,210000)
    return base64.b64encode(salt+dk).decode()

def verify_password(p, stored):
    raw=base64.b64decode(stored.encode())
    salt, expected=raw[:16], raw[16:]
    actual=hashlib.pbkdf2_hmac("sha256",p.encode(),salt,210000)
    return hmac.compare_digest(actual,expected)

def auth_user():
    auth=request.headers.get("Authorization","")
    if not auth.startswith("Bearer "): return None
    con=db()
    row=con.execute("""
      SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
      WHERE s.token=?
    """,(auth[7:],)).fetchone()
    con.close()
    return row

init_db()

@APP.get("/")
def root():
    return jsonify({"ok": True, "service": "classflow-web-backend", "message": "ClassFlow backend is live"})

@APP.get("/api/health")
def health():
    return jsonify({"ok":True,"service":"classflow-web-backend","mode":MODE})

@APP.post("/api/signup")
def signup():
    data=request.get_json(force=True)
    name=str(data.get("name","")).strip()
    email=str(data.get("email","")).strip().lower()
    password=str(data.get("password",""))
    if not name or not email or len(password)<6:
        return jsonify({"detail":"Name, valid email and password (6+ characters) are required."}),400
    con=db()
    try:
        cur=con.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                        (name,email,hash_password(password),now()))
        uid=cur.lastrowid
        tok=secrets.token_urlsafe(48)
        con.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",(tok,uid,now()))
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        return jsonify({"detail":"An account with this email already exists. Use Existing user / Sign in."}),409
    con.close()
    return jsonify({"access_token":tok,"user":{"id":uid,"name":name,"email":email}})

@APP.post("/api/login")
def login():
    data=request.get_json(force=True)
    email=str(data.get("email","")).strip().lower()
    password=str(data.get("password",""))
    con=db(); row=con.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
    if not row or not verify_password(password,row["password_hash"]):
        con.close(); return jsonify({"detail":"Invalid email or password."}),401
    tok=secrets.token_urlsafe(48)
    con.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",(tok,row["id"],now()))
    con.commit(); con.close()
    return jsonify({"access_token":tok,"user":{"id":row["id"],"name":row["name"],"email":row["email"]}})

@APP.post("/api/create-order")
def create_order():
    user=auth_user()
    if not user: return jsonify({"detail":"Please sign in first."}),401
    data=request.get_json(force=True)
    plan=str(data.get("plan",""))
    if plan not in PLANS: return jsonify({"detail":"Invalid plan."}),400
    amount=PLANS[plan]  # Never trust the browser's price.
    if not CASHFREE_CLIENT_ID or not CASHFREE_CLIENT_SECRET:
        return jsonify({"detail":"Cashfree sandbox keys are not configured on the backend."}),500

    order_id="CF_"+secrets.token_hex(10)
    payload={
      "order_id":order_id,
      "order_amount":amount,
      "order_currency":"INR",
      "customer_details":{
        "customer_id":"classflow_"+str(user["id"]),
        "customer_name":user["name"],
        "customer_email":user["email"]
      },
      "order_meta":{
        "return_url":PUBLIC_SITE_URL+"?payment=return&order_id={order_id}",
        **({"notify_url":WEBHOOK_URL} if WEBHOOK_URL else {})
      },
      "order_note":f"ClassFlow {plan} subscription"
    }
    headers={
      "x-client-id":CASHFREE_CLIENT_ID,
      "x-client-secret":CASHFREE_CLIENT_SECRET,
      "x-api-version":CASHFREE_API_VERSION,
      "Content-Type":"application/json"
    }
    r=requests.post(CASHFREE_BASE+"/pg/orders",headers=headers,json=payload,timeout=30)
    if r.status_code>=300:
        return jsonify({"detail":"Cashfree order creation failed.","cashfree_status":r.status_code,"cashfree_response":r.text[:1000]}),502
    cf=r.json()
    con=db()
    con.execute("""INSERT INTO orders(user_id,plan,amount,cashfree_order_id,payment_session_id,status,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (user["id"],plan,amount,cf.get("order_id"),cf.get("payment_session_id"),"CREATED",now()))
    con.commit(); con.close()
    return jsonify({"payment_session_id":cf.get("payment_session_id"),"mode":MODE,"order_id":cf.get("order_id")})

@APP.post("/api/cashfree/webhook")
def cashfree_webhook():
    # TODO before production: implement Cashfree webhook signature verification
    # using Cashfree's current signature specification, then update the order
    # idempotently. Never mark an order paid from an unverified browser redirect.
    raw=request.get_data()
    try: data=request.get_json(force=True)
    except Exception: data={"raw":raw.decode("utf-8","ignore")}
    print("CASHFREE WEBHOOK:",json.dumps(data)[:5000])
    return jsonify({"ok":True})

if __name__=="__main__":
    init_db()
    APP.run(host="0.0.0.0",port=int(os.getenv("PORT","8000")))
