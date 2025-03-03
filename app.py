from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import pymysql
import os
from datetime import datetime
import random
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Must be set for session usage

# 定义每个查询页面对应的查询内容
QUERY_CONTENTS = {
    1: "Climate Change Impacts on Agriculture",
    2: "Renewable Energy Technologies",
    3: "Advances in Artificial Intelligence"
}

def generate_latin_square_cyclic(N):
    """
    使用循环移位（Cyclic）算法生成一个 N×N 的拉丁方。
    拉丁方定义：每行、每列都包含数字 1..N 而且不重复。
    
    循环移位规则：
      square[i][j] = ((i + j) % N) + 1
    
    :param N: 方阵大小
    :return: 一个 N×N 的列表 (list of lists)，其中每个元素是一个整数
    """
    square = []
    for i in range(N):
        row = []
        for j in range(N):
            val = (i + j) % N + 1
            row.append(val)
        square.append(row)
    return square
    
square_9 = generate_latin_square_cyclic(9)

def get_connection():
    """
    解析 MYSQL_URL（如 'mysql://root:xxxx@host:3306/railway'），返回 PyMySQL 连接。
    """
    url = os.environ["MYSQL_URL"]
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

def init_db():
    """
    在 MySQL 中初始化 logs, documents, orders 三张表。
    若 documents 为空则插入初始文档数据。
    """
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 1) logs 表
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

            # 2) documents 表
            c.execute("SHOW TABLES LIKE 'documents'")
            if not c.fetchone():
                c.execute('''
                    CREATE TABLE documents (
                        id INT PRIMARY KEY,
                        qid INT,
                        docno INT,
                        title TEXT,
                        content TEXT
                    )
                ''')
                print("Created table: documents")

                # 插入初始文档数据
                docs_insert = [
                    (1, 1, 11, 'Rising Temperatures and Crop Yields', 'Higher average temperatures...'),
                    (2, 1, 12, 'Increased Extreme Weather Events', 'More frequent droughts...'),
                    (3, 1, 13, 'Spread of Pests and Diseases', 'Warmer climates allow pests...'),
                    # ... 略，其余文档同你之前的 ...
                    (9, 1, 19, 'Sustainable Agricultural Practices', 'Techniques like organic farming...'),
                    (10, 2, 21, 'Document 1', 'This is the content of Document 1 for Query 2.'),
                    # ... 继续插入 ...
                    (27, 3, 39, 'Document 9', 'This is the content of Document 9 for Query 3.')
                ]
                insert_sql = """INSERT INTO documents (id, qid, docno, title, content) 
                                VALUES (%s, %s, %s, %s, %s)"""
                c.executemany(insert_sql, docs_insert)
                print("Inserted initial documents data")

            # 3) orders 表：存储 (user_id, query_id) -> doc_order
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

        conn.commit()
    finally:
        conn.close()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        user_id = request.form.get("user_id")
        terms = request.form.get("terms")
        if not terms:
            return render_template("index.html", error="Please accept the Terms and Conditions.")
        if not user_id:
            return render_template("index.html", error="Please enter your User ID.")
        # 存到 session
        session["user_id"] = user_id
        return redirect(url_for("query_page", query_id=1))
    return render_template("index.html")

@app.route("/query/<int:query_id>", methods=["GET", "POST"])
def query_page(query_id):
    """
    1) 若 user 未登录，跳转回 index
    2) 若 POST，跳到下个页面
    3) 若 GET，则根据 user_id + query_id 在 orders 表查找是否已有 doc_order。
       - 如果有就用那顺序
       - 如果无就随机(或拉丁方)生成，存入 orders
       - 再按此顺序获取 documents 并渲染
    """
    if "user_id" not in session:
        return redirect(url_for("index"))
    user_id = session["user_id"]

    if request.method == "POST":
        if query_id < 3:
            return redirect(url_for("query_page", query_id=query_id + 1))
        else:
            return redirect(url_for("thanks"))

    # 连接数据库
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 1) 在 orders 表中查找是否已有 doc_order
            c.execute("SELECT doc_order FROM orders WHERE user_id=%s AND query_id=%s", (user_id, query_id))
            row = c.fetchone()
            if row:
                # 已有固定顺序
                doc_order_str = row["doc_order"]  # e.g. "2,5,9,4,1,3,7,8,6"
                doc_order = [int(x) for x in doc_order_str.split(",")]
            else:
                # 第一次访问 -> 用拉丁方生成 doc_order
                c.execute("SELECT id FROM documents WHERE qid=%s ORDER BY docno LIMIT 9", (query_id,))
                raw_doc_ids = [r["id"] for r in c.fetchall()]  # 9篇文档
            
                # 1) 生成 9×9 拉丁方(只做一次,可放全局变量)
                #   square_9 = generate_latin_square_cyclic(9)
            
                # 2) 计算 row_index
                row_index = (abs(hash(user_id)) + query_id) % 9
            
                # 3) 取这一行
                perm = square_9[row_index]  # e.g. [2,5,9,4,1,3,7,8,6]
            
                # 4) 重排 doc_ids
                doc_order = [ raw_doc_ids[perm[i] - 1] for i in range(9) ]
            
                # 存到 orders 表
                doc_order_str = ",".join(str(x) for x in doc_order)
                c.execute("INSERT INTO orders (user_id, query_id, doc_order) VALUES (%s, %s, %s)",
                          (user_id, query_id, doc_order_str))
                conn.commit()

            # 2) 按 doc_order 的顺序获取文档详情
            if not doc_order:
                # 如果没有任何文档ID(不大可能), docs=[]
                docs = []
            else:
                placeholders = ",".join(["%s"]*len(doc_order))  # e.g. "%s,%s,%s..."
                sql = f"SELECT id, title, content, docno FROM documents WHERE qid=%s AND id IN ({placeholders})"
                params = [query_id] + doc_order
                c.execute(sql, params)
                rows = c.fetchall()
                # rows里顺序不一定与 doc_order 一致, 需要手动reorder
                doc_map = {r["id"]: r for r in rows}
                docs = [doc_map[d] for d in doc_order if d in doc_map]
    finally:
        conn.close()

    query_content = QUERY_CONTENTS.get(query_id, "")
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

if __name__ == '__main__':
    init_db()  # 容器启动/本地启动时自动建表
    app.run(host="0.0.0.0", port=5000)
