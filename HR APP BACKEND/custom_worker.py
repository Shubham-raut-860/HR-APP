import os
import sys
import logging
import redis

# Ensure HR APP BACKEND is in path to import the plugins
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness.workers.agent_worker import register_agent
from app.agents.harness_plugins import _HR_AGENT_FACTORY

# Use SimpleWorker for Windows compatibility since os.fork is not available
from rq import Queue, SimpleWorker

JDParserClass = _HR_AGENT_FACTORY["jd_parser"]
CareerAnalystClass = _HR_AGENT_FACTORY["career_analyst"]

if __name__ == "__main__":
    register_agent("jd_parser", JDParserClass)
    register_agent("career_analyst", CareerAnalystClass)
    
    conn = redis.from_url("redis://127.0.0.1:6379", decode_responses=False)
    queues = ["default", "agent", "sql", "code", "jd_parser", "career_analyst"]
    queue_objects = [Queue(q, connection=conn) for q in queues]
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("Starting Windows-compatible RQ SimpleWorker...")
    worker = SimpleWorker(queue_objects, connection=conn)
    worker.work(with_scheduler=True)
