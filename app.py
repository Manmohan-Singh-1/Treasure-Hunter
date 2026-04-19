"""
AI Treasure Hunt Creator
API: Groq (llama-3.3-70b-versatile) — FREE, 14400 req/day
Framework: Flask + SQLite
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3
import json
import os
import uuid
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "treasure-hunt-secret-2025")
CORS(app)

# ─── Groq Client ───────────────────────────────────────────────────
groq_api_key = os.environ.get("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("GROQ_API_KEY environment variable not set. Please add it to .env file.")
client = Groq(api_key=groq_api_key)
MODEL = "llama-3.3-70b-versatile"

# ─── Database ──────────────────────────────────────────────────────
DB_PATH = "database/treasure_hunt.db"

def init_db():
    os.makedirs("database", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS players (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        total_hunts INTEGER DEFAULT 0, total_solved INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS hunts (
        id TEXT PRIMARY KEY, player_id TEXT NOT NULL,
        theme TEXT NOT NULL, difficulty TEXT NOT NULL,
        title TEXT NOT NULL, treasure TEXT NOT NULL,
        clues_json TEXT NOT NULL, total_clues INTEGER NOT NULL,
        solved_count INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hunt_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS clue_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hunt_id TEXT NOT NULL, clue_index INTEGER NOT NULL,
        attempt TEXT NOT NULL, is_correct INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()
    print("Database ready!")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/player", methods=["POST"])
def create_player():
    data = request.json
    name = data.get("name", "Explorer").strip()
    player_id = str(uuid.uuid4())
    db = get_db()
    try:
        db.execute("INSERT INTO players (id, name) VALUES (?, ?)", (player_id, name))
        db.commit()
        return jsonify({"success": True, "player_id": player_id, "name": name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/generate_hunt", methods=["POST"])
def generate_hunt():
    data = request.json
    theme      = data.get("theme", "nature")
    difficulty = data.get("difficulty", "medium")
    clue_count = int(data.get("clue_count", 4))
    player_id  = data.get("player_id")
    player_name = data.get("player_name", "Explorer")
    temperature = float(data.get("temperature", 0.7))
    top_p       = float(data.get("top_p", 0.9))

    # Override temperature and top_p based on difficulty if not provided
    if "temperature" not in data:
        temp_map   = {"easy": 0.5, "medium": 0.7, "hard": 0.9}
        temperature = temp_map.get(difficulty, 0.7)
    if "top_p" not in data:
        top_p_map  = {"easy": 0.8, "medium": 0.9, "hard": 1.0}
        top_p = top_p_map.get(difficulty, 0.9)

    system_prompt = """You are a master treasure hunt creator.
Your job is to return ONLY valid raw JSON — no markdown, no backticks, no explanation."""

    user_prompt = f"""Create a treasure hunt with exactly {clue_count} clues.
Theme: "{theme}"
Difficulty: "{difficulty}"

Return ONLY this JSON structure:
{{
  "title": "short evocative title (max 6 words)",
  "intro": "2-sentence atmospheric opening",
  "clues": [
    {{
      "riddle": "vivid atmospheric riddle (2-3 sentences)",
      "hint": "subtle one-sentence nudge (no direct answer)",
      "answer": "one or two word answer (lowercase)",
      "explanation": "one sentence why this answer is correct"
    }}
  ],
  "treasure": "one exciting sentence about the final reward",
  "domain_facts": ["fact 1 about {theme}", "fact 2", "fact 3"]
}}

Difficulty rules:
- easy: simple words, obvious clues, common knowledge
- medium: layered metaphors, some domain knowledge needed
- hard: cryptic wordplay, deep knowledge required"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=temperature,
            top_p=top_p,
            max_tokens=1500,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ]
        )

        raw = response.choices[0].message.content.strip()

        # Strip accidental markdown fences
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw = part
                    break

        hunt_data = json.loads(raw)

        # Save to DB
        hunt_id = str(uuid.uuid4())
        db = get_db()
        if player_id:
            db.execute("UPDATE players SET total_hunts = total_hunts + 1 WHERE id = ?", (player_id,))
        db.execute("""INSERT INTO hunts
            (id, player_id, theme, difficulty, title, treasure, clues_json, total_clues)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (hunt_id, player_id or "guest", theme, difficulty,
             hunt_data["title"], hunt_data["treasure"],
             json.dumps(hunt_data["clues"]), len(hunt_data["clues"])))

        intro = (f"Welcome, {player_name}! Your hunt: \"{hunt_data['title']}\". "
                 f"{hunt_data['intro']} You have {len(hunt_data['clues'])} clues. Good luck!")
        db.execute("INSERT INTO chat_messages (hunt_id, role, content) VALUES (?, ?, ?)",
                   (hunt_id, "assistant", intro))
        db.commit()
        db.close()

        return jsonify({
            "success": True,
            "hunt_id": hunt_id,
            "hunt": hunt_data,
            "model_config": {
                "model": MODEL,
                "temperature": temperature,
                "top_p": top_p,
                "difficulty": difficulty
            }
        })

    except json.JSONDecodeError as e:
        return jsonify({"success": False, "error": f"JSON error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    hunt_id         = data.get("hunt_id")
    user_message    = data.get("message", "")
    clues           = data.get("clues", [])
    current_idx     = data.get("current_clue", 0)
    solved          = data.get("solved", [])
    player_name     = data.get("player_name", "Explorer")
    theme           = data.get("theme", "unknown")
    temperature     = float(data.get("temperature", 0.8))
    top_p           = float(data.get("top_p", 0.9))

    if not hunt_id or not user_message:
        return jsonify({"success": False, "error": "Missing data"}), 400

    # Load chat history from DB
    db = get_db()
    rows = db.execute(
        "SELECT role, content FROM chat_messages WHERE hunt_id = ? ORDER BY created_at ASC LIMIT 20",
        (hunt_id,)
    ).fetchall()
    db.close()

    clue_context = "\n".join([
        f"Clue {i+1}: \"{c['riddle']}\" | answer: \"{c['answer']}\" | hint: \"{c['hint']}\" | solved: {solved[i] if i < len(solved) else False}"
        for i, c in enumerate(clues)
    ])
    current_clue = clues[current_idx] if current_idx < len(clues) else None

    system_prompt = f"""You are The Oracle — a mysterious, enthusiastic treasure hunt guide.
Player: {player_name}. Theme: {theme}.
All clues:
{clue_context}
Active clue #{current_idx + 1} of {len(clues)}.
Answer (NEVER reveal directly): "{current_clue['answer'] if current_clue else 'N/A'}"
Hint to give if asked: "{current_clue['hint'] if current_clue else ''}"
Rules: Be atmospheric, match the theme. Never give the answer directly. Max 2-3 sentences. Use emojis sometimes."""

    # Build message history for Groq
    messages = [{"role": "system", "content": system_prompt}]
    for row in rows[-12:]:
        messages.append({"role": row["role"], "content": row["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=temperature,
            top_p=top_p,
            max_tokens=300,
            messages=messages
        )
        reply = response.choices[0].message.content.strip()

        db = get_db()
        db.execute("INSERT INTO chat_messages (hunt_id, role, content) VALUES (?, ?, ?)",
                   (hunt_id, "user", user_message))
        db.execute("INSERT INTO chat_messages (hunt_id, role, content) VALUES (?, ?, ?)",
                   (hunt_id, "assistant", reply))
        db.commit()
        db.close()

        return jsonify({"success": True, "reply": reply})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/check_answer", methods=["POST"])
def check_answer():
    data = request.json
    hunt_id        = data.get("hunt_id")
    clue_index     = data.get("clue_index", 0)
    user_answer    = data.get("answer", "").strip().lower()
    correct_answer = data.get("correct_answer", "").strip().lower()

    is_correct = (
        user_answer == correct_answer or
        correct_answer in user_answer or
        user_answer in correct_answer or
        all(w in user_answer for w in correct_answer.split())
    )

    db = get_db()
    db.execute("INSERT INTO clue_attempts (hunt_id, clue_index, attempt, is_correct) VALUES (?, ?, ?, ?)",
               (hunt_id, clue_index, user_answer, 1 if is_correct else 0))
    if is_correct:
        db.execute("UPDATE hunts SET solved_count = solved_count + 1 WHERE id = ?", (hunt_id,))
    db.commit()
    db.close()

    return jsonify({"success": True, "is_correct": is_correct})


@app.route("/api/complete_hunt", methods=["POST"])
def complete_hunt():
    data = request.json
    hunt_id   = data.get("hunt_id")
    player_id = data.get("player_id")
    db = get_db()
    db.execute("UPDATE hunts SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?", (hunt_id,))
    if player_id:
        db.execute("UPDATE players SET total_solved = total_solved + 1 WHERE id = ?", (player_id,))
    db.commit()
    db.close()
    return jsonify({"success": True})


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    db = get_db()
    rows = db.execute("""
        SELECT p.name, p.total_hunts, p.total_solved,
               COUNT(CASE WHEN h.status='completed' THEN 1 END) as completed
        FROM players p LEFT JOIN hunts h ON h.player_id = p.id
        GROUP BY p.id ORDER BY completed DESC, p.total_solved DESC LIMIT 10
    """).fetchall()
    db.close()
    return jsonify({"success": True, "leaderboard": [dict(r) for r in rows]})


@app.route("/api/stats/<hunt_id>", methods=["GET"])
def hunt_stats(hunt_id):
    db = get_db()
    hunt = db.execute("SELECT * FROM hunts WHERE id=?", (hunt_id,)).fetchone()
    attempts = db.execute(
        "SELECT clue_index, COUNT(*) as tries, SUM(is_correct) as correct FROM clue_attempts WHERE hunt_id=? GROUP BY clue_index",
        (hunt_id,)).fetchall()
    db.close()
    if not hunt:
        return jsonify({"success": False, "error": "Not found"}), 404
    return jsonify({"success": True, "hunt": dict(hunt), "attempts": [dict(a) for a in attempts]})


if __name__ == "__main__":
    init_db()
    print("AI Treasure Hunt (Groq) running at http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
