from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import pymysql
import os
from datetime import datetime
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = "your_secret_key"

# ------------------ 1) 拉丁方 (循环移位) 生成 ------------------
def generate_latin_square_cyclic(N):
    """
    生成一个 N×N 的拉丁方 (循环移位)。
    row[i][j] = (i + j) % N + 1
    """
    square = []
    for i in range(N):
        row = []
        for j in range(N):
            val = (i + j) % N + 1
            row.append(val)
        square.append(row)
    return square

# 预先生成一个 9×9 的拉丁方，用于9篇文档的排列
LATIN_9x9 = generate_latin_square_cyclic(9)

# ------------------ 2) MySQL 连接 ------------------
def get_connection():
    """
    通过 MYSQL_URL 解析 MySQL DSN (host, port, user, password, db) 并返回连接
    """
    url = os.environ["MYSQL_URL"]  # e.g. "mysql://root:xxxx@containers-xxx:3306/railway"
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    user = parsed.username
    password = parsed.password
    db = parsed.path.lstrip('/')
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        db=db,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

# ------------------ 3) 初始化数据库表 ------------------
def init_db():
    """
    创建 queries, documents, orders, logs 四张表(若不存在)；
    并在 documents / queries 无数据时插入初始记录。
    """
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # --- logs 表 ---
            c.execute("SHOW TABLES LIKE 'logs'")
            if not c.fetchone():
                c.execute('''
                    CREATE TABLE logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id VARCHAR(100) NOT NULL,
                        doc_id VARCHAR(100),
                        event_type VARCHAR(255),
                        duration INT,
                        timestamp VARCHAR(255)
                    )
                ''')
                print("Created table: logs")

            # --- documents 表 ---
            c.execute("SHOW TABLES LIKE 'documents'")
            if not c.fetchone():
                c.execute('''
                    CREATE TABLE documents (
                        id INT PRIMARY KEY,
                        qid INT,
                        docno INT,
                        content TEXT
                    )
                ''')
                print("Created table: documents")

                # 仅示例插入部分文档，请按需补全
                docs_insert = [
                     (1, 1, 11, 'Higher average temperatures can speed up crop growth cycles, sometimes reducing yields and affecting crop quality.'),
                     (2, 1, 12, 'More frequent droughts, floods, and heatwaves threaten harvests and raise economic risks for farmers worldwide.'),
                     (3, 1, 13, 'Warmer climates allow pests and pathogens to expand their range, putting additional stress on crops and yields.'),
                     (4, 1, 14, 'Changes in rainfall patterns and competition for water resources make irrigation more challenging, particularly in arid regions.'),
                     (5, 1, 15, 'Fluctuating rain intensity and prolonged droughts erode topsoil and reduce soil fertility, requiring careful land management.'),
                     (6, 1, 16, 'As growing conditions change, farmers may need to adopt heat- or drought-tolerant crops or move to new planting zones.'),
                     (7, 1, 17, 'Extreme heat affects animal health, feed availability, and grazing land productivity, raising costs for livestock producers.'),
                     (8, 1, 18, 'Unpredictable harvests can drive up food prices and jeopardize global food supplies, hitting vulnerable populations the hardest.'),
                     (9, 1, 19, 'Techniques like organic farming, precision irrigation, and conservation tillage help enhance resilience against climate impacts.'),
                     (10, 2, 21, 'This is the content of Document 1 for Query 2.'),
                     (11, 2, 22, 'This is the content of Document 2 for Query 2.'),
                     (12, 2, 23, 'This is the content of Document 3 for Query 2.'),
                     (13, 2, 24, 'This is the content of Document 4 for Query 2.'),
                     (14, 2, 25, 'This is the content of Document 5 for Query 2.'),
                     (15, 2, 26, 'This is the content of Document 6 for Query 2.'),
                     (16, 2, 27, 'This is the content of Document 7 for Query 2.'),
                     (17, 2, 28, 'This is the content of Document 8 for Query 2.'),
                     (18, 2, 29, 'This is the content of Document 9 for Query 2.'),
                     (19, 3, 31, 'This is the content of Document 1 for Query 3.'),
                     (20, 3, 32, 'This is the content of Document 2 for Query 3.'),
                     (21, 3, 33, 'This is the content of Document 3 for Query 3.'),
                     (22, 3, 34, 'This is the content of Document 4 for Query 3.'),
                     (23, 3, 35, 'This is the content of Document 5 for Query 3.'),
                     (24, 3, 36, 'This is the content of Document 6 for Query 3.'),
                     (25, 3, 37, 'This is the content of Document 7 for Query 3.'),
                     (26, 3, 38, 'This is the content of Document 8 for Query 3.'),
                     (27, 3, 39, 'This is the content of Document 9 for Query 3.')
                ]
                insert_sql = """INSERT INTO documents (id, qid, docno, content)
                                VALUES (%s, %s, %s, %s, %s)"""
                c.executemany(insert_sql, docs_insert)
                print("Inserted initial documents data")

            # --- orders 表 ---
            c.execute("SHOW TABLES LIKE 'orders'")
            if not c.fetchone():
                c.execute('''
                    CREATE TABLE orders (
                        user_id VARCHAR(100) NOT NULL,
                        query_id INT NOT NULL,
                        doc_order TEXT,
                        PRIMARY KEY (user_id, query_id)
                    )
                ''')
                print("Created table: orders")

            # --- queries 表 ---
            c.execute("SHOW TABLES LIKE 'queries'")
            if not c.fetchone():
                c.execute('''
                    CREATE TABLE queries (
                        id INT PRIMARY KEY,
                        content TEXT
                    )
                ''')
                print("Created table: queries")

                # 插入3条查询
                c.executemany(
                    "INSERT INTO queries (id, content) VALUES (%s, %s, %s)",
                    [
                        (1, "Climate Change Impacts on Agriculture"),
                        (2, "How does climate change affect agriculture?"),
                        (3, "What are the causes of inflation?")
                    ]
                )
                print("Inserted initial queries data")

        conn.commit()
    finally:
        conn.close()

# ------------------ 4) 路由逻辑 ------------------

@app.route("/", methods=["GET", "POST"])
def index():
    """
    首页：用户输入 user_id 并勾选 T&C。
    """
    if request.method == "POST":
        user_id = request.form.get("user_id")
        terms = request.form.get("terms")
        if not terms:
            return render_template("index.html", error="Please accept the Terms and Conditions.")
        if not user_id:
            return render_template("index.html", error="Please enter your User ID.")
        session["user_id"] = user_id
        return redirect(url_for("query_page", query_id=1))
    return render_template("index.html")

@app.route("/query/<int:query_id>", methods=["GET", "POST"])
def query_page(query_id):
    """
    每个 user_id + query_id:
    1) 从 orders 表查看是否已有 doc_order；
    2) 若无 -> 用拉丁方行来重排 documents 并存入 orders；
    3) 再从 orders 拿 doc_order 并查询 documents 详情，按此顺序返回模板。
    4) queries 表里取出 query 内容(若有), 传给模板。
    """
    if "user_id" not in session:
        return redirect(url_for("index"))
    user_id = session["user_id"]

    if request.method == "POST":
        if query_id < 3:
            return redirect(url_for("query_page", query_id=query_id + 1))
        else:
            return redirect(url_for("thanks"))

    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 先从 queries 表获取此 query 的内容
            c.execute("SELECT content FROM queries WHERE id=%s", (query_id,))
            row_q = c.fetchone()
            if row_q:
                query_content = row_q["content"]
            else:
                query_content = f"Query {query_id} (No data)"

            # 再看 orders 表有没有记录
            c.execute("SELECT doc_order FROM orders WHERE user_id=%s AND query_id=%s", (user_id, query_id))
            row_o = c.fetchone()
            if row_o:
                # 已有顺序
                doc_order_str = row_o["doc_order"]
                doc_order = [int(x) for x in doc_order_str.split(",")]
            else:
                # 第一次 -> 生成 doc_order
                c.execute("SELECT id FROM documents WHERE qid=%s ORDER BY docno LIMIT 9", (query_id,))
                raw_doc_ids = [r["id"] for r in c.fetchall()]
                # 计算 row_index
                row_index = (abs(hash(user_id)) + query_id) % 9
                # 取拉丁方的一行
                perm = LATIN_9x9[row_index]  # e.g. [2,5,9,4,1,3,7,8,6]
                # 重排 doc_ids
                doc_order = [raw_doc_ids[perm[i] - 1] for i in range(9)]
                doc_order_str = ",".join(str(x) for x in doc_order)
                # 存到 orders
                c.execute("INSERT INTO orders (user_id, query_id, doc_order) VALUES (%s, %s, %s)",
                          (user_id, query_id, doc_order_str))
                conn.commit()

            # 根据 doc_order 获取文档详情
            if doc_order:
                placeholders = ",".join(["%s"] * len(doc_order))
                sql = f"SELECT id, content, docno FROM documents WHERE qid=%s AND id IN ({placeholders})"
                params = [query_id] + doc_order
                c.execute(sql, params)
                rows = c.fetchall()
                # 需手动reorder
                doc_map = {r["id"]: r for r in rows}
                docs = [doc_map[d] for d in doc_order if d in doc_map]
            else:
                docs = []

    finally:
        conn.close()

    return render_template("query.html", query_id=query_id, docs=docs, query_content=query_content)

@app.route("/thanks")
def thanks():
    return render_template("thanks.html")

@app.route("/pause")
def pause():
    return render_template("pause.html")

@app.route("/api/log", methods=["POST"])
def log_event():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    user_id = data.get('userId')
    doc_id = data.get('docId')
    event_type = data.get('eventType')
    duration = data.get('duration', 0)
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
init_db()
if __name__ == '__main__':
    # 容器/本地启动时，自动建表并插入初始数据
    app.run(host="0.0.0.0", port=5000)
