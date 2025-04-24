from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import pymysql
import os
from datetime import datetime
from urllib.parse import urlparse
import pandas as pd
from itertools import permutations
from dbutils.pooled_db import PooledDB
from functools import lru_cache
import time
from flask import g

app = Flask(__name__)
app.secret_key = "your_secret_key"

DEBUG_ENABLED = True 

# ---------- 1. 添加全局缓存 ----------
# 缓存变量 - 在全局级别定义
QUERY_CACHE = {}  # 查询内容缓存 {query_id: content}
DOC_ORDER_CACHE = {}  # 文档顺序缓存 {(user_id, query_id): doc_order_list}
DOC_CONTENT_CACHE = {}  # 文档内容缓存 {(qid, doc_id): doc_content}
LAST_CACHE_CLEAR = time.time()  # 上次清理缓存的时间
CACHE_TTL = 5400  # 缓存生存时间（秒）

def debug_print(message):
    """只在DEBUG_ENABLED为True时打印调试信息"""
    if DEBUG_ENABLED:
        print(message)
        
# ------------------ 1) 拉丁方生成 ------------------
def generate_latin_square(N):
    """
    生成一个 N×N 的拉丁方，每行都是完全不同的排列。
    """
    
    # 基础行 (1,2,...,N)
    base_row = list(range(1, N+1))
    
    # 获取所有可能的排列
    all_permutations = list(permutations(base_row))
    
    # 选择N个互不相同的排列
    square = []
    for i in range(N):
        # 使用固定的算法选择排列，确保每次选择的都不同
        square.append(list(all_permutations[i * (len(all_permutations) // N)]))
    
    return square

# 预先生成一个 9×9 的拉丁方，用于9篇文档的排列
LATIN_9x9 = generate_latin_square(9)

# ------------------ 2) 用户-行映射函数 ------------------
def get_user_row_index(user_id, total_rows=9):
    """
    基于用户ID确定性地分配拉丁方行索引
    """
    # 确保用户ID是字符串
    user_id_str = str(user_id)
    
    # 使用更好的哈希函数 - 位置加权字符哈希
    hash_value = sum(ord(c) * (i+1) for i, c in enumerate(user_id_str))
    
    # 取模得到行索引
    return hash_value % total_rows
    
# ------------------ 2) MySQL 连接 ------------------
# 修改连接池配置，增加最大连接数和超时设置
def create_pool():
    url = os.environ["MYSQL_URL"]
    parsed = urlparse(url)
    return PooledDB(
        creator=pymysql,
        host=parsed.hostname,
        port=parsed.port, 
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip('/'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        maxconnections=20,      # 增加最大连接数
        mincached=5,            # 最小空闲连接数
        maxcached=10,           # 最大空闲连接数
        blocking=True,          # 连接池满时阻塞
        maxusage=1000,          # 一个连接最多被使用的次数
        setsession=[],          # 连接时执行的命令列表
        ping=1                  # 自动检查连接是否可用
    )

# 初始化连接池
db_pool = create_pool()

# 替换原来的get_connection函数
def get_connection():
    """从连接池获取连接而不是每次创建新连接"""
    return db_pool.connection()
    

#def get_connection():
    """
    通过 MYSQL_URL 解析 MySQL DSN (host, port, user, password, db) 并返回连接
    """
    #url = os.environ["MYSQL_URL"]  # e.g. "mysql://root:xxxx@containers-xxx:3306/railway"
    #parsed = urlparse(url)
    #host = parsed.hostname
    #port = parsed.port
    #user = parsed.username
    #password = parsed.password
    #db = parsed.path.lstrip('/')
    #return pymysql.connect(
        #host=host,
        #port=port,
        #user=user,
        #password=password,
        #db=db,
        #charset='utf8mb4',
        #cursorclass=pymysql.cursors.DictCursor
    #)
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

AVAILABLE_QUERY_IDS = []

@lru_cache(maxsize=1)  # 使用Python内置的LRU缓存
def get_available_query_ids():
    """从数据库获取所有可用的查询ID - 添加缓存"""
    query_ids = []
    try:
        conn = get_connection()
        try:
            with conn.cursor() as c:
                c.execute("SELECT id FROM queries ORDER BY id")
                query_ids = [row['id'] for row in c.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        print(f"ERROR: Failed to get available query IDs: {str(e)}")
    return query_ids

# 在应用启动时加载查询ID列表
@app.before_first_request
def load_query_ids():
    """在应用启动时加载所有可用的查询ID"""
    global AVAILABLE_QUERY_IDS
    AVAILABLE_QUERY_IDS = get_available_query_ids()
    print(f"INFO: Loaded {len(AVAILABLE_QUERY_IDS)} available query IDs: {AVAILABLE_QUERY_IDS}")

# 替换原来的index路由，添加查询ID信息
@app.route("/", methods=["GET", "POST"])
def index():
    """
    首页：用户输入 user_id 并勾选 T&C。
    """
    global AVAILABLE_QUERY_IDS
    
    # 确保查询ID列表已加载
    if not AVAILABLE_QUERY_IDS:
        AVAILABLE_QUERY_IDS = get_available_query_ids()
        
    if request.method == "POST":
        user_id = request.form.get("user_id")
        terms = request.form.get("terms")
        if not terms:
            return render_template("index.html", error="Please accept the Terms and Conditions.")
        if not user_id:
            return render_template("index.html", error="Please enter your User ID.")
        
        session["user_id"] = user_id
        
        # 如果有可用的查询ID，重定向到第一个
        if AVAILABLE_QUERY_IDS:
            first_query_position = 1  # 这是位置，不是ID
            return redirect(url_for("query_page", query_position=first_query_position))
        else:
            return render_template("index.html", error="No queries available in the database.")
            
    return render_template("index.html", query_count=len(AVAILABLE_QUERY_IDS))

# 4. 确保清理缓存函数包含日志
def clear_old_caches():
    """定期清理过期缓存"""
    global LAST_CACHE_CLEAR
    current_time = time.time()
    
    # 每隔CACHE_TTL秒清理一次缓存
    if current_time - LAST_CACHE_CLEAR > CACHE_TTL:
        # 记录清理前的缓存大小
        before_size = {
            'QUERY_CACHE': len(QUERY_CACHE),
            'DOC_ORDER_CACHE': len(DOC_ORDER_CACHE),
            'DOC_CONTENT_CACHE': len(DOC_CONTENT_CACHE)
        }
        
        # 清理缓存
        QUERY_CACHE.clear()
        DOC_ORDER_CACHE.clear()
        DOC_CONTENT_CACHE.clear()
        LAST_CACHE_CLEAR = current_time
        
        print(f"INFO: 已清理缓存 (之前大小: QUERY={before_size['QUERY_CACHE']}, " +
              f"ORDER={before_size['DOC_ORDER_CACHE']}, CONTENT={before_size['DOC_CONTENT_CACHE']})")

def debug_print(message):
    """增强的调试日志函数"""
    if DEBUG_ENABLED:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        print(f"[DEBUG {timestamp}] {message}")
        
# ---------- 2. 优化数据库连接管理 ----------
@app.before_request
def before_request():
    """每个请求前设置数据库连接"""
    g.db_conn = get_connection()
    g.start_time = time.time()

@app.teardown_request
def teardown_request(exception=None):
    """每个请求后关闭数据库连接"""
    db_conn = getattr(g, 'db_conn', None)
    if db_conn is not None:
        db_conn.close()
    
    # 打印请求处理时间（可选，用于性能分析）
    if DEBUG_ENABLED:
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            print(f"DEBUG: Request processed in {duration:.3f} seconds")

# ---------- 3. 优化数据库查询函数 ----------
def get_query_content(query_id):
    """获取查询内容，使用缓存"""
    # 检查缓存
    if query_id in QUERY_CACHE:
        debug_print(f"DEBUG: Cache hit for query_id={query_id}")
        return QUERY_CACHE[query_id]
    
    debug_print(f"DEBUG: Cache miss for query_id={query_id}")
    # 缓存未命中，从数据库获取
    conn = g.db_conn
    with conn.cursor() as c:
        c.execute("SELECT content FROM queries WHERE id=%s", (query_id,))
        row = c.fetchone()
        if row and row["content"]:
            # 更新缓存
            QUERY_CACHE[query_id] = row["content"]
            return row["content"]
    
    # 默认返回
    return f"Query {query_id} (No data available)"

def get_doc_order(user_id, query_id):
    """获取文档顺序，使用缓存"""
    cache_key = (user_id, query_id)
    
    # 检查缓存
    if cache_key in DOC_ORDER_CACHE:
        debug_print(f"DEBUG: Doc order cache hit for user={user_id}, query={query_id}")
        return DOC_ORDER_CACHE[cache_key]
    
    debug_print(f"DEBUG: Doc order cache miss for user={user_id}, query={query_id}")
    # 缓存未命中，从数据库获取
    conn = g.db_conn
    with conn.cursor() as c:
        c.execute("SELECT doc_order FROM orders WHERE user_id=%s AND query_id=%s", (user_id, query_id))
        row = c.fetchone()
        if row and row["doc_order"]:
            # 已有顺序
            doc_order_str = row["doc_order"]
            doc_order = [int(x) for x in doc_order_str.split(",")]
            
            # 更新缓存
            DOC_ORDER_CACHE[cache_key] = doc_order
            return doc_order
    
    # 没有找到顺序，返回空列表（外部会处理）
    return []

# 3. 改进get_documents_for_query函数，确保缓存正常工作
def get_documents_for_query(query_id, doc_order):
    """高效获取文档内容，使用批量查询和缓存"""
    if not doc_order:
        return []
    
    debug_print(f"获取文档: query_id={query_id}, doc_order长度={len(doc_order)}")
    
    # 收集需要查询的文档IDs
    uncached_ids = []
    doc_map = {}
    
    # 首先检查缓存
    cache_hits = 0
    for doc_id in doc_order:
        cache_key = (int(query_id), int(doc_id))  # 确保使用整数类型作为键
        if cache_key in DOC_CONTENT_CACHE:
            # 从缓存获取
            doc_map[doc_id] = DOC_CONTENT_CACHE[cache_key]
            cache_hits += 1
        else:
            # 需要从数据库查询
            uncached_ids.append(doc_id)
    
    debug_print(f"文档缓存命中: {cache_hits}/{len(doc_order)}")
    
    # 如果有未缓存的文档，批量查询
    if uncached_ids:
        debug_print(f"从数据库获取 {len(uncached_ids)} 个未缓存的文档")
        conn = g.db_conn
        with conn.cursor() as c:
            placeholders = ",".join(["%s"] * len(uncached_ids))
            sql = f"SELECT id, content, docno FROM documents WHERE qid=%s AND id IN ({placeholders})"
            params = [query_id] + uncached_ids
            c.execute(sql, params)
            rows = c.fetchall()
            
            debug_print(f"查询返回 {len(rows)} 个文档")
            
            # 更新缓存和临时映射
            for row in rows:
                # 确保所有必要字段存在
                if "docno" not in row or row["docno"] is None:
                    row["docno"] = str(row["id"])
                else:
                    row["docno"] = str(row["docno"])
                
                if "content" not in row or row["content"] is None:
                    row["content"] = "文档内容不可用"
                
                # 更新缓存和文档映射
                cache_key = (int(query_id), int(row["id"]))  # 确保使用整数类型
                DOC_CONTENT_CACHE[cache_key] = row
                doc_map[row["id"]] = row
    
    # 按doc_order排序并返回文档
    result = [doc_map[d] for d in doc_order if d in doc_map]
    debug_print(f"最终返回 {len(result)} 个文档")
    return result
    
def generate_store_doc_order(user_id, query_id):
    """生成并存储文档顺序"""
    conn = g.db_conn
    with conn.cursor() as c:
        # 获取原始文档ID列表
        c.execute("SELECT id FROM documents WHERE qid=%s ORDER BY id", (query_id,))
        raw_docnos = [r["id"] for r in c.fetchall()]
        
        if not raw_docnos:
            return []
            
        # 处理文档顺序
        if len(raw_docnos) >= 9:
            # 计算 row_index
            row_index = get_user_row_index(user_id)
            # 取拉丁方的一行
            perm = LATIN_9x9[row_index]
            
            # 安全地重排文档
            doc_order = []
            for i in range(9):
                idx = perm[i] - 1
                if 0 <= idx < len(raw_docnos):  # 安全检查
                    doc_order.append(raw_docnos[idx])
        else:
            doc_order = raw_docnos.copy()
        
        # 存到 orders 表
        if doc_order:
            doc_order_str = ",".join(str(x) for x in doc_order)
            c.execute("INSERT INTO orders (user_id, query_id, doc_order) VALUES (%s, %s, %s)",
                    (user_id, query_id, doc_order_str))
            conn.commit()
            
            # 更新缓存
            cache_key = (user_id, query_id)
            DOC_ORDER_CACHE[cache_key] = doc_order
            
            return doc_order
        return []
        
# 2. 修复缓存键和查询页面函数
@app.route("/query/<int:query_position>", methods=["GET", "POST"])
def query_page(query_position):
    """优化后的查询页面处理函数"""
    global AVAILABLE_QUERY_IDS
    
    # 记录开始时间以计算总处理时间
    start_time = time.time()
    
    # 清理过期缓存
    clear_old_caches()
    
    # 确保查询ID列表已加载
    if not AVAILABLE_QUERY_IDS:
        AVAILABLE_QUERY_IDS = get_available_query_ids()
    
    # 确保查询位置有效
    if query_position < 1 or query_position > len(AVAILABLE_QUERY_IDS):
        return redirect(url_for("index"))
    
    # 获取实际的查询ID
    query_id = AVAILABLE_QUERY_IDS[query_position - 1]
    debug_print(f"处理查询: position={query_position}, actual_id={query_id}")
    
    if "user_id" not in session:
        return redirect(url_for("index"))
    
    user_id = session["user_id"]
    debug_print(f"用户ID: {user_id}")
    
    # 记录用户首次访问某个查询的时间
    is_first_visit = False
    if "visited_positions" not in session:
        session["visited_positions"] = []
        
    if query_position not in session["visited_positions"]:
        session["visited_positions"].append(query_position)
        is_first_visit = True
        debug_print(f"首次访问查询位置 {query_position}")
    
    if request.method == "POST":
        if query_position < len(AVAILABLE_QUERY_IDS):
            return redirect(url_for("query_page", query_position=query_position + 1))
        else:
            return redirect(url_for("thanks"))
    
    # 跟踪每个步骤的时间
    timing = {}
    
    # 获取查询内容 - 使用缓存
    step_start = time.time()
    query_content = get_query_content(query_id)
    timing['query_content'] = time.time() - step_start
    
    # 获取文档顺序 - 使用缓存
    step_start = time.time()
    doc_order = get_doc_order(user_id, query_id)
    timing['doc_order'] = time.time() - step_start
    
    # 如果没有文档顺序，生成并存储
    if not doc_order:
        step_start = time.time()
        doc_order = generate_store_doc_order(user_id, query_id)
        timing['generate_order'] = time.time() - step_start
    
    # 获取文档内容 - 使用缓存和批量查询
    step_start = time.time()
    docs = get_documents_for_query(query_id, doc_order)
    timing['documents'] = time.time() - step_start
    
    # 输出详细的性能信息
    total_time = time.time() - start_time
    debug_print(f"性能分析: query_content={timing.get('query_content', 0):.4f}s, " +
                f"doc_order={timing.get('doc_order', 0):.4f}s, " +
                f"generate_order={timing.get('generate_order', 0) if 'generate_order' in timing else 'N/A'}, " +
                f"documents={timing.get('documents', 0):.4f}s, " +
                f"total={total_time:.4f}s")
    
    # 输出缓存统计信息
    debug_print(f"缓存状态: QUERY_CACHE={len(QUERY_CACHE)}项, " +
                f"DOC_ORDER_CACHE={len(DOC_ORDER_CACHE)}项, " +
                f"DOC_CONTENT_CACHE={len(DOC_CONTENT_CACHE)}项")
    
    # 渲染模板
    return render_template(
        "query.html", 
        query_id=query_id,
        query_position=query_position,
        total_queries=len(AVAILABLE_QUERY_IDS),
        docs=docs, 
        query_content=query_content,
        is_first_visit=is_first_visit
    )

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

def clear_tables_before_import():
    """简单清空所有相关表"""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as c:
                
                # 删除文档表数据
                c.execute("DELETE FROM documents")
                
                # 删除查询表数据
                c.execute("DELETE FROM queries")
                
                # 提交事务
                conn.commit()
                
                print("已清空所有相关表，准备导入新数据")
                return True
        except Exception as e:
            conn.rollback()  # 出错时回滚
            print(f"清空表时出错: {e}")
            return False
        finally:
            conn.close()
    except Exception as e:
        print(f"连接数据库时出错: {e}")
        return False
        
clear_tables_before_import()

try:
    # 读取CSV文件
    df = pd.read_csv("strategic_selection_results_version2.csv")
    
    # 检查必要的列是否存在
    required_columns = ['qid', 'query', 'docno', 'text']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        print(f"错误: CSV文件缺少以下列: {', '.join(missing_columns)}")
    else:
        # 只保留前27个查询的数据
        unique_qids = df['qid'].unique()[:27]
        filtered_df = df[df['qid'].isin(unique_qids)]
        
        # 检查documents表是否为空
        is_table_empty = True  # 默认假设表为空
        conn = get_connection()
        try:
            with conn.cursor() as c:
                c.execute("SELECT COUNT(*) AS count FROM documents")
                result = c.fetchone()
                document_count = result['count'] if result else 0
                
                if document_count > 0:
                    print(f"跳过导入: documents表已包含{document_count}条记录")
                    is_table_empty = False
        finally:
            conn.close()  # 立即关闭连接
        
        # 如果表为空，执行导入
        if is_table_empty:
            import_df_to_database(filtered_df)  # 使用过滤后的DataFrame
            print(f"成功从 selected_docs.csv 导入前27个查询的数据")

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
