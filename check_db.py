import sqlite3
conn = sqlite3.connect(r'C:\xiaojiao\causal-memory\xiaojiao.db')
cur = conn.cursor()
for t in ['causal_edges', 'agent_facts', 'chunks', 'pending_predictions']:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"{t}: {cur.fetchone()[0]} 条")
    except Exception as e:
        print(f"{t}: {e}")
conn.close()
