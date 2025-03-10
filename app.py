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
        print("ERROR: No user_id in session, redirecting to index")
        return redirect(url_for("index"))
    
    user_id = session["user_id"]
    print(f"DEBUG: Processing query_page for user_id={user_id}, query_id={query_id}")

    if request.method == "POST":
        if query_id < 3:
            return redirect(url_for("query_page", query_id=query_id + 1))
        else:
            return redirect(url_for("thanks"))

    # 默认值，以防查询失败
    query_content = f"Query {query_id} (No data available)"
    docs = []
    
    try:
        conn = get_connection()
        try:
            with conn.cursor() as c:
                # 1. 查询内容
                c.execute("SELECT content FROM queries WHERE id=%s", (query_id,))
                row_q = c.fetchone()
                if row_q and row_q["content"]:
                    query_content = row_q["content"]
                    print(f"DEBUG: Found query content: '{query_content}'")
                else:
                    print(f"DEBUG: No query content found for query_id={query_id}")

                # 2. 文档顺序
                c.execute("SELECT doc_order FROM orders WHERE user_id=%s AND query_id=%s", (user_id, query_id))
                row_o = c.fetchone()
                if row_o and row_o["doc_order"]:
                    # 已有顺序，解析字符串为文档ID列表
                    doc_order_str = row_o["doc_order"]
                    try:
                        doc_order = [int(x) for x in doc_order_str.split(",") if x.strip()]
                        print(f"DEBUG: Found existing doc_order: {doc_order}")
                    except ValueError as e:
                        print(f"ERROR: Failed to parse doc_order '{doc_order_str}': {str(e)}")
                        doc_order = []
                else:
                    # 生成新的顺序
                    print(f"DEBUG: No existing doc_order, generating new one")
                    c.execute("SELECT id FROM documents WHERE qid=%s ORDER BY id", (query_id,))
                    raw_docnos = [r["id"] for r in c.fetchall()]
                    print(f"DEBUG: Retrieved raw_docnos: {raw_docnos}, length: {len(raw_docnos)}")
                    
                    if not raw_docnos:
                        print(f"WARNING: No documents found for query_id={query_id}")
                        doc_order = []
                    else:
                        # 处理文档数量
                        if len(raw_docnos) >= 9:
                            # 计算 row_index
                            row_index = (abs(hash(user_id)) + query_id) % 9
                            print(f"DEBUG: Using Latin square row_index={row_index}")
                            # 取拉丁方的一行
                            perm = LATIN_9x9[row_index]
                            print(f"DEBUG: Selected permutation: perm={perm}")
                            
                            try:
                                # 安全地重排文档
                                doc_order = []
                                for i in range(min(9, len(raw_docnos))):
                                    idx = perm[i] - 1
                                    if 0 <= idx < len(raw_docnos):  # 安全检查
                                        doc_order.append(raw_docnos[idx])
                                print(f"DEBUG: Generated doc_order={doc_order}")
                            except Exception as e:
                                print(f"ERROR: Failed to generate doc_order: {str(e)}")
                                doc_order = raw_docnos[:min(9, len(raw_docnos))]
                        else:
                            print(f"WARNING: Only {len(raw_docnos)} documents found for query_id={query_id}, expected at least 9")
                            doc_order = raw_docnos.copy()
                    
                    # 如果生成了文档顺序，存入orders表
                    if doc_order:
                        doc_order_str = ",".join(str(x) for x in doc_order)
                        try:
                            c.execute("INSERT INTO orders (user_id, query_id, doc_order) VALUES (%s, %s, %s)",
                                    (user_id, query_id, doc_order_str))
                            conn.commit()
                            print(f"DEBUG: Inserted doc_order into orders table")
                        except Exception as e:
                            print(f"ERROR: Failed to insert doc_order: {str(e)}")
                            conn.rollback()
                    else:
                        print(f"WARNING: Empty doc_order, not inserting into orders table")

                # 3. 获取文档详情
                if doc_order:
                    try:
                        placeholders = ",".join(["%s"] * len(doc_order))
                        sql = f"SELECT id, content, docno FROM documents WHERE qid=%s AND id IN ({placeholders})"
                        params = [query_id] + doc_order
                        print(f"DEBUG: Executing SQL: {sql}")
                        print(f"DEBUG: SQL params: {params}")
                        c.execute(sql, params)
                        rows = c.fetchall()
                        print(f"DEBUG: Retrieved {len(rows)} documents")
                        
                        # 需手动按 doc_order 排序
                        doc_map = {r["id"]: r for r in rows}
                        docs = []
                        for d in doc_order:
                            if d in doc_map:
                                # 确保所有字段存在且格式正确
                                doc = doc_map[d]
                                # 确保docno是字符串类型
                                if "docno" in doc and doc["docno"] is not None:
                                    doc["docno"] = str(doc["docno"])
                                else:
                                    doc["docno"] = str(doc["id"]) # 如果docno为空，使用id作为替代
                                
                                # 确保content字段存在
                                if "content" not in doc or doc["content"] is None:
                                    doc["content"] = "文档内容不可用"
                                
                                docs.append(doc)
                        
                        print(f"DEBUG: Final docs list has {len(docs)} documents")
                        # 打印每个文档的基本信息
                        for i, doc in enumerate(docs):
                            print(f"DEBUG: Doc {i+1} - id: {doc['id']}, docno: {doc['docno']}, content length: {len(doc['content']) if 'content' in doc and doc['content'] else 0}")
                    except Exception as e:
                        print(f"ERROR: Failed to retrieve document details: {str(e)}")
                else:
                    print(f"WARNING: Empty doc_order, no documents to retrieve")
        finally:
            conn.close()
            
        # 最终检查传递给模板的数据
        print(f"DEBUG: Sending to template - query_id: {query_id}, query_content: '{query_content}', docs count: {len(docs)}")
        
    except Exception as e:
        import traceback
        print(f"ERROR in query_page: {str(e)}")
        print(traceback.format_exc())
    
    # 添加对模板数据的清理和转换
    # 1. 确保查询内容非空
    if not query_content:
        query_content = f"Query {query_id} (No content available)"
    
    # 2. 确保docs是一个列表且每个文档都有必要的字段
    if not isinstance(docs, list):
        docs = []
    
    # 3. 文档内容的最终检查
    clean_docs = []
    for doc in docs:
        if isinstance(doc, dict):
            clean_doc = {
                "id": doc.get("id", 0),
                "docno": str(doc.get("docno", "")),
                "content": doc.get("content", "文档内容不可用")
            }
            clean_docs.append(clean_doc)
    
    # 如果仍然没有文档，可以添加一个占位符（调试用）
    if not clean_docs and app.config.get("DEBUG", False):
        clean_docs = [{
            "id": 999,
            "docno": "placeholder",
            "content": "This is a placeholder document for testing. If you see this, it means no real documents were retrieved from the database."
        }]

    return render_template("query.html", query_id=query_id, docs=clean_docs, query_content=query_content)

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
