from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import pymysql
import os
from datetime import datetime
from urllib.parse import urlparse
import pandas as pd

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
    创建 queries, documents, orders, logs 四张表(若不存在)。
    不插入任何示例数据。
    """
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # --- 1) logs 表 ---
            c.execute("SHOW TABLES LIKE 'logs'")
            if not c.fetchone():
                c.execute('''
                    CREATE TABLE logs (
                      id INT AUTO_INCREMENT PRIMARY KEY,
                      user_id VARCHAR(100) NOT NULL,     -- 用户ID
                      qid INT DEFAULT 0,                 -- 查询ID (可选)
                      docno VARCHAR(255) DEFAULT '',     -- 文档标号，使用VARCHAR
                      event_type VARCHAR(100) NOT NULL,  -- "PASSAGE_SELECTION", "OPEN_DOC", ...
                      start_idx INT DEFAULT -1,          -- 选文起始索引，没有就 -1
                      end_idx INT DEFAULT -1,            -- 选文结束索引，没有就 -1
                      duration INT DEFAULT 0,            -- 上一次到本次事件的耗时
                      pass_flag TINYINT DEFAULT 0,       -- 0 or 1
                      timestamp DATETIME                 -- 记录时间
                    )
                ''')
                print("Created table: logs")

            # --- 2) documents 表 ---
            c.execute("SHOW TABLES LIKE 'documents'")
            if not c.fetchone():
                # 如果 documents 表不存在，则创建，docno使用VARCHAR
                c.execute('''
                    CREATE TABLE documents (
                        id INT PRIMARY KEY,
                        qid INT,
                        docno VARCHAR(255),
                        content TEXT
                    )
                ''')
                print("Created table: documents")
            else:
                # 修改docno列类型为VARCHAR
                try:
                    c.execute("ALTER TABLE documents MODIFY COLUMN docno VARCHAR(255)")
                    print("Modified docno column to VARCHAR(255)")
                except Exception as e:
                    print(f"修改列类型时出错: {e}")

            # --- 3) orders 表 ---
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

            # --- 4) queries 表 ---
            c.execute("SHOW TABLES LIKE 'queries'")
            if not c.fetchone():
                # 如果 queries 表不存在，则创建
                c.execute('''
                    CREATE TABLE queries (
                        id INT PRIMARY KEY,
                        content TEXT
                    )
                ''')
                print("Created table: queries")

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
                raw_docnos = [r["id"] for r in c.fetchall()]

                # 计算 row_index
                row_index = (abs(hash(user_id)) + query_id) % 9
                # 取拉丁方的一行
                perm = LATIN_9x9[row_index]  # e.g. [2,5,9,4,1,3,7,8,6]

                # 重排 docnos
                # 这里假设 raw_docnos 至少有 9 篇文档，否则会 index out of range
                # 如果不一定有 9 篇，可以加个判断
                doc_order = [raw_docnos[perm[i] - 1] for i in range(9)]
                doc_order_str = ",".join(str(x) for x in doc_order)

                # 存到 orders 表
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
                # 需手动按 doc_order 排序
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

    user_id    = data.get('userId')
    qid        = data.get('qid', 0)
    docno      = data.get('docno', 0)
    event_type = data.get('eventType', "")
    start_idx  = data.get('startIndex', -1)
    end_idx    = data.get('endIndex', -1)
    duration   = data.get('duration', 0)
    pass_flag  = data.get('passFlag', 0)
    timestamp  = datetime.now()  # Use datetime.now() for a proper DATETIME value

    conn = get_connection()
    try:
        with conn.cursor() as c:
            sql = """
                INSERT INTO logs (user_id, qid, docno, event_type, start_idx, end_idx, duration, pass_flag, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            c.execute(sql, (user_id, qid, docno, event_type, start_idx, end_idx, duration, pass_flag, timestamp))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'Log received'}), 200

def import_df_to_database(df):
    """
    从DataFrame导入数据到数据库的queries和documents表。
    DataFrame应包含qid, query, docno, text列。
    如果表不存在，会先创建表结构。
    """
    # 先确保表结构存在
    init_db()
    
    # 先插入查询，再插入文档
    insert_queries_from_df(df)
    insert_documents_from_df(df)
    
def insert_queries_from_df(df):
    """
    从DataFrame导入唯一查询到queries表。
    """
    # 获取唯一查询
    unique_queries = df[['qid', 'query']].drop_duplicates().reset_index(drop=True)
    
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 检查已存在的查询ID
            c.execute("SELECT id FROM queries")
            existing_ids = [row['id'] for row in c.fetchall()]
            
            # 准备插入数据
            insert_data = []
            for _, row in unique_queries.iterrows():
                # 如果查询ID已存在则跳过
                if row['qid'] in existing_ids:
                    continue
                    
                insert_data.append((
                    row['qid'],      # id
                    row['query']     # content
                ))
                
            if insert_data:
                # 批量插入数据到queries表
                insert_sql = """
                    INSERT INTO queries (id, content)
                    VALUES (%s, %s)
                """
                c.executemany(insert_sql, insert_data)
                
        conn.commit()
        print(f"成功插入 {len(insert_data)} 条记录到queries表")
    except Exception as e:
        print(f"插入queries时出错: {e}")
        conn.rollback()
    finally:
        conn.close()

def insert_documents_from_df(df):
    """
    从DataFrame导入文档数据到documents表。
    将'text'列映射到数据库的'content'列。
    """
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 获取当前最大id作为起点
            c.execute("SELECT MAX(id) as max_id FROM documents")
            result = c.fetchone()
            start_id = result['max_id'] if result['max_id'] is not None else 0
            
            # 准备插入数据
            insert_data = []
            for i, row in df.iterrows():
                doc_id = start_id + i + 1
                insert_data.append((
                    doc_id,           # id
                    row['qid'],       # qid
                    row['docno'],     # docno (VARCHAR类型，可以直接插入字符串)
                    row['text']       # content (从'text'映射)
                ))
                
            # 批量插入数据到documents表
            insert_sql = """
                INSERT INTO documents (id, qid, docno, content)
                VALUES (%s, %s, %s, %s)
            """
            c.executemany(insert_sql, insert_data)
            
        conn.commit()
        print(f"成功插入 {len(df)} 条记录到documents表")
    except Exception as e:
        print(f"插入documents时出错: {e}")
        conn.rollback()
    finally:
        conn.close()


# 在容器/本地启动时，自动建表并插入初始数据（如空）
init_db()

try:
    # 读取CSV文件
    df = pd.read_csv("selected_docs.csv")
    
    # 检查必要的列是否存在
    required_columns = ['qid', 'query', 'docno', 'text']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        print(f"错误: CSV文件缺少以下列: {', '.join(missing_columns)}")
    else:
        # 导入数据到数据库
        import_df_to_database(df)
        print(f"成功从 selected_docs.csv 导入数据")
except Exception as e:
    print(f"导入数据时出错: {e}")

def check_query_document_counts():
    """检查每个查询ID下的文档数量，并输出统计信息"""
    conn = get_connection()
    try:
        with conn.cursor() as c:
            # 获取所有查询ID
            c.execute("SELECT id FROM queries ORDER BY id")
            query_ids = [row['id'] for row in c.fetchall()]
            
            print(f"总共有 {len(query_ids)} 个查询")
            
            # 检查每个查询ID下的文档数量
            query_counts = {}
            for qid in query_ids:
                c.execute("SELECT COUNT(*) as doc_count FROM documents WHERE qid=%s", (qid,))
                count = c.fetchone()['doc_count']
                query_counts[qid] = count
                print(f"查询ID {qid} 有 {count} 个文档")
            
            # 统计分析
            exact_nine = sum(1 for count in query_counts.values() if count == 9)
            less_than_nine = sum(1 for count in query_counts.values() if count < 9)
            more_than_nine = sum(1 for count in query_counts.values() if count > 9)
            zero_docs = sum(1 for count in query_counts.values() if count == 0)
            
            print("\n统计信息:")
            print(f"正好有9个文档的查询: {exact_nine}")
            print(f"少于9个文档的查询: {less_than_nine}")
            print(f"多于9个文档的查询: {more_than_nine}")
            print(f"没有文档的查询: {zero_docs}")
            
            # 找出文档数少于9的查询ID
            if less_than_nine > 0:
                print("\n文档数少于9的查询ID:")
                for qid, count in query_counts.items():
                    if count < 9:
                        print(f"查询ID {qid}: {count} 个文档")
    finally:
        conn.close()

# 调用函数
check_query_document_counts()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
