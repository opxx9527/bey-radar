from flask import Flask, request, abort
import os

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar is running 🌀"

@app.route("/webhook", methods=["POST"])
def webhook():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
