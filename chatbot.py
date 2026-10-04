import json
import os
import re
from pathlib import Path

import nltk
import numpy as np
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def ensure_nltk_data():
    checks = [
        (("punkt", "punkt_tab"), lambda: word_tokenize("test")),
        (("stopwords",), lambda: stopwords.words("english")),
    ]

    for packages, check in checks:
        try:
            check()
        except LookupError:
            for package in packages:
                nltk.download(package)


ensure_nltk_data()

FAQ_FILE = Path(__file__).parent / "faqs.json"

MATCH_THRESHOLD = 0.35
SUGGEST_THRESHOLD = 0.10
CONTEXT_FAQS = 4

AI_MODELS = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-3.5-flash", "gemini-2.5-flash") if m]

KEEP_WORDS = {"where", "when", "why", "not", "no"}

GREETINGS = {"hi", "hello", "hey", "hii", "hola", "namaste", "yo"}
THANKS = {"thanks", "thank", "thx", "thankyou"}
GOODBYES = {"bye", "goodbye", "cya"}

SYSTEM_PROMPT = """You are the customer support assistant for ShopEase, an online store.

You are given FAQ entries that were retrieved for the customer's message. Use them as your source of truth for store policies.

Rules:
- Answer the customer's actual situation, not just the nearest FAQ. Be warm, direct and brief (2 to 5 sentences).
- If the customer describes a problem such as a late, lost or damaged order, acknowledge it, say what is normal according to the FAQs, and give clear next steps.
- You cannot see orders, accounts or tracking data. Never invent order status, dates, compensation or policies that are not in the FAQs.
- If the FAQs do not cover the question, say so honestly and point the customer to support: chat here, email support@shopease.example, or call 1800-000-000 (9 AM to 9 PM, Monday to Saturday).
- Reply in plain text with no markdown and no bullet symbols. Write in the customer's language when possible."""


def clean_history(history):
    cleaned = []

    for item in (history or [])[-8:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = str(item.get("content", "")).strip()[:500]

        if role not in ("user", "assistant") or not content:
            continue

        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += "\n" + content
        else:
            cleaned.append({"role": role, "content": content})

    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)

    if cleaned and cleaned[-1]["role"] == "user":
        cleaned.pop()

    return cleaned


class FAQBot:
    def __init__(self):
        self.faqs = json.loads(FAQ_FILE.read_text(encoding="utf-8"))
        self.stop_words = set(stopwords.words("english")) - KEEP_WORDS
        self.stemmer = PorterStemmer()
        self.client = None

        documents = []
        owners = []

        for index, faq in enumerate(self.faqs):
            texts = [faq["question"]] + faq.get("variants", [])
            if faq.get("keywords"):
                texts.append(faq["keywords"])

            for text in texts:
                documents.append(self.preprocess(text))
                owners.append(index)

        self.owners = np.array(owners)
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform(documents)

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        if api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
                print("AI answers: ON (Gemini)")
            except ImportError:
                print("AI answers: OFF (run: pip install google-genai)")
        else:
            print("AI answers: OFF (set GEMINI_API_KEY to turn on)")

    def preprocess(self, text):
        text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        tokens = word_tokenize(text)
        tokens = [t for t in tokens if t not in self.stop_words]
        tokens = [self.stemmer.stem(t) for t in tokens]
        return " ".join(tokens)

    def starter_questions(self, count=4):
        return [faq["question"] for faq in self.faqs[:count]]

    def small_talk(self, message):
        words = set(re.findall(r"[a-z]+", message.lower()))

        if len(words) > 4:
            return None
        if words & GREETINGS:
            return "Hello! I am the ShopEase assistant. Ask me about orders, shipping, returns or payments."
        if words & THANKS:
            return "You are welcome! Let me know if there is anything else I can help with."
        if words & GOODBYES:
            return "Goodbye! Have a great day."
        return None

    def faq_scores(self, message):
        cleaned = self.preprocess(message)
        if not cleaned:
            return None

        query = self.vectorizer.transform([cleaned])
        doc_scores = cosine_similarity(query, self.matrix)[0]

        scores = np.zeros(len(self.faqs))
        np.maximum.at(scores, self.owners, doc_scores)
        return scores

    def reply(self, message):
        talk = self.small_talk(message)
        if talk:
            return {"answer": talk, "confidence": 1.0, "matched": None, "suggestions": []}

        scores = self.faq_scores(message)
        if scores is None:
            return self.fallback([])

        ranked = scores.argsort()[::-1]
        best = int(ranked[0])

        if scores[best] >= MATCH_THRESHOLD:
            return {
                "answer": self.faqs[best]["answer"],
                "confidence": round(float(scores[best]), 2),
                "matched": self.faqs[best]["question"],
                "suggestions": [],
            }

        close = [self.faqs[int(i)]["question"] for i in ranked[:3] if scores[int(i)] >= SUGGEST_THRESHOLD]
        return self.fallback(close)

    def respond(self, message, history=None):
        talk = self.small_talk(message)
        if talk:
            return {"answer": talk, "confidence": 1.0, "matched": None, "suggestions": []}

        if self.client is None:
            return self.reply(message)

        try:
            return self.ai_reply(message, history)
        except Exception as error:
            print("AI error, using FAQ matching instead:", error)
            return self.reply(message)

    def ai_reply(self, message, history):
        from google.genai import types

        scores = self.faq_scores(message)
        if scores is None:
            scores = np.zeros(len(self.faqs))

        top = scores.argsort()[::-1][:CONTEXT_FAQS]
        context = "\n\n".join(
            f"FAQ {n + 1}\nQuestion: {self.faqs[int(i)]['question']}\nAnswer: {self.faqs[int(i)]['answer']}"
            for n, i in enumerate(top)
        )

        prompt = f"Retrieved FAQ entries, most similar first:\n\n{context}\n\nCustomer message: {message}"
        messages = clean_history(history) + [{"role": "user", "content": prompt}]

        contents = [
            types.Content(
                role="user" if item["role"] == "user" else "model",
                parts=[types.Part(text=item["content"])],
            )
            for item in messages
        ]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=1024,
            temperature=0.4,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        answer = ""
        last_error = None

        for model in AI_MODELS:
            try:
                response = self.client.models.generate_content(model=model, contents=contents, config=config)
                answer = (response.text or "").strip()
                if answer:
                    break
            except Exception as error:
                last_error = error

        if not answer:
            raise last_error or ValueError("Empty AI response")

        return {"answer": answer, "confidence": round(float(scores.max()), 2), "matched": None, "suggestions": []}

    def fallback(self, suggestions):
        if suggestions:
            text = "I am not sure I understood. Did you mean one of these?"
        else:
            text = "Sorry, I could not find an answer to that. Here are some things I can help with:"
            suggestions = self.starter_questions(3)

        return {"answer": text, "confidence": 0.0, "matched": None, "suggestions": suggestions}