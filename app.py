from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import sqlite3
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Must be set for session usage

# Define the query text for each query page (qid 1, 2, and 3)
QUERY_CONTENTS = {
    1: "Climate Change Impacts on Agriculture",
    2: "Renewable Energy Technologies",
    3: "Advances in Artificial Intelligence"
}

# Initialize the database (create logs and documents tables, and insert initial data)
def init_db():
    conn = sqlite3.connect('survey.db')
    c = conn.cursor()
    # Create logs table
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            doc_id TEXT,
            event_type TEXT,
            duration INTEGER,
            timestamp TEXT
        )
    ''')
    # Create documents table with qid and docno fields
    c.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            qid INTEGER,
            docno INTEGER,
            title TEXT,
            content TEXT
        )
    ''')
    # If the documents table is empty, insert initial data
    c.execute("SELECT COUNT(*) FROM documents")
    if c.fetchone()[0] == 0:
        c.executescript('''
            INSERT INTO documents (id, qid, docno, title, content) VALUES
            (1, 1, 11, 'Rising Temperatures and Crop Yields', 'Higher average temperatures can speed up crop growth cycles, sometimes reducing yields and affecting crop quality.'),
            (2, 1, 12, 'Increased Extreme Weather Events', 'More frequent droughts, floods, and heatwaves threaten harvests and raise economic risks for farmers worldwide.'),
            (3, 1, 13, 'Spread of Pests and Diseases', 'Warmer climates allow pests and pathogens to expand their range, putting additional stress on crops and yields.'),
            (4, 1, 14, 'Water Scarcity', 'Changes in rainfall patterns and competition for water resources make irrigation more challenging, particularly in arid regions.'),
            (5, 1, 15, 'Soil Degradation and Erosion', 'Fluctuating rain intensity and prolonged droughts erode topsoil and reduce soil fertility, requiring careful land management.'),
            (6, 1, 16, 'Shifts in Planting Patterns', 'As growing conditions change, farmers may need to adopt heat- or drought-tolerant crops or move to new planting zones.'),
            (7, 1, 17, 'Livestock Vulnerability', 'Extreme heat affects animal health, feed availability, and grazing land productivity, raising costs for livestock producers.'),
            (8, 1, 18, 'Economic and Food Security Risks', 'Unpredictable harvests can drive up food prices and jeopardize global food supplies, hitting vulnerable populations the hardest.'),
            (9, 1, 19, 'Sustainable Agricultural Practices', 'Techniques like organic farming, precision irrigation, and conservation tillage help enhance resilience against climate impacts.'),
            (10, 2, 21, 'Document 1', 'This is the content of Document 1 for Query 2.'),
            (11, 2, 22, 'Document 2', 'This is the content of Document 2 for Query 2.'),
            (12, 2, 23, 'Document 3', 'This is the content of Document 3 for Query 2.'),
            (13, 2, 24, 'Document 4', 'This is the content of Document 4 for Query 2.'),
            (14, 2, 25, 'Document 5', 'This is the content of Document 5 for Query 2.'),
            (15, 2, 26, 'Document 6', 'This is the content of Document 6 for Query 2.'),
            (16, 2, 27, 'Document 7', 'This is the content of Document 7 for Query 2.'),
            (17, 2, 28, 'Document 8', 'This is the content of Document 8 for Query 2.'),
            (18, 2, 29, 'Document 9', 'This is the content of Document 9 for Query 2.'),
            (19, 3, 31, 'Document 1', 'This is the content of Document 1 for Query 3.'),
            (20, 3, 32, 'Document 2', 'This is the content of Document 2 for Query 3.'),
            (21, 3, 33, 'Document 3', 'This is the content of Document 3 for Query 3.'),
            (22, 3, 34, 'Document 4', 'This is the content of Document 4 for Query 3.'),
            (23, 3, 35, 'Document 5', 'This is the content of Document 5 for Query 3.'),
            (24, 3, 36, 'Document 6', 'This is the content of Document 6 for Query 3.'),
            (25, 3, 37, 'Document 7', 'This is the content of Document 7 for Query 3.'),
            (26, 3, 38, 'Document 8', 'This is the content of Document 8 for Query 3.'),
            (27, 3, 39, 'Document 9', 'This is the content of Document 9 for Query 3.');
        ''')
    conn.commit()
    conn.close()

# Index page: Display Terms & Conditions and User ID input
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        user_id = request.form.get("user_id")
        terms = request.form.get("terms")
        if not terms:
            return render_template("index.html", error="Please accept the Terms and Conditions.")
        if not user_id:
            return render_template("index.html", error="Please enter your User ID.")
        session["user_id"] = user_id  # Save user ID in session
        return redirect(url_for("query", query_id=1))
    return render_template("index.html")

# Query page: query_id indicates which query (total 3 queries)
@app.route("/query/<int:query_id>", methods=["GET", "POST"])
def query(query_id):
    if "user_id" not in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        if query_id < 3:
            return redirect(url_for("query", query_id=query_id + 1))
        else:
            return redirect(url_for("thanks"))
    conn = sqlite3.connect('survey.db')
    c = conn.cursor()
    c.execute("SELECT id, title, content, docno FROM documents WHERE qid = ? ORDER BY docno LIMIT 9", (query_id,))
    docs = [{"id": row[0], "title": row[1], "content": row[2], "docno": row[3]} for row in c.fetchall()]
    conn.close()
    # Randomize document order for now; later replace with Latin square ordering
    random.shuffle(docs)
    # Get the query content for this qid
    query_content = QUERY_CONTENTS.get(query_id, "")
    return render_template("query.html", query_id=query_id, docs=docs, query_content=query_content)

# Thank-you page
@app.route("/thanks")
def thanks():
    return render_template("thanks.html")

# API endpoint: Record click, unclick, and other events
@app.route("/api/log", methods=["POST"])
def log_event():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    user_id = data.get('userId')
    doc_id = data.get('docId')
    event_type = data.get('eventType')
    duration = data.get('duration', 0)  # Optionally record duration
    timestamp = datetime.now().isoformat()
    conn = sqlite3.connect('survey.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO logs (user_id, doc_id, event_type, duration, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, doc_id, event_type, duration, timestamp))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Log received'}), 200

@app.route("/pause")
def pause():
    return render_template("pause.html")

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
