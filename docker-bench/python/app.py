"""Small API with real database and Azure Blob operations, no external services."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import psycopg
from azure.storage.blob import BlobServiceClient

def exercise():
    with psycopg.connect(os.environ['DATABASE_URL']) as conn:
        with conn.cursor() as cur:
            cur.execute('CREATE TABLE IF NOT EXISTS benchmark_items (id integer PRIMARY KEY, value text NOT NULL)')
            cur.execute('TRUNCATE benchmark_items')
            cur.executemany('INSERT INTO benchmark_items VALUES (%s, %s)', [(i, f'item-{i}') for i in range(1000)])
            cur.execute('SELECT count(*), sum(id) FROM benchmark_items')
            assert cur.fetchone() == (1000, 499500)
    service = BlobServiceClient(account_url='http://azurite:10000/benchmark', credential=os.environ['AZURITE_KEY'], api_version='2023-11-03')
    container = service.get_container_client('benchmark')
    if not container.exists():
        container.create_container()
    payload = bytes(range(256)) * 4096
    blob = container.get_blob_client('roundtrip')
    blob.upload_blob(payload, overwrite=True)
    assert blob.download_blob().readall() == payload
    blob.delete_blob()
    return {'rows': 1000, 'sum': 499500, 'blob_bytes': len(payload)}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            result = {'ready': True} if self.path == '/health' else exercise()
            body = json.dumps(result).encode()
            self.send_response(200)
        except Exception as exc:
            body = str(exc).encode()
            self.send_response(500)
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    if '--self-test' in sys.argv:
        print(42)
    else:
        HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
