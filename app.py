from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import pymysql
import os
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Must be set for session usage

# 1) 建立 MySQL 连接函数，从环境变量读取连接信息
def get_connection():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        db=os.environ["MYSQL_DATABASE"],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

# 2) 定义查询页面内容
QUERY_CONTENTS = {
    1: "Climate Change Impacts on Agriculture",
    2: "Renewable Energy Technologies",
    3: "Advances in Artificial Intelligence"
}

# 3) 在MySQL里初始化数据表(只在容器启动时执行一次)
def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 创建 logs 表
            c.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(100) NOT NULL,
                    doc_id VARCHAR(100),
                    event_type VARCHAR(255),
                    duration INT,
                    timestamp VARCHAR(255)
                )
            ''')
            # 创建 documents 表
            c.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id INT PRIMARY KEY,
                    qid INT,
                    docno INT,
                    title TEXT,
                    content TEXT
                )
            ''')
            # 检查 documents 表是否已有数据
            c.execute("SELECT COUNT(*) as cnt FROM documents")
            row = c.fetchone()
            if row and row["cnt"] == 0:
                # 插入初始文档数据 (不能用 executescript, 用多次execute或multi statements)
                docs_insert = [
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
                    (27, 3, 39, 'Document 9', 'This is the content of Document 9 for Query 3.')
                ]
                insert_sql = "INSERT INTO documents (id, qid, docno, title, content) VALUES (%s, %s, %s, %s, %s)"
                c.executemany(insert_sql, docs_insert)
        conn.commit()
    finally:
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
            return redirect(url_for("query_page", query_id=query_id + 1))
        else:
            return redirect(url_for("thanks"))
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 这里 SELECT 了 docno, 以便在模板中使用 data-docno
            c.execute("SELECT id, title, content, docno FROM documents WHERE qid = %s ORDER BY docno LIMIT 9", (query_id,))
            rows = c.fetchall()
    finally:
        conn.close()

    docs = [{"id": row["id"], "title": row["title"], "content": row["content"], "docno": row["docno"]} for row in rows]
    # Randomize document order for now
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

    conn = get_connection()
    try:
        with conn.cursor() as c:
            sql = """
                INSERT INTO logs (user_id, doc_id, event_type, duration, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            """
            c.execute(sql, (user_id, doc_id, event_type, duration, timestamp))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'Log received'}), 200

@app.route("/pause")
def pause():
    return render_template("pause.html")

if __name__ == '__main__':
    # 在容器启动时自动建表并插入数据(若尚未插入)
    init_db()
    # 在本地调试可改成 debug=True, port=5000
    app.run(host="0.0.0.0", port=5000)
