from flask import Flask, jsonify, render_template, request

from chatbot import FAQBot

app = Flask(__name__)
bot = FAQBot()


@app.route("/")
def home():
    return render_template("index.html", starters=bot.starter_questions())


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Message is empty"}), 400

    history = data.get("history") or []
    return jsonify(bot.respond(message[:300], history))


if __name__ == "__main__":
    app.run(debug=True)