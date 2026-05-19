import multiprocessing

# Workers: (2 x CPU cores) + 1, capped at 8 for memory safety
workers = min((2 * multiprocessing.cpu_count()) + 1, 8)
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8000"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
loglevel = "info"
forwarded_allow_ips = "*"
